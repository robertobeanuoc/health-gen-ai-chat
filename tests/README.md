# Tests

Automated tests for the parts of this project where a silent regression would be hardest to
notice and most damaging: the dbt semantic layer (everything else is built on top of it), the SQL
validation guard in `mcp_exec`, and the Streamlit dashboard renderer.

## Running

```bash
uv run pytest tests/                          # everything
uv run pytest tests/test_dbt_semantic_coherence.py -v
uv run pytest tests/test_mcp_exec_validation.py -v
uv run pytest tests/test_streamlit_dashboard.py -v
```

Most tests need the same `.env` MySQL credentials the app itself uses (`MYSQL_HOST`,
`MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`) — they're skipped automatically if those aren't
set, rather than failing with a confusing connection error.

## What's covered

### `test_dbt_semantic_coherence.py` — the most critical layer

Runs `dbt parse` fresh (not against stale `target/` artifacts) and checks the compiled manifests
directly:

- `dbt parse` succeeds at all — a single invalid value anywhere in `semantic_schema.yml` (e.g. a
  dimension `type` that isn't `categorical`/`time`) crashes it outright, silently breaking every
  `mcp_semantic` tool at once.
- Every dbt view model has documented columns (`models_schema.yml`) — regression test for a real
  bug where `get_table_columns`, the tool the LLM is told to trust for "what columns exist,"
  always returned an empty list because no model ever documented its columns.
- Every dimension/entity/measure in `semantic_schema.yml` resolves to a column that actually
  exists on the view it wraps.
- Dimension `type` values are always `categorical`/`time` (the only values MetricFlow accepts).
- No row-bookkeeping columns (`row_created_at`, `row_updated_at`, `created_at`) leak back into
  `source_schema.yml` — they're not the real event timestamp and were removed on purpose.
- `get_table_columns` / `get_model_lineage` / `_resolve_semantic_model_alias` all resolve the
  three ways the LLM might name a model — the raw source table name, the semantic model name, and
  the dbt view name — to the same underlying view.
- `list_local_metrics` actually returns the metrics defined in `metrics_schema.yml` — regression
  test for a second real bug: measures inside `semantic_models` are *not* automatically metrics in
  dbt's semantic layer, so without an explicit top-level `metrics:` block this tool always
  returned `[]`.

### `test_mcp_exec_validation.py` — the database execution guard

Unit tests against `_validate_select_query` (no live database needed — it's a pure function over
SQL text, parsed with `sqlglot`):

- Legitimate `SELECT` queries pass, including `ORDER BY ... DESC` and a column literally named
  `last_updated` — a regression test for the previous keyword-substring matcher, which used to
  reject that column because it contains the substring `UPDATE`.
- Every write/structural statement is blocked by its real AST node type (`INSERT`, `UPDATE`,
  `DELETE`, `DROP`, `ALTER`, `GRANT`, `REPLACE`, `TRUNCATE`, `SHOW`, `DESCRIBE`/`DESC`, and
  multi-statement injection like `SELECT ...; DROP TABLE ...;`).
- `information_schema`, `performance_schema`, `mysql`, and `sys` are blocked, including when
  buried in a subquery — the dbt semantic layer must stay the only source of truth for table and
  column names, not raw schema introspection.
- Malformed SQL is rejected with a parse error instead of being sent to MySQL.

### `test_streamlit_dashboard.py` — the dashboard renderer

Uses Streamlit's own `AppTest` harness (in-process script execution, no server) to check the
renderer handles every supported chart type without crashing. Dashboard configs are built by
calling the real `build_dashboard` tool from `mcp_visualization_health_gen_ai_chat` — not
hand-written JSON — so these tests go through the same validation a chat turn does; `requests.get`
is mocked so nothing touches the real chat backend or database.

Covers: no `message_id`, dashboard not found (404), backend unreachable, every chart type
individually, a chart type `build_dashboard` itself must reject before it ever reaches Streamlit,
an unsupported chart type reaching Streamlit's own defensive fallback directly, a full dashboard
combining every chart type plus metrics and tables, and a chart with no data.

### `test_streamlit_server_e2e.py` — does the real process actually boot

Launches an *actual* `streamlit run src/chat_agent/streamlit_dashboard.py` subprocess, the same
invocation `docker-compose.yml`'s `streamlit` service uses, pointed at a small stdlib HTTP stub
standing in for the FastAPI backend. `AppTest` never boots a real server, so it can't catch a
broken subprocess invocation, port binding, or startup crash — the kind of failure that shows up
in Docker but not in the AppTest suite. Checks the server comes up and serves a page; deep content
assertions are the AppTest suite's job, not this one's — a live server's first HTTP response is
just the SPA shell before Streamlit's WebSocket connects and actually runs the script.

### `test_streamlit_live_glucose_dashboard.py` — the real end-to-end chain

Reproduces the actual sequence of tool calls a chat turn makes for a glucose question, driven
directly instead of through the LLM: `get_table_columns` (mcp_semantic) discovers the view's real
columns → an aggregated `execute_read_query` (mcp_exec) runs against the real database → the real
result rows go through `build_dashboard` (mcp_visualization) → a real Streamlit server renders it.
Unlike every other test here, it deliberately uses real data, not a fixture — the point is to
prove the whole chain works together, not just each piece in isolation. Requires a live MySQL
connection (skipped otherwise).

By default it only checks the page responds; it doesn't linger. Pass `--show-dashboard` to also
print the live URL and pause so you can open it in a browser yourself before the server tears
down:

```bash
uv run pytest tests/test_streamlit_live_glucose_dashboard.py --show-dashboard -s
```

(`-s` is needed so pytest doesn't capture the printed URL.) Leave the flag off for automated runs —
it's meant for a human checking the result interactively, not CI.

## Shared fixtures (`conftest.py`)

- `dbt_project_env` / `mysql_env` — skip a test module cleanly if MySQL credentials aren't set,
  instead of failing with a confusing connection error.
- `dbt_manifests` — runs `dbt parse` fresh and returns the parsed `manifest.json` +
  `semantic_manifest.json`.
- `run_streamlit_server(chat_api_base_url)` — context manager that boots a real Streamlit
  subprocess (the `docker-compose.yml` invocation) against a given backend URL and tears it down
  on exit.
- `run_stub_chat_backend(dashboards_by_message_id)` — context manager for a minimal stdlib HTTP
  server implementing just `GET /api/messages/{id}/dashboard`, used to feed the real Streamlit
  server fixed data without needing the real FastAPI backend or database.
- `show_dashboard` — the `--show-dashboard` flag as a boolean fixture.
