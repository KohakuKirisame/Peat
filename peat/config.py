import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


@dataclass
class Config:
    data_dir: Path = field(default_factory=lambda: Path(os.getenv("PEAT_DATA_DIR", "data")).resolve())
    secure_cookies: bool = field(default_factory=lambda: os.getenv("PEAT_SECURE_COOKIES", "false") == "true")
    registration_open: bool = field(
        default_factory=lambda: os.getenv("PEAT_REGISTRATION_OPEN", "true") == "true"
    )
    console_enabled: bool = field(default_factory=lambda: os.getenv("PEAT_CONSOLE_ENABLED", "true") == "true")
    background: bool = True
    origins: list[str] = field(
        default_factory=lambda: [
            s.strip()
            for s in os.getenv(
                "PEAT_ORIGINS",
                "http://localhost:8787,http://127.0.0.1:8787,http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if s.strip()
        ]
    )
    llm_allowed_hosts: set[str] = field(
        default_factory=lambda: set(filter(None, os.getenv("PEAT_LLM_ALLOWED_HOSTS", "").split(",")))
    )

    @property
    def database(self) -> Path:
        return self.data_dir / "peat.sqlite3"

    @property
    def runtime(self) -> Path:
        return self.data_dir / "runtime"
