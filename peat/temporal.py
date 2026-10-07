"""Publication timestamps and observed price windows, without inferring causality."""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or timezone.utc)
    except ValueError:
        return None


def news_timing(article, horizon="medium_long", at=None):
    current = at or datetime.now(timezone.utc)
    value = article.get("source_published_at") or article.get("published_at")
    published = timestamp(value)
    precise = bool(value and "T" in value and (value.endswith("Z") or "+" in value[10:] or "-" in value[10:]))
    age = (current - published).total_seconds() / 3600 if published else None
    threshold = {"ultra_short": 72, "short": 336, "medium_long": 2160}.get(horizon, 2160)
    return {
        "effective_published_at": value,
        "publication_precision": "time" if precise else "date" if published else "unknown",
        "age_hours": round(age, 2) if age is not None else None,
        "timing_class": "undated"
        if age is None
        else "future_unverified"
        if age < -0.1
        else "recent"
        if age <= threshold
        else "background",
        "event_time": None,
        "event_time_status": "verify_in_source",
    }


def price_alignment(article, intraday, daily):
    published = timestamp(article.get("effective_published_at"))
    if not published or article.get("timing_class") == "future_unverified":
        return {"status": "publication_time_unverified"}
    epoch = published.timestamp()

    def point(bar, interval):
        return {
            "time": datetime.fromtimestamp(bar["end_time"], timezone.utc).isoformat()
            if bar.get("end_time")
            else None,
            "time_precision": "bar_close" if bar.get("end_time") else "session_date",
            "session_date": bar.get("session_date"),
            "price": bar["close"],
            "interval": interval,
            "session": bar.get("session", "unknown"),
        }

    def change(before, after):
        return (
            round((after["price"] / before["price"] - 1) * 100, 4)
            if before and after and before["price"]
            else None
        )

    bars = (intraday or {}).get("candles", [])
    complete = [bar for bar in bars if bar.get("complete") and bar.get("end_time")]
    if (
        article.get("publication_precision") == "time"
        and complete
        and complete[0]["time"] <= epoch <= complete[-1]["end_time"]
    ):
        before = next((bar for bar in reversed(complete) if bar["end_time"] <= epoch), None)
        after = next((bar for bar in complete if bar["time"] >= epoch), None)
        later = next((bar for bar in complete if bar["time"] >= epoch + 3600), None)
        a, b, c = [point(bar, intraday["interval"]) if bar else None for bar in (before, after, later)]
        return {
            "status": "matched",
            "basis": "publication_time",
            "before": a,
            "first_after": b,
            "one_hour_after": c,
            "first_change_pct": change(a, b),
            "one_hour_change_pct": change(a, c),
            "interpretation": "observed_movement_not_causal_attribution",
        }
    bars = [bar for bar in (daily or {}).get("candles", []) if bar.get("complete")]
    if not bars:
        return {"status": "price_history_unavailable"}
    try:
        zone = ZoneInfo(daily.get("timezone") or "UTC")
    except ZoneInfoNotFoundError:
        zone = timezone.utc
    day = (
        published.astimezone(zone).date().isoformat()
        if article.get("publication_precision") == "time"
        else published.date().isoformat()
    )
    if day < bars[0]["session_date"] or day > bars[-1]["session_date"]:
        return {
            "status": "outside_price_window",
            "coverage_start": bars[0]["session_date"],
            "coverage_end": bars[-1]["session_date"],
        }
    before = next((bar for bar in reversed(bars) if bar["session_date"] < day), None)
    event_day = next((bar for bar in bars if bar["session_date"] == day), None)
    after = next((bar for bar in bars if bar["session_date"] > day), None)
    a, b = [point(bar, "1d") if bar else None for bar in (before, after)]
    return {
        "status": "matched",
        "basis": "publication_date",
        "before": a,
        "next_session": b,
        "publication_day": point(event_day, "1d") if event_day else None,
        "change_pct": change(a, b),
        "interpretation": "daily_session_context_intraday_order_unknown",
    }
