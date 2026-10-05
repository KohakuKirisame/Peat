"""Securities-only context for research; account cash/deposits stay in the account UI."""

from copy import deepcopy


def investment_context(cached: dict | None):
    if not cached:
        return None
    original = cached["data"]
    fields = {
        "provider",
        "environment",
        "currency",
        "invested",
        "market_value",
        "realized",
        "unrealized",
        "positions",
        "ungrouped_positions",
        "pie_status",
        "source",
        "as_of",
    }
    data = {key: deepcopy(value) for key, value in original.items() if key in fields}
    total = data.get("market_value")
    if total is None:
        total = sum(max(0, position.get("value") or 0) for position in data.get("positions", []))
        data["market_value"] = total
    data["allocation_basis"] = "securities_market_value"
    for position in data.get("positions", []):
        position["weight_pct"] = (
            position["value"] / total * 100 if total and position.get("value") is not None else None
        )
    data["pies"] = [
        {key: deepcopy(value) for key, value in pie.items() if key != "cash"}
        for pie in original.get("pies", [])
        if pie.get("positions")
    ]
    return {"data": data, "updated_at": cached["updated_at"]}
