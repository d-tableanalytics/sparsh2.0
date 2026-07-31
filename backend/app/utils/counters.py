"""Atomic per-year sequence numbers for human-readable business ids.

Employee codes, requisition numbers and candidate ids are shown to people and printed on
documents, so they must be sequential AND never collide. Computing them with a `count()` + 1
races: two concurrent creates both read N and both write N+1.

`find_one_and_update` with `$inc` is a single atomic server-side operation, so every caller
gets a distinct number even under concurrency. One document per (scope, year).

Nothing here ever deletes or overwrites — `$inc` with `upsert=True` only creates the counter
document on first use and increments it thereafter.
"""
from datetime import datetime, timezone
from typing import Optional

from pymongo import ReturnDocument

from app.db.mongodb import get_collection

COL_COUNTERS = "counters"


async def next_sequence(scope: str, year: Optional[int] = None) -> int:
    """Reserve and return the next number for (scope, year). Starts at 1."""
    yr = year if year is not None else datetime.now(timezone.utc).year
    doc = await get_collection(COL_COUNTERS).find_one_and_update(
        {"scope": scope, "year": yr},
        {"$inc": {"seq": 1}},
        upsert=True,
        return_document=ReturnDocument.AFTER,
    )
    return int(doc["seq"])


async def next_code(scope: str, prefix: str, width: int = 4, year: Optional[int] = None) -> str:
    """Formatted id, e.g. next_code(SEQ_EMPLOYEE, "EMP") -> "EMP-2026-0001"."""
    yr = year if year is not None else datetime.now(timezone.utc).year
    seq = await next_sequence(scope, yr)
    return f"{prefix}-{yr}-{str(seq).zfill(width)}"
