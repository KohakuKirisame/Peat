"""Fetch public article pages and extract their readable body, without browser credentials."""

import asyncio
import base64
import ipaddress
import json
import re
import socket
from urllib.parse import parse_qs, urlencode, urljoin, urlparse

import httpx

from .article_extract import inspect_page
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


class ArticleError(ProviderError):
    def __init__(self, code: str, source_url: str | None = None, retry_after: int | None = None):
        super().__init__(code, retry_after)
        self.source_url = source_url


class ArticleReader:
    async def download(self, url: str, *, form: dict | None = None) -> tuple[bytes, str]:
        last_error = None
        for attempt in range(3):
            try:
                return await self._download_once(url, form=form)
            except (httpx.TransportError, ArticleError) as exc:
                last_error = exc
                transient = isinstance(exc, httpx.TransportError) or exc.code in {
                    "article_rate_limited",
                    "article_source_temporary",
                }
                if not transient or attempt == 2:
                    raise
                if getattr(exc, "retry_after", None) and exc.retry_after > 3:
                    # Do not retry earlier than a publisher's longer requested backoff.
                    raise
                await asyncio.sleep(min(3, getattr(exc, "retry_after", None) or (0.5 * 2**attempt)))
        raise last_error

    async def _download_once(self, url: str, *, form: dict | None = None) -> tuple[bytes, str]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(20, connect=10), trust_env=False, follow_redirects=False
        ) as client:
            current = url
            visited = set()
            last_validated = None
            for _ in range(8):
                if current in visited:
                    raise ArticleError("article_redirect_limit", current)
                visited.add(current)
                address = await public_address(current)
                last_validated = current
                original = httpx.URL(current)
                target = original.copy_with(host=address)
                headers = {
                    "User-Agent": "Mozilla/5.0 (compatible; Peat/0.3; article reader)",
                    "Host": original.netloc.decode(),
                    "Cookie": "",
                    "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.5",
                    "Accept-Language": "en,zh;q=0.9",
                }
                try:
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
                            if response.status_code in {301, 302, 303}:
                                form = None
                            continue
                        status = response.status_code
                        if status in {408, 425, 429, 500, 502, 503, 504}:
                            hint = response.headers.get("retry-after", "")
                            raise ArticleError(
                                "article_rate_limited" if status == 429 else "article_source_temporary",
                                current,
                                min(3600, int(hint)) if hint.isdigit() else None,
                            )
                        if status in {401, 403, 451}:
                            raise ArticleError("article_access_restricted", current)
                        if status in {404, 410}:
                            raise ArticleError("article_not_found", current)
                        if status != 200:
                            raise ArticleError("article_source_unavailable", current)
                        content_type = response.headers.get("content-type", "text/html").lower()
                        if not any(
                            kind in content_type
                            for kind in ("text/", "application/json", "application/xhtml")
                        ):
                            raise ArticleError("article_source_unavailable", current)
                        content = bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content) > MAX_DOWNLOAD:
                                raise ArticleError("article_too_large", current)
                        return bytes(content), current
                except httpx.TransportError as exc:
                    # Preserve a validated publisher URL for the reader even when transport fails.
                    if not hasattr(exc, "article_url"):
                        exc.article_url = current
                    raise
        raise ArticleError("article_redirect_limit", last_validated)

    async def publisher_url(self, url: str, with_page=False):
        parsed = urlparse(url)
        if parsed.hostname != "news.google.com":
            return (url, None) if with_page else url
        token = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if not re.fullmatch(r"[A-Za-z0-9_-]{10,3000}", token):
            raise ProviderError("article_link_unavailable")
        # Decode the actual protobuf string length; regex matching can retain framing bytes.
        try:
            decoded = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4))
            if decoded.startswith(b"\x08\x13\x22"):
                index, length, shift = 3, 0, 0
                while index < len(decoded) and shift < 35:
                    byte = decoded[index]
                    index += 1
                    length |= (byte & 127) << shift
                    if not byte & 128:
                        break
                    shift += 7
                embedded = decoded[index : index + length].decode("utf-8")
                if len(decoded[index : index + length]) == length and embedded.startswith(
                    ("https://", "http://")
                ):
                    return (embedded, None) if with_page else embedded
        except (ValueError, UnicodeDecodeError):
            pass
        query = parse_qs(parsed.query)
        locale = {
            key: query.get(key, [value])[0]
            for key, value in {"hl": "en-US", "gl": "US", "ceid": "US:en"}.items()
        }
        page, landed = await self.download(
            f"https://news.google.com/rss/articles/{token}?" + urlencode(locale)
        )
        if urlparse(landed).hostname != "news.google.com":
            return (landed, page) if with_page else landed
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
        # Google may return length-framed, multi-line JSON rather than one JSON row per line.
        text = raw.decode("utf-8", errors="replace")
        decoder = json.JSONDecoder()
        offset = 0
        for _ in range(100):
            start = text.find("[", offset)
            if start < 0:
                break
            try:
                rows, used = decoder.raw_decode(text[start:])
                offset = start + used
                for row in rows:
                    if isinstance(row, list) and len(row) > 2 and row[0] == "wrb.fr" and row[1] == "Fbv4je":
                        payload = json.loads(row[2]) if isinstance(row[2], str) else row[2]
                        if (
                            isinstance(payload, list)
                            and len(payload) > 1
                            and payload[0] == "garturlres"
                            and isinstance(payload[1], str)
                        ):
                            return (payload[1], None) if with_page else payload[1]
            except (ValueError, TypeError, IndexError):
                offset = start + 1
        raise ProviderError("article_link_unavailable")

    async def read(self, url: str, expected_title: str | None = None) -> dict:
        last_source = None
        resolving = True
        try:
            source, page = await self.publisher_url(url, with_page=True)
            resolving = False
            if page is None:
                page, source = await self.download(source)
            last_source = source
            extracted = await asyncio.to_thread(inspect_page, page, source, expected_title)
            if not extracted["content"] and extracted["error"] not in {
                "article_subscription_required",
                "article_access_restricted",
            }:
                for alternate in extracted["alternatives"]:
                    try:
                        candidate, candidate_url = await self.download(alternate)
                        other = await asyncio.to_thread(
                            inspect_page, candidate, candidate_url, expected_title
                        )
                    except (httpx.HTTPError, ProviderError):
                        continue
                    if other["error"] == "article_subscription_required":
                        raise ArticleError("article_subscription_required", last_source)
                    if other["content"]:
                        extracted, source = other, candidate_url
                        break
            if not extracted["content"]:
                raise ArticleError(extracted["error"], last_source)
            text = extracted["content"]
            return {
                "content": text[:MAX_ARTICLE],
                "source_url": source,
                "truncated": len(text) > MAX_ARTICLE,
                "extraction_method": extracted.get("method"),
            }
        except ArticleError as exc:
            if resolving:
                # An internal resolver endpoint is never an original-article link.
                exc.source_url = url
            raise
        except httpx.HTTPError as exc:
            raise ArticleError(
                "article_source_temporary", url if resolving else getattr(exc, "article_url", last_source)
            ) from None
        except (ValueError, TypeError):
            raise ArticleError("article_body_unavailable", last_source) from None
