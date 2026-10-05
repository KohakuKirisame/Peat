"""Disposable browser-test server. Never uses the production data directory."""

import sys
import tempfile
from pathlib import Path

import uvicorn

if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from peat.app import create_app
    from peat.config import Config

    with tempfile.TemporaryDirectory(prefix="peat-e2e-") as path:
        uvicorn.run(
            create_app(Config(data_dir=Path(path), background=False)),
            host="127.0.0.1",
            port=8788,
            access_log=False,
        )
