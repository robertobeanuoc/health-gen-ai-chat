# Health Gen AI Chat

A natural-language chat agent for personal health data, powered by **Claude** (via Anthropic API), **dbt**, and three **MCP servers**.

Ask questions in plain English, get SQL executed against your databases, and see results as interactive charts — all from a terminal or a browser.

---

## How it works

```
You (terminal or browser)
        │
        ▼
  Chat Agent  ──────  Claude API  (Opus 4.8 in terminal · Haiku 4.5 default in web UI)
        │
        ├── MCP: mcp_semantic        reads dbt artifacts → metrics, columns, lineage
        ├── MCP: mcp_exec            runs read-only SQL against MySQL
        └── MCP: mcp_visualization   validates & builds dashboard configs (Streamlit renders them)
```

The three MCP servers run as child processes of the chat agent. You only need to start the agent. The web UI additionally embeds a separate Streamlit process to render dashboards.

### Data sources

| Source | Schema | Description |
|---|---|---|
| Abbott LibreLink | `cgm_abbot_connector` | Continuous glucose monitor readings |
| Strava | `strava-to-db` | Physical activity records |
| Food recognition | `food_recognition` | Food intake records with glycemic index and carbohydrates |

---

## Prerequisites

| Tool | Version | Install |
|---|---|---|
| [uv](https://docs.astral.sh/uv/) | ≥ 0.4 | `brew install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Python | 3.11.x | managed by uv automatically |
| MySQL | 5.7+ / 8.x | the two source schemas must be reachable |
| Anthropic API key | — | [console.anthropic.com](https://console.anthropic.com) |

---

## Quick start

### 1. Clone and set up the environment

```bash
git clone https://github.com/robertobeanuoc/health-gen-ai-chat.git
cd health-gen-ai-chat

# Create the virtual environment and install all dependencies in one step
uv sync
```

`uv sync` reads `pyproject.toml`, pins Python 3.11, creates `.venv/`, and installs every dependency. The `uv.lock` file ensures reproducible installs across machines.

### 2. Configure dbt

The repository includes `dbt_health_gen_ai_chat/profiles.yml`, which reads connection details from environment variables so **no credentials are hardcoded**:

```yaml
# dbt_health_gen_ai_chat/profiles.yml  (already in the repo)
dbt_health_gen_ai_chat:
  target: dev
  outputs:
    dev:
      type: mysql
      server: "{{ env_var('MYSQL_HOST') }}"
      port: "{{ env_var('MYSQL_PORT', '3306') | int }}"
      schema: "{{ env_var('MYSQL_DATABASE') }}"
      username: "{{ env_var('MYSQL_USER') }}"
      password: "{{ env_var('MYSQL_PASSWORD') }}"
      ssl_disabled: true
```

All dbt commands must be run with `--profiles-dir dbt_health_gen_ai_chat` so dbt finds this file instead of looking in `~/.dbt/`.

Test the connection (after setting the env vars in Step 4):

```bash
uv run dbt debug --project-dir dbt_health_gen_ai_chat --profiles-dir dbt_health_gen_ai_chat
```

### 3. Compile dbt artifacts

The semantic MCP server reads `manifest.json` and `semantic_manifest.json`. Generate them with:

```bash
uv run dbt compile --project-dir dbt_health_gen_ai_chat --profiles-dir dbt_health_gen_ai_chat
```

This creates:

```
dbt_health_gen_ai_chat/target/manifest.json
dbt_health_gen_ai_chat/target/semantic_manifest.json
```

Re-run this command any time you change your dbt models or schema files.

### 4. Set environment variables

Copy the example file and fill in your credentials:

```bash
cp .env.example .env
```

```
# .env
ANTHROPIC_API_KEY=sk-ant-...

# MySQL connection — used by the app, mcp-exec, and dbt
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=your_user
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=your_database
```

Optional — override the Claude model used by the **web UI** (terminal mode always uses `claude-opus-4-8`):

```
CLAUDE_MODEL=claude-haiku-4-5-20251001   # default
# CLAUDE_MODEL=claude-sonnet-4-6
# CLAUDE_MODEL=claude-opus-4-8
```

Only thinking-capable models are supported (`thinking={"type": "adaptive"}` is always enabled).

### 5. Start the chat agent

```bash
uv run python -m src.chat_agent.main
```

```
Health Gen AI Chat — type 'quit' to exit.

You: What is my average glucose by day this week?
```

The agent discovers your data schema, writes SQL, executes it, and returns results. If a dashboard is appropriate it builds one via the visualization MCP server, which the web UI renders through an embedded Streamlit app.

---

## Web UI

`src/chat_agent/index.html` is a responsive dark-theme chat interface that works on desktop, tablet, and mobile. On narrow screens the session sidebar becomes a slide-in drawer toggled by a hamburger button. It sends requests to `POST /api/chat` and, for messages that built a dashboard, embeds a Streamlit iframe scoped to that message — a session can accumulate any number of dashboards this way. The backend server (`src/chat_agent/server.py`) is included in the repo.

The web UI uses `claude-haiku-4-5-20251001` by default. Set `CLAUDE_MODEL` in `.env` to switch to a different thinking-capable model.

Start both processes (FastAPI/Uvicorn and Streamlit are already included in the project dependencies):

```bash
uv run uvicorn src.chat_agent.server:app --reload --port 8000
uv run streamlit run src/chat_agent/streamlit_dashboard.py --server.port 8501
```

Open `http://localhost:8000` in your browser. The Streamlit app at `http://localhost:8501` is only meant to be embedded in the chat UI's iframes — it renders one dashboard per `message_id` query param, not a standalone view.

---

## Docker

The project includes a `docker/Dockerfile` and a `docker-compose.yml` for running the full stack in a container.

### Requirements

- Docker and Docker Compose installed
- A `.env` file in the project root (see [Environment variables](#4-set-environment-variables))

### Build and run

```bash
docker compose up --build
```

The app will be available at `http://localhost:8000`, and the Streamlit dashboard renderer (embedded by the chat UI) at `http://localhost:8501`.

### Environment variables in Docker

Docker Compose reads `.env` from the project root automatically and injects the following variables into the `app` container:

| Variable | Required | Notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | Yes | Anthropic API key |
| `MYSQL_HOST` | Yes | Use your host IP or a Docker network hostname — **not** `localhost` (e.g. `mysql-server` if that's the MySQL container's Docker name on a shared network) |
| `MYSQL_PORT` | No | Defaults to `3306` |
| `MYSQL_USER` | Yes | |
| `MYSQL_PASSWORD` | Yes | |
| `MYSQL_DATABASE` | Yes | |
| `CLAUDE_MODEL` | No | Defaults to `claude-haiku-4-5-20251001` |

The `streamlit` service reuses the same image with a different command, and is given `CHAT_API_BASE_URL=http://app:8000` so it can reach the chat backend over the Docker network.

The dbt artifacts (`manifest.json`, `semantic_manifest.json`) are generated automatically at container startup — no need to compile them before building the image.

Before compiling dbt artifacts or starting the server, the `app` container's entrypoint (`docker/wait_for_mysql.py`) polls `MYSQL_HOST:MYSQL_PORT` with a real PyMySQL connection every 5s and blocks until MySQL accepts it. This matters because the MySQL server (Docker name `mysql-server`) typically runs in its own Compose project here (no `depends_on` across separate compose files), so nothing otherwise stops the app from starting — and failing to connect — before MySQL has finished starting up.

---

## Example questions

**Glucose:**
- *What is my average glucose by day over the last 30 days?*
- *Show me a line chart of my glucose readings for this week.*
- *How many manual readings vs sensor scans did I have last month?*
- *What hour of day do I typically have the highest glucose?*

**Strava:**
- *What is my total running distance per month this year?*
- *Show me a bar chart of activity count by sport type.*
- *What are my top 5 longest rides?*

**Food:**
- *What foods did I eat most this week?*
- *Show me the total carbohydrates I consumed per day this month.*
- *What is my average glycemic index by food type?*
- *Which foods with fast absorption did I eat the most?*

**Cross-domain:**
- *On days when I exercise, is my average glucose lower?*
- *Does eating high-glycemic foods correlate with higher glucose readings?*

---

## Project structure

```
health-gen-ai-chat/
├── pyproject.toml                            # project metadata & dependencies (uv)
├── uv.lock                                   # locked dependency graph
├── docker-compose.yml                        # Docker Compose — builds and runs the app + Streamlit
├── .env.example                              # environment variable template
├── docker/
│   ├── Dockerfile                            # container image for the FastAPI server
│   ├── entrypoint.sh                         # waits for MySQL, compiles dbt artifacts, starts uvicorn
│   └── wait_for_mysql.py                     # entrypoint step: blocks until MySQL (mysql-server) accepts connections
├── dbt_health_gen_ai_chat/                   # dbt project
│   ├── dbt_project.yml
│   ├── models/
│   │   ├── source_schema.yml                 # raw source definitions
│   │   ├── semantic_schema.yml               # semantic models & metrics
│   │   ├── view_glucose_register.sql
│   │   └── view_strava_activities.sql
│   └── target/                               # generated by dbt compile
│       ├── manifest.json
│       └── semantic_manifest.json
├── src/
│   ├── mcp_semantic_healh_gen_ai_chat/       # Semantic MCP server
│   │   └── main.py
│   ├── mcp_exec_health_gen_ai_chat/          # Exec MCP server
│   │   └── main.py
│   ├── mcp_visualization_health_gen_ai_chat/ # Visualization MCP server
│   │   └── main.py
│   └── chat_agent/                           # LLM agent + web UI
│       ├── main.py                           # terminal chat agent
│       ├── server.py                         # FastAPI HTTP server for the web UI
│       ├── streamlit_dashboard.py            # Streamlit dashboard renderer, embedded per-message
│       └── index.html                        # browser chat UI
├── docs/
│   ├── how-to-use.md                         # end-to-end setup guide
│   ├── mcp-semantic.md                       # Semantic MCP server reference
│   ├── mcp-exec.md                           # Exec MCP server reference
│   └── mcp-visualization.md                  # Visualization MCP server reference
└── tests/                                    # pytest suite — see tests/README.md
    ├── conftest.py
    ├── test_dbt_semantic_coherence.py
    ├── test_mcp_exec_validation.py
    ├── test_streamlit_dashboard.py
    ├── test_streamlit_server_e2e.py
    └── test_streamlit_live_glucose_dashboard.py
```

---

## MCP servers

| Server | FastMCP name | Tools |
|---|---|---|
| `mcp_semantic_healh_gen_ai_chat` | `dbt_core_semantic_layer` | `list_local_metrics`, `get_dimensions_by_semantic_model`, `get_model_lineage`, `get_table_columns` |
| `mcp_exec_health_gen_ai_chat` | `mysql_execution_engine` | `execute_read_query` |
| `mcp_visualization_health_gen_ai_chat` | `DashboardEngine` | `get_system_capabilities`, `recommend_visualization`, `validate_chart`, `check_memory`, `build_dashboard` |

See the [`docs/`](docs/) folder for full reference documentation on each server.

---

## Testing

```bash
uv run pytest tests/
```

Covers the dbt semantic layer's coherence (the most critical layer — everything else is built on
top of it), the `mcp_exec` SQL validation guard, and the Streamlit dashboard renderer — including
booting a real Streamlit server the same way `docker-compose.yml` does. See
[`tests/README.md`](tests/README.md) for what each test file covers and how to view a live
dashboard rendered from real data while a test runs (`--show-dashboard`).

---

## Development

### Add a dependency

```bash
uv add <package>          # adds to pyproject.toml and updates uv.lock
```

### Remove a dependency

```bash
uv remove <package>
```

### Sync after pulling changes

```bash
uv sync                   # installs/removes packages to match uv.lock
```

### Run any command in the project environment

```bash
uv run <command>          # no need to activate the venv manually
```

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| `FileNotFoundError: dbt artifact not found` | Run `uv run dbt compile --project-dir dbt_health_gen_ai_chat --profiles-dir dbt_health_gen_ai_chat` |
| `RuntimeError: Missing required env vars: MYSQL_HOST …` | Set `MYSQL_HOST`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` in `.env` |
| `pymysql.err.OperationalError` | Check values of `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE`; confirm the MySQL user has `SELECT` on both source schemas |
| `anthropic.APIError: authentication_error` | Check `ANTHROPIC_API_KEY` is set and valid |
| Dashboards don't render | Confirm the Streamlit process is running on port 8501 and `CHAT_API_BASE_URL` points at the chat backend |

For detailed setup instructions see [docs/how-to-use.md](docs/how-to-use.md).
