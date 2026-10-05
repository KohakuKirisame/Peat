"""Activate a successfully installed, explicitly selected calendar dependency at restart."""

import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv


def activate():
    load_dotenv()
    runtime = Path(os.getenv("PEAT_DATA_DIR", "data")).resolve() / "runtime"
    marker = runtime / "calendar-active.json"
    if marker.is_file():
        path = Path(json.loads(marker.read_text())["path"]).resolve()
        if not path.is_relative_to(runtime.resolve()) or not (path / "exchange_calendars").is_dir():
            raise RuntimeError(
                "Invalid calendar runtime. Restore calendar-active.json or remove the override."
            )
        sys.path.insert(0, str(path))
