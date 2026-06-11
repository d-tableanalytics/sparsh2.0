"""Phase 8 verification — conversation-quality fixes from the live-transcript review.

Covers the regressions found in real use:
  * P1 greeting replay — a bare greeting ('hi', '"Hi" / "Hello"', 'thanks') must
    pass through the rewriter untouched, so the model greets instead of the
    rewriter inventing a question from context (which replayed the last answer).
  * P2 context bleed — a self-contained global command ('show all batches',
    'list all companies') must NOT be rewritten with scope borrowed from the
    previous turn; only genuine references (it/that/this) get resolved.
  * P4 session-vs-task — list_sessions excludes personal to-do entries
    (type=="task") by default and reports how many it hid; include_tasks=true
    brings them back.

Run:  python -m app.assistant.tests.test_phase8_quality   (from backend/)
No live DB / OpenAI needed.
"""
from __future__ import annotations

import asyncio
import re

from bson import ObjectId

import app.assistant.tools.admin.calendar_tools as calendar_tools
from app.assistant.core import query_rewriter as qr
from app.assistant.schemas.context import UserContext


# ── Fake Mongo with $ne / $gte / $lte / $regex + count_documents ───────────────
def _match(query, doc):
    for k, v in query.items():
        field = doc.get(k)
        if isinstance(v, dict):
            if "$ne" in v and field == v["$ne"]:
                return False
            if "$gte" in v and not (field is not None and field >= v["$gte"]):
                return False
            if "$lte" in v and not (field is not None and field <= v["$lte"]):
                return False
            if "$regex" in v:
                flags = re.I if "i" in v.get("$options", "") else 0
                if field is None or not re.search(v["$regex"], str(field), flags):
                    return False
        elif field != v:
            return False
    return True


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    def sort(self, key, direction=1):
        self._docs.sort(key=lambda d: d.get(key) or "", reverse=(direction == -1))
        return self

    async def to_list(self, n):
        return list(self._docs[:n])


class FakeCollection:
    def __init__(self, docs=None):
        self.docs = docs or []

    def find(self, query=None, projection=None):
        return _Cursor([d for d in self.docs if _match(query or {}, d)])

    async def count_documents(self, query):
        return len([d for d in self.docs if _match(query or {}, d)])


class FakeLLM:
    """Records utility_complete calls so we can assert the rewriter LLM is only
    invoked for genuine follow-ups (never for greetings/global commands)."""

    def __init__(self, reply="REWRITTEN"):
        self.calls = 0
        self.reply = reply

    async def utility_complete(self, prompt, max_tokens=80, meter=None):
        self.calls += 1
        return self.reply


SA = UserContext(user_id="sa1", full_name="Dipti", role="superadmin")

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


B1 = ObjectId()
# A realistic mix: 2 real sessions + 3 to-do "task" entries in one collection.
EVENTS = [
    {"_id": ObjectId(), "title": "Kickoff Strategy", "start": "2026-06-09T10:00",
     "type": "session", "status": "scheduled", "session_type": "CEO Direct", "batch_id": str(B1)},
    {"_id": ObjectId(), "title": "Module Review", "start": "2026-06-10T15:00",
     "type": "session", "status": "completed", "session_type": "Module Review", "batch_id": str(B1)},
    {"_id": ObjectId(), "title": "Update CV Pool Sheet", "start": "2026-06-09T09:00",
     "type": "task", "status": "scheduled", "batch_id": str(B1)},
    {"_id": ObjectId(), "title": "Job post on LinkedIn", "start": "2026-06-10T09:00",
     "type": "task", "status": "scheduled", "batch_id": str(B1)},
    {"_id": ObjectId(), "title": "Call Arundhati reminder", "start": "2026-06-11T09:00",
     "type": "task", "status": "scheduled", "batch_id": str(B1)},
]


def _resolver():
    cols = {
        "STAFF_CALENDER": FakeCollection([]),
        "LEARNER_CALENDER": FakeCollection([]),
        "calendar_events": FakeCollection([dict(d) for d in EVENTS]),
    }
    return lambda name: cols.setdefault(name, FakeCollection())


async def main():
    print("\n=== Phase 8 — Conversation-quality fixes ===\n")

    # ── P1: greetings/gratitude are social → never rewritten ───────────────
    print("P1 greeting handling (is_social / no rewrite):")
    check("'hi' is social", qr.is_social("hi"))
    check("'Hello!' is social", qr.is_social("Hello!"))
    check('\'"Hi" / "Hello"\' is social (the exact bug input)', qr.is_social('"Hi" / "Hello"'))
    check("'thanks' is social", qr.is_social("thanks"))
    check("'ok cool' is social", qr.is_social("ok cool"))
    check("'hi, how do I create a batch?' is NOT social (mixed)",
          not qr.is_social("hi, how do I create a batch?"))

    # ── P2: global commands are self-contained → never rewritten ───────────
    print("\nP2 global commands (no context bleed):")
    check("'Show all batches' does not need rewrite", not qr._needs_rewrite("Show all batches"))
    check("'List all companies' does not need rewrite", not qr._needs_rewrite("List all companies"))
    check("'platform overview' does not need rewrite", not qr._needs_rewrite("platform overview"))
    check("'tell me about this batch' DOES need rewrite (follow-up)",
          qr._needs_rewrite("tell me about this batch"))
    check("'what about next week' DOES need rewrite (elliptical)",
          qr._needs_rewrite("what about next week"))

    # rewrite() must short-circuit (no LLM call) for social + global, even WITH
    # a previous-turn context that mentions a specific company.
    ctx_text = "assistant: Here is the overview of Sparsh Magic LLP ... average score 38.5"
    llm = FakeLLM()
    r_hi = await qr.rewrite(llm, '"Hi" / "Hello"', "", ctx_text)
    check("greeting passes through unchanged", r_hi["rewritten_query"] == '"Hi" / "Hello"'
          and r_hi["rewritten"] is False)
    r_all = await qr.rewrite(llm, "Show all batches", "", ctx_text)
    check("'show all batches' passes through unchanged (no company injected)",
          r_all["rewritten_query"] == "Show all batches" and r_all["rewritten"] is False)
    check("LLM rewriter NOT called for social/global", llm.calls == 0)

    # A genuine follow-up DOES invoke the rewriter.
    llm2 = FakeLLM(reply="Tell me about the SPARSH INTERNAL TRAINING batch")
    r_follow = await qr.rewrite(llm2, "tell me about this batch", "", ctx_text)
    check("follow-up is rewritten via LLM", r_follow["rewritten"] is True and llm2.calls == 1)

    # ── P4: list_sessions excludes tasks by default ────────────────────────
    print("\nP4 list_sessions excludes to-do tasks by default:")
    calendar_tools.get_collection = _resolver()

    r_def = await calendar_tools.list_sessions(SA)
    titles = {s["title"] for s in r_def.data["sessions"]}
    check("default returns ONLY real sessions",
          titles == {"Kickoff Strategy", "Module Review"})
    check("no task titles leak in",
          not ({"Update CV Pool Sheet", "Job post on LinkedIn"} & titles))
    check("reports how many tasks were hidden", r_def.data.get("tasks_excluded") == 3,
          str(r_def.data.get("tasks_excluded")))

    r_inc = await calendar_tools.list_sessions(SA, include_tasks=True)
    inc_titles = {s["title"] for s in r_inc.data["sessions"]}
    check("include_tasks=true brings tasks back", {"Update CV Pool Sheet"} <= inc_titles
          and len(r_inc.data["sessions"]) == 5)
    check("include_tasks=true reports no exclusions", "tasks_excluded" not in r_inc.data)

    # Filters still compose with the task exclusion.
    r_done = await calendar_tools.list_sessions(SA, status="completed")
    check("status filter + task exclusion",
          [s["title"] for s in r_done.data["sessions"]] == ["Module Review"])

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
