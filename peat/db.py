import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


DEFAULT_SETTINGS = {
    "theme": "dark",
    "accent": "#8a9aff",
    "language": "en",
    "style": "balanced",
    "news_limit": 500,
    "news_days": 30,
    "news_interval": 900,
    "portfolio_interval": 60,
    "ai_provider": "openai",
    "ai_model": "",
    "reasoning_effort": "auto",
    "news_language": "en",
    "ai_base_prompt": "",
    "ai_style_prompts": {},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
 id INTEGER PRIMARY KEY, username TEXT NOT NULL UNIQUE COLLATE NOCASE,
 password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','user')),
 active INTEGER NOT NULL DEFAULT 1, settings TEXT NOT NULL DEFAULT '{}', created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sessions (
 token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 expires_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS credentials (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, provider TEXT NOT NULL,
 encrypted TEXT NOT NULL, PRIMARY KEY(user_id,provider)
);
CREATE TABLE IF NOT EXISTS watchlist (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 symbol TEXT NOT NULL, name TEXT NOT NULL, sector TEXT NOT NULL DEFAULT '',
 UNIQUE(user_id,symbol)
);
CREATE TABLE IF NOT EXISTS cache (
 user_id INTEGER NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL, updated_at TEXT NOT NULL,
 PRIMARY KEY(user_id,kind)
);
CREATE TABLE IF NOT EXISTS snapshots (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 total_value REAL NOT NULL, total_cost REAL, currency TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS history (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE, kind TEXT NOT NULL,
 external_id TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(user_id,kind,external_id)
);
CREATE TABLE IF NOT EXISTS news (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, title TEXT NOT NULL, content TEXT NOT NULL, url TEXT NOT NULL,
 source TEXT NOT NULL, topic TEXT NOT NULL, published_at TEXT, fetched_at TEXT NOT NULL,
 UNIQUE(user_id,fingerprint)
);
CREATE INDEX IF NOT EXISTS news_user_date ON news(user_id,published_at DESC);
CREATE TABLE IF NOT EXISTS analyses (
 id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 provider TEXT NOT NULL, model TEXT NOT NULL, style TEXT NOT NULL, content TEXT NOT NULL,
 evidence TEXT NOT NULL, created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS statement_rows (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 fingerprint TEXT NOT NULL, payload TEXT NOT NULL, PRIMARY KEY(user_id,fingerprint)
);
CREATE TABLE IF NOT EXISTS symbol_mappings (
 user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
 ticker TEXT NOT NULL, symbol TEXT NOT NULL, PRIMARY KEY(user_id,ticker)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        with self.connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA)
            conn.execute("PRAGMA user_version=1")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.path, timeout=15)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def all(self, query: str, params=()) -> list[dict]:
        with self.connect() as conn:
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def one(self, query: str, params=()) -> dict | None:
        rows = self.all(query, params)
        return rows[0] if rows else None

    def execute(self, query: str, params=()):
        with self.connect() as conn:
            return conn.execute(query, params).lastrowid

    def settings(self, uid: int) -> dict:
        user = self.one("SELECT settings FROM users WHERE id=?", (uid,))
        return DEFAULT_SETTINGS | json.loads(user["settings"] if user else "{}")

    def cached(self, uid: int, kind: str) -> dict | None:
        row = self.one("SELECT * FROM cache WHERE user_id=? AND kind=?", (uid, kind))
        return {"data": json.loads(row["payload"]), "updated_at": row["updated_at"]} if row else None

    def put_cache(self, uid: int, kind: str, payload):
        self.execute(
            "INSERT INTO cache VALUES(?,?,?,?) ON CONFLICT(user_id,kind) DO UPDATE SET "
            "payload=excluded.payload,updated_at=excluded.updated_at",
            (uid, kind, json.dumps(payload), now()),
        )
