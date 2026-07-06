"""
Tests for the timezone handling in mcp_exec. All datetime columns are stored
in UTC, but the user asking questions is not necessarily in UTC — these tests
verify that the offset resolution is correct and that every datetime column
documented in the dbt semantic layer can actually be converted to local time
via CONVERT_TZ(column, 'UTC', @@session.time_zone) once execute_read_query
has set the session time zone.
"""

import json
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, "src")

from mcp_exec_health_gen_ai_chat.main import (  # noqa: E402
    _resolve_timezone_offset,
    execute_read_query,
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


def _datetime_columns(model_node: dict) -> list[str]:
    return [
        name
        for name, info in model_node.get("columns", {}).items()
        if (info.get("data_type") or "").lower().startswith("datetime")
    ]


def test_resolve_timezone_offset_utc_is_zero():
    assert _resolve_timezone_offset("UTC") == "+00:00"


def test_resolve_timezone_offset_matches_zoneinfo():
    for tz_name in ["Europe/Madrid", "America/New_York", "Asia/Tokyo", "Pacific/Kiritimati"]:
        expected_offset = datetime.now(ZoneInfo(tz_name)).utcoffset()
        total_minutes = int(expected_offset.total_seconds() // 60)
        sign = "+" if total_minutes >= 0 else "-"
        total_minutes = abs(total_minutes)
        expected = f"{sign}{total_minutes // 60:02d}:{total_minutes % 60:02d}"
        assert _resolve_timezone_offset(tz_name) == expected


def test_resolve_timezone_offset_rejects_unknown_zone():
    with pytest.raises(ValueError, match="Unknown IANA timezone"):
        _resolve_timezone_offset("Not/A_Real_Zone")


def test_execute_read_query_rejects_invalid_timezone(mysql_env):
    result = execute_read_query("SELECT 1", timezone="Not/A_Real_Zone")
    assert result.startswith("Invalid timezone:")


def test_every_datetime_column_supports_convert_tz(dbt_manifests):
    """
    For every datetime column documented across the dbt models, CONVERT_TZ
    against the session time zone set by execute_read_query must succeed and
    return a real (non-error, non-empty-error) JSON result — otherwise the
    LLM's instructed pattern for timezone conversion would fail at query time.
    """
    models = _models_by_name(dbt_manifests["manifest"])

    checked_at_least_one = False
    for view_name in VIEW_MODELS:
        assert view_name in models, f"{view_name} not found in manifest.json"
        for column in _datetime_columns(models[view_name]):
            checked_at_least_one = True
            sql = (
                f"SELECT CONVERT_TZ({column}, 'UTC', @@session.time_zone) AS converted "
                f"FROM {view_name} LIMIT 1"
            )
            raw = execute_read_query(sql, timezone="Europe/Madrid")
            try:
                rows = json.loads(raw)
            except json.JSONDecodeError:
                pytest.fail(
                    f"execute_read_query on {view_name}.{column} did not return JSON: {raw}"
                )
            assert isinstance(rows, list), (
                f"execute_read_query on {view_name}.{column} returned an error: {raw}"
            )

    assert checked_at_least_one, "no datetime columns found across VIEW_MODELS — test is vacuous"
