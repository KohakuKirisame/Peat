"""Fetch public article pages and extract their readable body, without browser credentials."""

import asyncio
import base64
import ipaddress
import json
import re
import socket
from urllib.parse import urljoin, urlparse

import httpx
import trafilatura

from .brokers import ProviderError

MAX_DOWNLOAD = 4_000_000
MAX_ARTICLE = 60_000


async def public_address(url: str) -> str:
    try:
        parsed = urlparse(url)
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or port not in {80, 443}
            or "\\" in url
            or len(url) > 4000
        ):
            raise ValueError
        addresses = await asyncio.to_thread(
            socket.getaddrinfo, parsed.hostname, port, type=socket.SOCK_STREAM
        )
    except (ValueError, OSError):
        raise ProviderError("article_url_unavailable") from None
    if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
        raise ProviderError("article_url_blocked")
    addresses.sort(key=lambda item: item[0] != socket.AF_INET)
    return addresses[0][4][0]


class ArticleReader:
    async def download(self, url: str, *, form: dict | None = None) -> tuple[bytes, str]:
        # Each redirect is validated and pinned independently to prevent DNS rebinding.
        async with httpx.AsyncClient(timeout=15, trust_env=False, follow_redirects=False) as client:
            current = url
            for _ in range(6):
                address = await public_address(current)
                original = httpx.URL(current)
                target = original.copy_with(host=address)
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; Peat/0.1; article reader)",
                    "Host": original.netloc.decode(),
                    "Cookie": "",
                    "Accept": "text/html,application/json",
                }
                async with client.stream(
                    "POST" if form else "GET",
                    target,
                    headers=headers,
                    data=form,
                    extensions={"sni_hostname": original.host},
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            break
                        current = urljoin(current, location)
                        form = None
                        continue
                    if response.status_code != 200:
                        raise ProviderError("article_source_unavailable")
                    content_type = response.headers.get("content-type", "text/html").lower()
                    if not any(
                        kind in content_type for kind in ("text/", "application/json", "application/xhtml")
                    ):
                        raise ProviderError("article_source_unavailable")
                    content = bytearray()
                    async for chunk in response.aiter_bytes():
                        content.extend(chunk)
                        if len(content) > MAX_DOWNLOAD:
                            raise ProviderError("article_too_large")
                    return bytes(content), current
        raise ProviderError("article_redirect_limit")

    async def publisher_url(self, url: str) -> str:
        parsed = urlparse(url)
        if parsed.hostname != "news.google.com":
            return url
        token = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,3000}", token):
            raise ProviderError("article_link_unavailable")
        # Older Google RSS links embed the publisher address as a protobuf string.
        try:
            decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            embedded = re.search(rb"https?://[^\x00-\x20\x7f-\xff]+", decoded)
            if embedded:
                return embedded.group().decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            pass
        page, landed = await self.download(
            f"https://news.google.com/rss/articles/{token}?hl=en-US&gl=US&ceid=US:en"
        )
        if urlparse(landed).hostname != "news.google.com":
            return landed
        text = page.decode("utf-8", errors="replace")
        signature = re.search(r'data-n-a-sg=["\']([^"\']+)', text)
        timestamp = re.search(r'data-n-a-ts=["\']([0-9]+)', text)
        if not signature or not timestamp:
            raise ProviderError("article_link_unavailable")
        # Public Google News RPC envelope, documented by google-news-url-decoder:
        # https://github.com/SSujitX/google-news-url-decoder
        context = [
            ["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
            "X",
            "X",
            1,
            [1, 1, 1],
            1,
            1,
            None,
            0,
            0,
            None,
            0,
        ]
        request = ["garturlreq", context, token, int(timestamp.group(1)), signature.group(1)]
        rpc = [[["Fbv4je", json.dumps(request, separators=(",", ":")), None, "1"]]]
        raw, _ = await self.download(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            form={"f.req": json.dumps(rpc, separators=(",", ":"))},
        )
        # Responses may include an XSSI prefix and length-framed JSON chunks.
        for line in raw.decode("utf-8", errors="replace").splitlines():
            if not line.lstrip().startswith("["):
                continue
            try:
                rows = json.loads(line)
                for row in rows:
                    if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and row[1] == "Fbv4je":
                        payload = json.loads(row[2])
                        if payload[0] == "garturlres" and isinstance(payload[1], str):
                            return payload[1]
            except (ValueError, TypeError, IndexError):
                continue
        raise ProviderError("article_link_unavailable")

    async def read(self, url: str) -> dict:
        try:
            source = await self.publisher_url(url)
            page, source = await self.download(source)
            html = page.decode("utf-8", errors="replace")
            if re.search(r'"isAccessibleForFree"\s*:\s*(?:false|"false")', html, re.I):
                raise ProviderError("article_subscription_required")
            text = await asyncio.to_thread(
                trafilatura.extract,
                page,
                url=source,
                output_format="txt",
                include_comments=False,
                include_tables=False,
                favor_precision=True,
            )
        except (httpx.HTTPError, ValueError):
            raise ProviderError("article_source_unavailable") from None
        if not text or len(text.strip()) < 160:
            raise ProviderError("article_body_unavailable")
        if any(
            phrase in text.casefold()
            for phrase in (
                "verify you are human",
                "enable javascript and cookies",
                "subscribe to continue reading",
                "订阅后阅读全文",
            )
        ):
            raise ProviderError("article_body_unavailable")
        # Keep a clear distinction between the retrieved body and the RSS excerpt.
        return {
            "content": text.strip()[:MAX_ARTICLE],
            "source_url": source,
            "truncated": len(text.strip()) > MAX_ARTICLE,
        }
