import hashlib
import ipaddress
import json
import os
import secrets
import socket
from datetime import datetime, timedelta, timezone
from urllib.parse import urlparse

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.fernet import Fernet
from fastapi import HTTPException

from .config import Config
from .db import Database

hasher = PasswordHasher()


def verify_password(encoded: str, password: str) -> bool:
    try:
        return hasher.verify(encoded, password)
    except (VerificationError, InvalidHashError):
        return False


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_session(db: Database, uid: int) -> str:
    token = secrets.token_urlsafe(48)
    expiry = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    db.execute("INSERT INTO sessions VALUES(?,?,?)", (digest(token), uid, expiry))
    db.execute("DELETE FROM sessions WHERE expires_at<?", (datetime.now(timezone.utc).isoformat(),))
    return token


class Vault:
    def __init__(self, config: Config, db: Database):
        self.db = db
        key = os.getenv("PEAT_ENCRYPTION_KEY")
        path = config.data_dir / "master.key"
        if not key:
            if not path.exists():
                if db.one("SELECT user_id FROM credentials LIMIT 1"):
                    raise RuntimeError("Encryption key is missing. Restore data/master.key from your backup.")
                key = Fernet.generate_key()
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "wb") as file:
                    file.write(key)
            key = path.read_bytes()
        self.cipher = Fernet(key.encode() if isinstance(key, str) else key)

    def get(self, uid: int, provider: str) -> dict:
        row = self.db.one("SELECT encrypted FROM credentials WHERE user_id=? AND provider=?", (uid, provider))
        return json.loads(self.cipher.decrypt(row["encrypted"].encode())) if row else {}

    def set(self, uid: int, provider: str, value: dict):
        encrypted = self.cipher.encrypt(json.dumps(value).encode()).decode()
        self.db.execute(
            "INSERT INTO credentials VALUES(?,?,?) ON CONFLICT(user_id,provider) DO UPDATE SET "
            "encrypted=excluded.encrypted",
            (uid, provider, encrypted),
        )

    def redact(self, uid: int, text: str) -> str:
        for provider in ("trading212", "openai"):
            for name, value in self.get(uid, provider).items():
                if name in {"api_key", "api_secret"} and value:
                    text = text.replace(value, "[redacted]")
        return text


def validate_llm_url(url: str, config: Config):
    parsed = urlparse(url)
    if parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username or parsed.password:
        raise HTTPException(422, "invalid_api_url")
    try:
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        raise HTTPException(422, "invalid_api_url") from None
    if parsed.query or parsed.fragment or "\\" in url:
        raise HTTPException(422, "invalid_api_url")
    if parsed.hostname in config.llm_allowed_hosts:
        return
    if parsed.scheme != "https":
        raise HTTPException(422, "https_required")
    try:
        addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    except OSError:
        raise HTTPException(422, "api_host_unresolved") from None
    if not addresses or any(not ipaddress.ip_address(address[4][0]).is_global for address in addresses):
        raise HTTPException(422, "private_api_host_not_allowed")
    # Pin a checked address for the HTTP connection; do not resolve the hostname again at connect time.
    addresses.sort(key=lambda item: item[0] != socket.AF_INET)
    return addresses[0][4][0]
