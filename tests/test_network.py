import socket

import httpx
import pytest

from peat.ai import Intelligence
from peat.config import Config
from peat.security import validate_llm_url


@pytest.mark.asyncio
async def test_llm_connection_pins_validated_address_and_preserves_tls_hostname(tmp_path, monkeypatch):
    config = Config(data_dir=tmp_path)
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 443))],
    )
    address = validate_llm_url("https://model.example/v1", config)
    captured = []
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda request: (
                captured.append(request) or httpx.Response(401, json={"error": "no fixture credential"})
            )
        )
    ) as client:
        service = Intelligence(None, None, client, None, config)
        await service.request(
            {"base_url": "https://model.example/v1", "connect_ip": address}, "GET", "/models"
        )
    assert captured[0].url.host == "93.184.216.34"
    assert captured[0].headers["host"] == "model.example"
    assert captured[0].extensions["sni_hostname"] == "model.example"
