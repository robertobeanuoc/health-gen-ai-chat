"""
Coherence checks for the dbt semantic layer — the most critical part of the
system, since every tool the chat agent uses to discover tables/columns/
metrics (mcp_semantic) reads directly from these compiled artifacts. If this
layer is broken or silently incomplete, everything built on top of it
(SQL generation, dashboards, chat replies) degrades without an obvious error.

These tests run `dbt parse` fresh (see conftest.dbt_manifests) so they catch
regressions introduced by editing the .yml/.sql files directly, not just
bugs in the Python tool code.
"""

import sys

sys.path.insert(0, "src")

from mcp_semantic_healh_gen_ai_chat.main import (  # noqa: E402
    _resolve_semantic_model_alias,
    get_dimensions_by_semantic_model,
    get_model_lineage,
    get_table_columns,
    list_local_metrics,
)

VIEW_MODELS = [
    "view_glucose_register",
    "view_insulin_register",
    "view_food_register",
    "view_strava_activities",
]


def _models_by_name(manifest: dict) -> dict:
    return {
        n["name"]: n
        for n in manifest["nodes"].values()
        if n.get("resource_type") == "model"
    }


def _sources_by_name(manifest: dict) -> dict:
    return {s["name"]: s for s in manifest["sources"].values()}


def test_dbt_parse_succeeds(dbt_manifests):
    """
    The most basic possible check, and the one most likely to catch a real
    mistake: an invalid value anywhere in semantic_schema.yml (e.g. a
    dimension `type` that isn't `categorical`/`time`) makes dbt parse crash
    outright, which silently breaks every mcp_semantic tool at once.
    """
    assert dbt_manifests["manifest"]["nodes"]
    assert dbt_manifests["semantic_manifest"]["semantic_models"]


def test_every_view_model_has_documented_columns(dbt_manifests):
    """
    Regression test for a real bug: models_schema.yml didn't exist, so every
    dbt model node had an empty `columns` dict, and get_table_columns (the
    tool the LLM is told to trust for "what columns exist") silently returned
    an empty list for every single model.
    """
    models = _models_by_name(dbt_manifests["manifest"])
    for view_name in VIEW_MODELS:
        assert view_name in models, f"{view_name} not found in manifest.json"
        columns = models[view_name].get("columns") or {}
        assert columns, f"{view_name} has no documented columns in models_schema.yml"


def test_semantic_model_dimensions_reference_real_columns(dbt_manifests):
    """
    Every dimension/entity/measure `expr` (or bare name when no expr is given)
    in semantic_schema.yml must resolve to a column that actually exists on
    the underlying view — otherwise a metric or dimension the LLM tries to
    use will fail at query time with a confusing "unknown column" error.
    """
    models = _models_by_name(dbt_manifests["manifest"])

    for sm in dbt_manifests["semantic_manifest"]["semantic_models"]:
        model_alias = sm["node_relation"]["alias"]
        assert model_alias in models, (
            f"semantic model '{sm['name']}' points to '{model_alias}', "
            f"which isn't a model in manifest.json"
        )
        view_columns = set(models[model_alias].get("columns", {}).keys())
        assert view_columns, f"{model_alias} has no documented columns to validate against"

        for entity in sm.get("entities", []):
            ref = entity.get("expr") or entity["name"]
            assert ref in view_columns, (
                f"{sm['name']}: entity '{entity['name']}' references column "
                f"'{ref}', not found in {model_alias}'s columns {sorted(view_columns)}"
            )

        for dim in sm.get("dimensions", []):
            ref = dim.get("expr") or dim["name"]
            assert ref in view_columns, (
                f"{sm['name']}: dimension '{dim['name']}' references column "
                f"'{ref}', not found in {model_alias}'s columns {sorted(view_columns)}"
            )

        for measure in sm.get("measures", []):
            ref = measure.get("expr") or measure["name"]
            assert ref in view_columns, (
                f"{sm['name']}: measure '{measure['name']}' references column "
                f"'{ref}', not found in {model_alias}'s columns {sorted(view_columns)}"
            )


def test_dimension_types_are_valid(dbt_manifests):
    """
    Regression test: `type: datetime`/`type: timestamp` were used at one
    point and are not valid MetricFlow dimension types — only `categorical`
    and `time` are. dbt_parse_succeeds would already catch this (dbt crashes
    on an invalid enum value), but this pins down *why*, so a future failure
    here points straight at the cause instead of a generic parse crash.
    """
    valid_types = {"categorical", "time"}
    for sm in dbt_manifests["semantic_manifest"]["semantic_models"]:
        for dim in sm.get("dimensions", []):
            assert dim["type"] in valid_types, (
                f"{sm['name']}: dimension '{dim['name']}' has invalid type "
                f"'{dim['type']}' (must be one of {valid_types})"
            )


def test_no_bookkeeping_columns_leak_into_sources(dbt_manifests):
    """
    row_created_at/row_updated_at/created_at are row-bookkeeping fields, not
    the actual event timestamp — they were removed from source_schema.yml
    on purpose to stop the LLM from confusing them with the real time
    dimension. This guards against them creeping back in.
    """
    forbidden = {"row_created_at", "row_updated_at", "created_at"}
    for source in dbt_manifests["manifest"]["sources"].values():
        documented = set(source.get("columns", {}).keys())
        leaked = documented & forbidden
        assert not leaked, f"source '{source['name']}' documents bookkeeping columns: {leaked}"


def test_get_table_columns_returns_real_columns_for_every_view(dbt_manifests):
    """End-to-end through the actual MCP tool function, not just the manifest."""
    import json

    for view_name in VIEW_MODELS:
        result = json.loads(get_table_columns(view_name))
        assert result["columns"], f"get_table_columns('{view_name}') returned no columns"
        assert result["model"] == view_name


def test_get_table_columns_resolves_raw_source_name(dbt_manifests):
    """
    The LLM may pass the raw source table name (e.g. "glucose_register")
    instead of the dbt view that wraps it — this must redirect to the view,
    not return the (unreachable) raw source's own info.
    """
    import json

    result = json.loads(get_table_columns("glucose_register"))
    assert result["model"] == "view_glucose_register"
    assert "note" in result


def test_get_table_columns_resolves_semantic_model_name(dbt_manifests):
    """The LLM may pass the semantic model name instead of the dbt view name."""
    import json

    result = json.loads(get_table_columns("semantic_glucose_register"))
    assert result["model"] == "view_glucose_register"


def test_get_model_lineage_resolves_all_three_name_forms(dbt_manifests):
    """
    view name, raw source name, and semantic model name must all resolve to
    the same underlying dbt model.
    """
    import json

    by_view = json.loads(get_model_lineage("view_glucose_register"))
    by_source = json.loads(get_model_lineage("glucose_register"))
    by_semantic = json.loads(get_model_lineage("semantic_glucose_register"))

    assert by_view["name"] == by_source["name"] == by_semantic["name"] == "view_glucose_register"


def test_resolve_semantic_model_alias_matches_every_model(dbt_manifests):
    for sm in dbt_manifests["semantic_manifest"]["semantic_models"]:
        alias = _resolve_semantic_model_alias(sm["name"])
        assert alias == sm["node_relation"]["alias"]


def test_list_local_metrics_returns_all_defined_measures(dbt_manifests):
    import json

    metrics = json.loads(list_local_metrics())
    metric_names = {m["name"] for m in metrics}

    expected_measure_names = {
        measure["name"]
        for sm in dbt_manifests["semantic_manifest"]["semantic_models"]
        for measure in sm.get("measures", [])
    }
    # Every measure implicitly becomes a metric in dbt's semantic layer.
    assert expected_measure_names <= metric_names


def test_get_dimensions_by_semantic_model_covers_every_model(dbt_manifests):
    import json

    dimensions = json.loads(get_dimensions_by_semantic_model())
    for sm in dbt_manifests["semantic_manifest"]["semantic_models"]:
        assert sm["name"] in dimensions
        returned_names = {d["name"] for d in dimensions[sm["name"]]}
        expected_names = {d["name"] for d in sm.get("dimensions", [])}
        assert returned_names == expected_names
