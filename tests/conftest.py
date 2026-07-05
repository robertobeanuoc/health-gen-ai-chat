import os
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path

import pytest
from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DBT_PROJECT_DIR = PROJECT_ROOT / "dbt_health_gen_ai_chat"
SRC_DIR = PROJECT_ROOT / "src"

for path in (str(SRC_DIR),):
    if path not in sys.path:
        sys.path.insert(0, path)

load_dotenv(PROJECT_ROOT / ".env")


def pytest_addoption(parser):
    parser.addoption(
        "--show-dashboard",
        action="store_true",
        default=False,
        help="Print live dashboard URLs and pause so you can open them in a "
        "browser (for interactive/manual runs only — leave off in CI/automated runs).",
    )


@pytest.fixture(scope="session")
def show_dashboard(request) -> bool:
    return request.config.getoption("--show-dashboard")


@pytest.fixture(scope="session")
def mysql_env() -> dict:
    """Same as dbt_project_env, but for tests that query MySQL directly (not via dbt)."""
    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing env vars for MySQL: {', '.join(missing)}")
    return dict(os.environ)


@pytest.fixture(scope="session")
def dbt_project_env() -> dict:
    """
    The MySQL connection env vars dbt needs even just to parse the project
    (dbt validates the profile's connection config eagerly). Skips the whole
    dbt-dependent test module if they aren't set, rather than failing with a
    confusing dbt error.
    """
    required = ["MYSQL_HOST", "MYSQL_USER", "MYSQL_PASSWORD", "MYSQL_DATABASE"]
    missing = [name for name in required if not os.getenv(name)]
    if missing:
        pytest.skip(f"Missing env vars for dbt: {', '.join(missing)}")
    return dict(os.environ)


@pytest.fixture(scope="session")
def dbt_manifests(dbt_project_env: dict) -> dict:
    """
    Runs `dbt parse` fresh against the current state of the dbt project files
    so tests validate what's on disk right now, not stale target/ artifacts
    from a previous run. Returns the parsed manifest.json and
    semantic_manifest.json.
    """
    import json

    result = subprocess.run(
        ["dbt", "parse", "--quiet"],
        cwd=str(DBT_PROJECT_DIR),
        env=dbt_project_env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, (
        f"dbt parse failed (this breaks every downstream tool that reads these "
        f"artifacts):\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )

    target = DBT_PROJECT_DIR / "target"
    with open(target / "manifest.json", encoding="utf-8") as f:
        manifest = json.load(f)
    with open(target / "semantic_manifest.json", encoding="utf-8") as f:
        semantic_manifest = json.load(f)

    return {"manifest": manifest, "semantic_manifest": semantic_manifest}


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                return
        time.sleep(0.3)
    raise TimeoutError(f"Nothing listening on port {port} after {timeout}s")


@contextmanager
def run_streamlit_server(chat_api_base_url: str):
    """
    Boots a real Streamlit server for streamlit_dashboard.py using the same
    command docker-compose.yml's `streamlit` service runs, pointed at
    `chat_api_base_url` instead of the real chat backend. Yields the
    server's base URL; terminates the subprocess on exit.
    """
    port = free_port()
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/chat_agent/streamlit_dashboard.py",
            f"--server.port={port}",
            "--server.address=127.0.0.1",
            "--server.headless=true",
            "--browser.gatherUsageStats=false",
        ],
        cwd=str(PROJECT_ROOT),
        env={**os.environ, "CHAT_API_BASE_URL": chat_api_base_url},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_port(port)
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=5)


@contextmanager
def run_stub_chat_backend(dashboards_by_message_id: dict):
    """
    A minimal stdlib HTTP server standing in for the FastAPI chat backend —
    only implements the one endpoint streamlit_dashboard.py actually calls
    (GET /api/messages/{id}/dashboard), serving `dashboards_by_message_id`
    and 404 for any id not in it. Yields the server's base URL.
    """
    import json
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from threading import Thread

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            prefix, suffix = "/api/messages/", "/dashboard"
            if self.path.startswith(prefix) and self.path.endswith(suffix):
                message_id = self.path[len(prefix) : -len(suffix)]
                dashboard = dashboards_by_message_id.get(message_id)
                if dashboard is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.end_headers()
                    self.wfile.write(json.dumps(dashboard).encode())
                    return
            self.send_response(404)
            self.end_headers()

        def log_message(self, *args):
            pass  # keep test output quiet

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)
