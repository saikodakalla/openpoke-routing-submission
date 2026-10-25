"""Resolve 'usual' purchases using actual completed receipts, never guessed brands."""

import json
import re
from . import activity
from .conversation import normalized


def resolve_purchase(store, request):
    text = normalized(request.text)
    if not re.search(r"\b(order|reorder|buy)\b", text):
        return None
    categories = store.rows("SELECT DISTINCT category FROM merchants")
    category = next((r["category"] for r in categories if normalized(r["category"]) in text.split()), None)
    if not category:
        return None
    with activity.step("lookup", "Checking past orders", "SQLite · completed purchases grouped by merchant"):
        merchants = store.rows(
            "SELECT m.*,count(o.id) frequency FROM merchants m LEFT JOIN orders o "
            "ON o.merchant_id=m.id AND o.status='completed' WHERE m.category=? "
            "GROUP BY m.id ORDER BY frequency DESC,m.id",
            (category,),
        )
        named = [
            m
            for m in merchants
            if any(
                " " + normalized(alias) + " " in " " + text + " "
                for alias in [m["name"], *json.loads(m["aliases"])]
            )
        ]
        # A clarification-selected task is still checked against recorded merchant ownership.
        selected = [m for m in merchants if m["task_id"] == request.task_id] if request.task_id else named
        if len(selected) == 1:
            request.task_id = selected[0]["task_id"]
            request.purchase = True
            return {"selected": selected[0], "counts": merchants}
        if not any(w in text.split() for w in ("usual", "regular", "favorite", "favourite", "usuals")):
            return None
        maximum = merchants[0]["frequency"] if merchants else 0
        tied = [m for m in merchants if m["frequency"] == maximum and maximum > 0]
        if len(tied) == 1:
            request.task_id, request.purchase = tied[0]["task_id"], True
            return {"selected": tied[0], "counts": merchants}
        if len(tied) > 1:
            choices = [{"label": m["name"], "task_id": m["task_id"]} for m in tied]
            description = " and ".join(f"{m['name']} ({m['frequency']} completed orders)" for m in tied)
            return {
                "response": f"I see you have ordered from {description} equally often. Which place did you mean?",
                "clarification": {"kind": "merchant", "options": choices},
                "counts": merchants,
            }
        return {
            "response": "I don't have any completed orders for that yet. Which place would you like?",
            "clarification": {"kind": "merchant", "options": []},
            "counts": merchants,
        }
