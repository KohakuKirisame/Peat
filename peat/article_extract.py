"""Pure article extraction helpers: main article metadata, readable text and declared alternatives."""

import json
import re
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlparse

import trafilatura
from lxml import etree, html

from .temporal import timestamp


def normalized_url(value):
    parsed = urlparse(value)
    return parsed.netloc.lower().removeprefix("www."), parsed.path.rstrip("/")


def text_only(value):
    value = re.sub(r"</(?:p|div|h[1-6])\s*>|<br\s*/?>", "\n\n", value, flags=re.I)
    try:
        node = html.fragment_fromstring(value, create_parent="div")
        for child in node.xpath(".//script|.//style|.//nav|.//aside|.//footer|.//form"):
            child.drop_tree()
        value = node.text_content()
    except (ValueError, etree.ParserError):
        pass
    return re.sub(r"[ \t]+", " ", re.sub(r"\n[ \t]*\n(?:[ \t]*\n)+", "\n\n", value)).strip()


def valid_body(text):
    if not text:
        return False
    cjk = len(re.findall(r"[\u3400-\u9fff]", text))
    return len(text.strip()) >= (80 if cjk > len(text) / 4 else 160)


def access_problem(text):
    sample = (text or "").casefold()
    if len(sample) < 1800 and any(
        term in sample
        for term in (
            "verify you are human",
            "checking your browser",
            "access denied",
            "request blocked",
            "captcha",
        )
    ):
        return "article_access_restricted"
    if len(sample) < 1800 and any(
        term in sample[:900]
        for term in (
            "subscribe to continue reading",
            "subscribe to read the full",
            "订阅后阅读全文",
            "会员专享",
        )
    ):
        return "article_subscription_required"
    if len(sample) < 1000 and any(term in sample for term in ("enable javascript", "javascript is required")):
        return "article_dynamic_page"
    return None


def inspect_page(page: bytes, source: str, expected_title: str | None = None):
    try:
        tree = html.fromstring(page, parser=html.HTMLParser(no_network=True, recover=True))
    except (ValueError, etree.ParserError):
        return {"content": None, "error": "article_body_unavailable", "alternatives": []}
    page_title = " ".join(tree.xpath("//h1[1]//text()") or tree.xpath("//title/text()"))
    title = (expected_title or page_title).casefold().strip()
    alternatives = []
    canonical = tree.xpath('//link[contains(concat(" ", normalize-space(@rel), " "), " canonical ")]/@href')
    amp = tree.xpath('//link[contains(concat(" ", normalize-space(@rel), " "), " amphtml ")]/@href')
    for href in [*amp, *canonical]:
        target = urljoin(source, href)
        if (
            target != source
            and urlparse(target).scheme in {"http", "https"}
            and urlparse(target).path not in {"", "/"}
        ):
            if target not in alternatives:
                alternatives.append(target)
    main_urls = {normalized_url(source), *(normalized_url(urljoin(source, link)) for link in canonical)}
    candidates = []

    def visit(value, depth=0):
        if depth > 7 or len(candidates) >= 100:
            return
        if isinstance(value, list):
            for child in value[:100]:
                visit(child, depth + 1)
        elif isinstance(value, dict):
            kinds = value.get("@type", [])
            if isinstance(kinds, str):
                kinds = [kinds]
            if isinstance(kinds, list) and any(
                isinstance(kind, str)
                and (kind.endswith("Article") or kind in {"BlogPosting", "LiveBlogPosting"})
                for kind in kinds
            ):
                addresses = [value.get("url"), value.get("mainEntityOfPage"), value.get("@id")]
                urls = [item.get("@id") if isinstance(item, dict) else item for item in addresses]
                urls = [normalized_url(urljoin(source, item)) for item in urls if isinstance(item, str)]
                similarity = (
                    SequenceMatcher(None, title, str(value.get("headline", "")).casefold()).ratio()
                    if title
                    else 0
                )
                score = (
                    100 if any(url in main_urls for url in urls) else -80 if urls else 5
                ) + similarity * 50
                candidates.append((score, value))
            # Do not treat recommendation lists as the main page's access declaration.
            for key in ("@graph", "mainEntity"):
                if key in value:
                    visit(value[key], depth + 1)

    for raw in tree.xpath('//script[contains(@type,"ld+json")]/text()')[:40]:
        try:
            visit(json.loads(raw))
        except (ValueError, TypeError, RecursionError):
            continue
    chosen = max(candidates, key=lambda item: item[0]) if candidates else None
    article = chosen[1] if chosen and chosen[0] >= 0 else {}
    dates = {}
    for field, key, meta_key in (
        ("published_at", "datePublished", "article:published_time"),
        ("modified_at", "dateModified", "article:modified_time"),
    ):
        alternatives_date = tree.xpath(f'//meta[@property="{meta_key}"]/@content')
        value = article.get(key) or (alternatives_date[0] if alternatives_date else None)
        dates[field] = value if isinstance(value, str) and len(value) <= 64 and timestamp(value) else None
    if (
        article.get("isAccessibleForFree") is False
        or str(article.get("isAccessibleForFree", "")).lower() == "false"
    ):
        return {"content": None, "error": "article_subscription_required", "alternatives": []}
    bodies = []
    structured = article.get("articleBody")
    if isinstance(structured, list):
        structured = "\n\n".join(item for item in structured if isinstance(item, str))
    if isinstance(structured, str):
        candidate = text_only(structured)
        if valid_body(candidate) and not access_problem(candidate):
            bodies.append((candidate, "structured_article"))
    # Standard mode enables Readability/jusText and baseline fallbacks skipped by precision mode.
    extracted = trafilatura.extract(
        page, url=source, output_format="txt", include_comments=False, include_tables=True
    )
    if valid_body(extracted) and not access_problem(extracted):
        bodies.append((extracted.strip(), "readable_article"))
    if not bodies:
        extracted = trafilatura.extract(
            page,
            url=source,
            output_format="txt",
            include_comments=False,
            include_tables=True,
            favor_recall=True,
        )
        if valid_body(extracted) and not access_problem(extracted):
            bodies.append((extracted.strip(), "recall_article"))
    if not bodies:
        for node in tree.xpath('//article|//*[@itemprop="articleBody"]')[:5]:
            paragraphs = [
                " ".join(p.itertext()).strip()
                for p in node.xpath(
                    './/p[not(ancestor::aside or ancestor::nav or ancestor::footer or ancestor::*[@hidden] or ancestor::*[@aria-hidden="true"])]'
                )
            ]
            candidate = "\n\n".join(p for p in paragraphs if p)
            if valid_body(candidate) and not access_problem(candidate):
                bodies.append((candidate, "article_paragraphs"))
    if bodies:
        # An explicit articleBody is less likely to include navigation; prefer it when substantial.
        structured = next((item for item in bodies if item[1] == "structured_article"), None)
        longest = max(bodies, key=lambda item: len(item[0]))
        content, method = (
            structured if structured and len(structured[0]) >= len(longest[0]) * 0.6 else longest
        )
        return {
            "content": content,
            "method": method,
            "error": None,
            "alternatives": alternatives[:2],
            **dates,
        }
    visible = " ".join(tree.xpath("//body//text()[not(ancestor::script or ancestor::style)]"))
    return {
        "content": None,
        "error": access_problem(extracted or visible) or "article_body_unavailable",
        "alternatives": alternatives[:2],
    }
