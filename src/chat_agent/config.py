from datetime import date, datetime
from functools import lru_cache
from pathlib import Path
from zoneinfo import ZoneInfo

import yaml

_CONFIG_PATH = Path(__file__).parent / "config.yaml"
_LOCAL_TZ = ZoneInfo("Europe/Madrid")


@lru_cache(maxsize=1)
def _load_system_prompt_template() -> str:
    with open(_CONFIG_PATH, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["system_prompt"]


def get_system_prompt(today: date | None = None) -> str:
    """Build the system prompt with today's real date prepended.

    The model's own sense of "today" defaults to its training cutoff, so
    bare dates in user queries (e.g. "July 15") get resolved against the
    wrong year unless we tell it explicitly. `today` defaults to the
    server's local date but is overridable for testing.
    """
    if today is None:
        today = datetime.now(_LOCAL_TZ).date()
    date_header = f"Today's date is {today.isoformat()} ({today.strftime('%A')}).\n\n"
    return date_header + _load_system_prompt_template()
