import json

import httpx
import pytest
from fastapi.testclient import TestClient

from peat.app import create_app
from peat.article_extract import inspect_page
from peat.articles import ArticleError, ArticleReader
from peat.config import Config
from peat.db import now

BODY = (
    "This synthetic company article contains operating details, quarterly results and product demand. "
    "It explains a published manufacturing plan and the figures relevant to its investors.\n\n"
    "A second paragraph describes the industry's changes and gives readers context for the company update. "
    "These sentences are test data used to validate extraction, with no real portfolio or recommendation."
)


def test_main_article_jsonld_is_used_without_false_paywall_from_recommendations(monkeypatch):
    monkeypatch.setattr("peat.article_extract.trafilatura.extract", lambda *args, **kwargs: None)
    metadata = {
        "@graph": [
            {
                "@type": "NewsArticle",
                "url": "https://publisher.example/story",
                "headline": "Fixture results",
                "isAccessibleForFree": True,
                "articleBody": BODY,
            },
            {
                "@type": "NewsArticle",
                "url": "https://publisher.example/premium-other",
                "isAccessibleForFree": False,
            },
        ]
    }
    page = f'<html><title>Fixture results</title><script type="application/ld+json">{json.dumps(metadata)}</script></html>'.encode()
    result = inspect_page(page, "https://publisher.example/story", "Fixture results")
    assert result["content"] == BODY and result["method"] == "structured_article"


def test_main_article_subscription_marker_is_respected():
    metadata = {
        "@type": "NewsArticle",
        "url": "https://publisher.example/story",
        "isAccessibleForFree": False,
        "articleBody": BODY,
    }
    result = inspect_page(
        f'<script type="application/ld+json">{json.dumps(metadata)}</script><article><p>{BODY}</p></article>'.encode(),
        "https://publisher.example/story",
    )
    assert result["error"] == "article_subscription_required" and not result["content"]


@pytest.mark.asyncio
async def test_declared_amp_fallback_keeps_valid_publisher_body(monkeypatch):
    reader = ArticleReader()
    calls = []

    async def download(url, *, form=None):
        calls.append(url)
        if url.endswith("/amp"):
            return f"<article><h1>Fixture results</h1><p>{BODY}</p></article>".encode(), url
        return (
            b'<html><head><link rel="amphtml" href="/story/amp"></head><body>Enable JavaScript to continue</body></html>',
            url,
        )

    monkeypatch.setattr(reader, "download", download)
    result = await reader.read("https://publisher.example/story", expected_title="Fixture results")
    assert "quarterly results" in result["content"]
    assert result["source_url"].endswith("/amp") and len(calls) == 2


@pytest.mark.asyncio
async def test_transient_fetch_retries_but_access_restrictions_do_not(monkeypatch):
    reader = ArticleReader()
    attempts = []
    waits = []

    async def delay(seconds):
        waits.append(seconds)

    async def download(url, *, form=None):
        attempts.append(url)
        if len(attempts) == 1:
            raise httpx.ConnectError("fixture network error")
        if len(attempts) == 2:
            raise ArticleError("article_source_temporary", url)
        return BODY.encode(), url

    monkeypatch.setattr(reader, "_download_once", download)
    monkeypatch.setattr("peat.articles.asyncio.sleep", delay)
    assert (await reader.download("https://publisher.example/story"))[0] == BODY.encode()
    assert len(attempts) == 3 and waits == [0.5, 1.0]

    async def blocked(url, *, form=None):
        attempts.append(url)
        raise ArticleError("article_access_restricted", url)

    monkeypatch.setattr(reader, "_download_once", blocked)
    with pytest.raises(ArticleError):
        await reader.download("https://publisher.example/story")
    assert len(attempts) == 4


@pytest.mark.asyncio
async def test_google_multiline_framed_rpc_response(monkeypatch):
    reader = ArticleReader()

    async def download(url, *, form=None):
        if form:
            rows = [["wrb.fr", "Fbv4je", json.dumps(["garturlres", "https://publisher.example/article"])]]
            return (")]}'\n\n102\n" + json.dumps(rows, indent=2)).encode(), url
        return b'<div data-n-a-sg="fixture" data-n-a-ts="1234"></div>', url

    monkeypatch.setattr(reader, "download", download)
    assert (
        await reader.publisher_url("https://news.google.com/rss/articles/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA")
        == "https://publisher.example/article"
    )


@pytest.mark.asyncio
async def test_resolver_failure_keeps_article_link_not_rpc_endpoint(monkeypatch):
    reader = ArticleReader()
    original = "https://news.google.com/rss/articles/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"

    async def download(url, *, form=None):
        if form:
            raise ArticleError("article_rate_limited", url)
        return b'<div data-n-a-sg="fixture" data-n-a-ts="1234"></div>', url

    monkeypatch.setattr(reader, "download", download)
    with pytest.raises(ArticleError) as raised:
        await reader.read(original)
    assert raised.value.source_url == original


@pytest.mark.asyncio
async def test_google_redirect_reuses_the_already_downloaded_publisher_page(monkeypatch):
    reader = ArticleReader()
    calls = []

    async def download(url, *, form=None):
        calls.append(url)
        return f"<article><p>{BODY}</p></article>".encode(), "https://publisher.example/story"

    monkeypatch.setattr(reader, "download", download)
    assert (await reader.read("https://news.google.com/rss/articles/AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"))[
        "source_url"
    ] == "https://publisher.example/story"
    assert len(calls) == 1


def test_failed_body_can_be_retried_and_preserves_resolved_source(tmp_path, monkeypatch):
    app = create_app(Config(data_dir=tmp_path, background=False))
    calls = []

    async def read(url, expected_title=None):
        calls.append(url)
        if len(calls) == 1:
            raise ArticleError("article_source_temporary", "https://publisher.example/resolved")
        return {"content": BODY, "source_url": url, "truncated": False}

    monkeypatch.setattr(app.state.news.reader, "read", read)
    with TestClient(app, base_url="http://localhost", headers={"X-Peat-Request": "1"}) as client:
        client.post(
            "/api/auth/register", json={"username": "retry-owner", "password": "fixture-password-123"}
        )
        article = app.state.db.execute(
            "INSERT INTO news(user_id,fingerprint,title,content,url,source,topic,fetched_at) VALUES(1,'fixture','Fixture','Excerpt','https://news.google.com/articles/fixture','Press','Technology',?)",
            (now(),),
        )
        failed = client.post(f"/api/news/{article}/fulltext").json()
        assert (
            failed["status"] == "unavailable" and failed["source_url"] == "https://publisher.example/resolved"
        )
        client.post(f"/api/news/{article}/fulltext")
        assert len(calls) == 1
        ready = client.post(f"/api/news/{article}/fulltext?refresh=true").json()
        assert ready["status"] == "ready" and ready["content"] == BODY
        assert calls[-1] == "https://publisher.example/resolved"
