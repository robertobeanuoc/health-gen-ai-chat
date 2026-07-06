from functools import lru_cache
from pathlib import Path

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"


@lru_cache(maxsize=1)
def _base_system_prompt() -> str:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["system_prompt"]


def get_system_prompt(timezone: str | None = None) -> str:
    """
    Returns the system prompt, appending the user's timezone (if known) so the
    model can pass it to `execute_read_query` and convert UTC-stored datetime
    columns to local time in SQL rather than in its own reasoning.
    """
    base = _base_system_prompt()
    if not timezone:
        return base
    return base + f"\n\nUser timezone: {timezone}\n"
