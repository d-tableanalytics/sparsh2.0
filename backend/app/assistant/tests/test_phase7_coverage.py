"""Phase 7 verification — full section coverage + org-wide Calendar tool.

Covers the gaps closed in this change set:
  * list_sessions — NEW superadmin-only org-wide Calendar tool (RBAC gating,
    org-wide reads, date/batch/status/type filters, no PII).
  * Section coverage — every one of the 8 product sections (Dashboard, Companies,
    Batches, Session Templates, User Management, Calendar, Support Engine, Media
    Library) maps to at least one tool the superadmin can call.
  * Role boundary — admins/learners still cannot reach the SA-only org tools
    (the policy is: org-wide data is superadmin-only; no role mixing).
  * Whisper transcription routing — Whisper is preferred and the offline Google
    recognizer is the fallback.
  * Superadmin system prompt advertises list_sessions.

Run:  python -m app.assistant.tests.test_phase7_coverage   (from backend/)
No live DB / OpenAI / S3 needed.
"""
from __future__ import annotations

import asyncio
import re

from bson import ObjectId

import app.assistant.tools.admin.calendar_tools as calendar_tools
import app.services.transcription_service as ts
from app.assistant.core.prompt_builder import build_system_prompt
from app.assistant.schemas.context import UserContext
from app.assistant.tools import registry


# ── Minimal fake Mongo supporting $gte/$lte/$regex (date range + type filters) ──
def _match(query, doc):
    for k, v in query.items():
        field = doc.get(k)
        if isinstance(v, dict):
            if "$gte" in v and not (field is not None and field >= v["$gte"]):
                return False
            if "$lte" in v and not (field is not None and field <= v["$lte"]):
                return False
            if "$regex" in v:
                flags = re.I if "i" in v.get("$options", "") else 0
                if field is None or not re.search(v["$regex"], str(field), flags):
                    return False
            if "$ne" in v and field == v["$ne"]:
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

    def find(self, query=None):
        return _Cursor([d for d in self.docs if _match(query or {}, d)])

    async def count_documents(self, query):
        return len([d for d in self.docs if _match(query or {}, d)])


B1 = ObjectId()
CO1 = ObjectId()

# Sessions are spread across the three calendar collections, with assigned_member_ids
# present in the raw docs to prove they are NOT surfaced (no PII / no member leakage).
STAFF_SESS = [
    {"_id": ObjectId(), "title": "Kickoff Strategy", "start": "2026-06-02T10:00",
     "status": "completed", "session_type": "CEO Direct", "batch_id": str(B1),
     "company_id": str(CO1), "assigned_member_ids": ["m1", "m2"]},
]
LEARNER_SESS = [
    {"_id": ObjectId(), "title": "Module Review", "start": "2026-06-09T15:00",
     "status": "scheduled", "session_type": "Module Review", "batch_id": str(B1),
     "company_id": str(CO1), "assigned_member_ids": ["m3"]},
    {"_id": ObjectId(), "title": "Old Session", "start": "2026-05-01T09:00",
     "status": "completed", "session_type": "Support Check", "batch_id": "other_batch",
     "company_id": "other_co", "assigned_member_ids": ["m4"]},
]
EVENTS = [
    {"_id": ObjectId(), "title": "Upcoming Ops Sync", "start": "2026-06-12T11:00",
     "status": "scheduled", "session_type": "Operational", "batch_id": str(B1),
     "company_id": str(CO1), "assigned_member_ids": ["m5"]},
]


def _resolver():
    cols = {
        "STAFF_CALENDER": FakeCollection([dict(d) for d in STAFF_SESS]),
        "LEARNER_CALENDER": FakeCollection([dict(d) for d in LEARNER_SESS]),
        "calendar_events": FakeCollection([dict(d) for d in EVENTS]),
    }
    return lambda name: cols.setdefault(name, FakeCollection())


SA = UserContext(user_id="sa1", full_name="Dipti", role="superadmin")
ADMIN = UserContext(user_id="ad1", full_name="Coach", role="admin")
CADMIN = UserContext(user_id="ca1", full_name="Owner", role="clientadmin", company_id=str(CO1))
LEARNER = UserContext(user_id="cu1", full_name="Asha", role="clientuser", company_id=str(CO1))

results = []


def check(name, cond, extra=""):
    results.append(bool(cond))
    print(f"  [{'PASS' if cond else 'FAIL'}] {name}{(' — ' + extra) if extra else ''}")


# The 8 product sections → the tool(s) that answer them. A section is "covered"
# for a role if the role can call at least one of its tools.
SECTIONS = {
    "Dashboard": {"get_dashboard_stats"},
    "Companies": {"list_companies", "get_company_overview"},
    "Batches": {"list_batches", "get_batch_details"},
    "Session Templates": {"get_session_templates"},
    "User Management": {"list_users", "get_user_activity"},
    "Calendar": {"get_my_sessions", "list_sessions"},
    "Support Engine": {"get_support_engine_status", "search_knowledge"},
    "Media Library": {"search_media_library", "list_media_library"},
}


async def main():
    calendar_tools.get_collection = _resolver()
    registry.register_all()
    print("\n=== Phase 7 — Section coverage + org-wide Calendar tool ===\n")

    # 1) RBAC — list_sessions is superadmin-only (org-wide data stays SA-only).
    print("RBAC gating (list_sessions is SA-only):")
    sa_tools = {t.name for t in registry.tools_for_role("superadmin")}
    ad_tools = {t.name for t in registry.tools_for_role("admin")}
    ca_tools = {t.name for t in registry.tools_for_role("clientadmin")}
    cu_tools = {t.name for t in registry.tools_for_role("clientuser")}
    check("SA sees list_sessions", "list_sessions" in sa_tools)
    check("AD does NOT see list_sessions", "list_sessions" not in ad_tools)
    check("CA does NOT see list_sessions", "list_sessions" not in ca_tools)
    check("CU does NOT see list_sessions", "list_sessions" not in cu_tools)

    # Execution gate (defense-in-depth): non-SA invocation is denied before DB.
    spec = registry.get_tool("list_sessions")
    denied = await registry.execute_tool(spec, ADMIN, {})
    check("AD execution of list_sessions denied", not denied.success, denied.error or "")

    # 2) list_sessions — org-wide read across all three calendar collections.
    print("\nOrg-wide reads + filters:")
    r_all = await calendar_tools.list_sessions(SA)
    titles = {s["title"] for s in r_all.data["sessions"]}
    check("returns sessions from all 3 collections",
          {"Kickoff Strategy", "Module Review", "Upcoming Ops Sync", "Old Session"} <= titles)
    check("scope is global", r_all.meta.scope_applied == "global")
    check("no attendee ids leaked (no PII)",
          all("assigned_member_ids" not in s for s in r_all.data["sessions"]))

    # Date-range filter (only June 2026).
    r_june = await calendar_tools.list_sessions(SA, from_date="2026-06-01", to_date="2026-06-30")
    j_titles = {s["title"] for s in r_june.data["sessions"]}
    check("date range excludes May session", "Old Session" not in j_titles and "Module Review" in j_titles)

    # Batch filter.
    r_batch = await calendar_tools.list_sessions(SA, batch_id=str(B1))
    check("batch filter narrows to that batch",
          all(s.get("batch_id") == str(B1) for s in r_batch.data["sessions"])
          and len(r_batch.data["sessions"]) == 3)

    # Status filter (case-insensitive → lowercased).
    r_done = await calendar_tools.list_sessions(SA, status="Completed")
    check("status filter (lowercased) works",
          all(s.get("status") == "completed" for s in r_done.data["sessions"])
          and len(r_done.data["sessions"]) == 2)

    # Session-type keyword (regex, case-insensitive substring).
    r_type = await calendar_tools.list_sessions(SA, session_type="module")
    check("session_type keyword filter works",
          [s["title"] for s in r_type.data["sessions"]] == ["Module Review"])

    # Sorted ascending by start.
    starts = [s.get("start") for s in r_all.data["sessions"]]
    check("results sorted by start ascending", starts == sorted(starts))

    # 3) Section coverage — every section answerable by the superadmin.
    print("\nSection coverage (superadmin sees a tool for all 8 sections):")
    for section, tools in SECTIONS.items():
        covered = bool(tools & sa_tools)
        check(f"{section} covered", covered, "" if covered else f"need one of {tools}")

    # Learner/admin still covered for the self-service sections (no org tools).
    print("\nNon-SA still covered for personal sections:")
    check("CU has Dashboard", "get_dashboard_stats" in cu_tools)
    check("CU has Calendar (own)", "get_my_sessions" in cu_tools)
    check("CU has Support Engine", "get_support_engine_status" in cu_tools)
    check("CU has Media Library (search)", "search_media_library" in cu_tools)
    check("CU CANNOT reach org Companies/Batches/Users",
          not ({"list_companies", "list_batches", "list_users"} & cu_tools))

    # 4) Superadmin prompt advertises the new org-wide Calendar tool.
    print("\nPrompt wiring:")
    sa_prompt = build_system_prompt(SA)
    check("SA prompt mentions list_sessions", "list_sessions" in sa_prompt)
    cu_prompt = build_system_prompt(LEARNER)
    check("CU prompt keeps own-data privacy", "only access the current user's own data" in cu_prompt)

    # 5) Whisper transcription routing (preferred; Google is the fallback).
    print("\nWhisper transcription routing:")
    orig_key = getattr(__import__("app.config.settings", fromlist=["settings"]).settings,
                       "OPENAI_API_KEY", None)
    from app.config.settings import settings as _settings

    _settings.OPENAI_API_KEY = "sk-test"
    check("whisper_available true when key set", ts.whisper_available() is True)
    _settings.OPENAI_API_KEY = ""
    check("whisper_available false when no key", ts.whisper_available() is False)
    check("_whisper_transcribe returns None without key",
          await ts._whisper_transcribe("nonexistent.wav") is None)

    # transcribe_audio_chunk uses Whisper when it succeeds...
    async def _fake_whisper_ok(_path):
        return "whisper-said-this"

    ts._whisper_transcribe = _fake_whisper_ok
    out = await ts.transcribe_audio_chunk("anything.wav")
    check("chunk transcriber uses Whisper result", out == "whisper-said-this")

    # ...and falls back to Google when Whisper is unavailable.
    async def _fake_whisper_none(_path):
        return None

    ts._whisper_transcribe = _fake_whisper_none
    ts.sync_transcribe_wav = lambda _p: "google-said-this"
    out2 = await ts.transcribe_audio_chunk("anything.wav")
    check("chunk transcriber falls back to Google", out2 == "google-said-this")

    _settings.OPENAI_API_KEY = orig_key  # restore

    passed = sum(1 for c in results if c)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
