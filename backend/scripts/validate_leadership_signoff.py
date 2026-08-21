"""Leadership level sign-off validator - source-document review gate.

Runs entirely against an IN-MEMORY fake Mongo. No real database is opened, no existing
TPMS document is read or written, and no email is sent. Safe to run at any time.

Background: "Key insights of Leadership Score" carries defects that change WHAT A LEADER
IS SCORED ON - at L5 and L7 several question titles name one parameter while their four
options measure a different one, and L7 Q6 printed its option scores in reverse merit
order. Those cannot be guessed at in code, so the module records them, shows them, and
refuses to FREEZE a score built from a level nobody has approved.

What it proves:

  verbatim       Every question, option, letter and SCORE matches the printed document
                 exactly - including its typos, its duplicated option sets and L7 Q6's
                 inverted scoring. Nothing is corrected in code.
  drift          A database already holding different values is REPORTED, never rewritten.
  register       Every defective question carries its issue, and every clean one does not.
  read overlay   Rows seeded BEFORE the register existed still report their issue, so no
                 stored document has to be migrated for the flags to appear.
  fingerprint    Sign-off records the exact rubric approved. Retitling a question, moving
                 a weightage or restating an option invalidates it; reordering does not.
  stale = unsigned  An out-of-date approval is reported as NOT signed off, never as
                 "signed off (stale)" - the two must not be distinguishable to a caller.
  weightage      A level whose weightages do not total 100 cannot be signed off at all.
  compute gate   Freezing a score is refused while any enrolled level is unapproved, and
                 the error names the levels and why. Closing the window is not gated.
  scope          Only levels actually enrolled block the close - an unapproved L7 does
                 not hold up a cycle with nobody at L7.
  collect stays open  Sign-off gates ONLY the close. Setting up and collecting feedback
                 are untouched, so the flow can be tested end to end first.

Usage (PowerShell, from backend/):
    python scripts/validate_leadership_signoff.py
"""
from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime

from bson import ObjectId

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OK, BAD = "[PASS]", "[FAIL]"
_results: list = []


def check(label: str, condition: bool, detail: str = "") -> bool:
    _results.append(bool(condition))
    print(f"{OK if condition else BAD} {label}" + (f"  ({detail})" if detail else ""))
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} " + "-" * max(0, 62 - len(title)))


# ─────────────────────────────────────────────────────────────
# In-memory Mongo stand-in
# ─────────────────────────────────────────────────────────────
class FakeCollection:
    def __init__(self, docs=None):
        # Mongo stamps `_id` on insert and the service relies on it; seed the same way so
        # a missing id cannot fail a check for a reason unrelated to sign-off.
        self.docs = []
        for d in (docs or []):
            self.docs.append({"_id": ObjectId(), **dict(d)})

    @staticmethod
    def _match(doc, query):
        for k, cond in (query or {}).items():
            v = doc.get(k)
            if isinstance(cond, dict):
                if "$ne" in cond and v == cond["$ne"]:
                    return False
                if "$in" in cond and v not in cond["$in"]:
                    return False
            elif v != cond:
                return False
        return True

    def find(self, query=None, *a, **k):
        rows = [d for d in self.docs if self._match(d, query or {})]

        class _C:
            def sort(self, *a, **k):
                return self

            async def to_list(self, n=None):
                return rows
        return _C()

    async def find_one(self, query):
        for d in self.docs:
            if self._match(d, query):
                return d
        return None

    async def count_documents(self, query):
        return len([d for d in self.docs if self._match(d, query)])

    async def update_one(self, query, update, upsert=False):
        # Mirrors pymongo's return shape - update_cycle branches on `matched_count`, so a
        # bare None here would fail a check for a harness reason, not a code one.
        class _R:
            def __init__(self, matched):
                self.matched_count = matched
                self.modified_count = matched

        for d in self.docs:
            if self._match(d, query):
                d.update(update.get("$set", {}))
                return _R(1)
        if upsert:
            self.docs.append({"_id": ObjectId(), **query, **update.get("$set", {}),
                              **update.get("$setOnInsert", {})})
            return _R(0)
        return _R(0)

    async def insert_one(self, doc):
        self.docs.append(dict(doc))

    async def insert_many(self, docs, ordered=True):
        self.docs.extend(dict(d) for d in docs)

    async def delete_one(self, query):
        for i, d in enumerate(self.docs):
            if self._match(d, query):
                self.docs.pop(i)

                class _R:
                    deleted_count = 1
                return _R()

        class _R0:
            deleted_count = 0
        return _R0()


class Harness:
    """Fake collections wired under leadership_service."""

    def __init__(self, *, questions=None, subjects=None, cycles=None):
        self.questions = FakeCollection(questions or [])
        self.subjects = FakeCollection(subjects or [])
        self.cycles = FakeCollection(cycles or [])
        self.signoff = FakeCollection()
        self.empty = FakeCollection()

    def collection(self, name):
        return {
            "tpms_leadership_questions": self.questions,
            "tpms_leadership_subjects": self.subjects,
            "tpms_leadership_cycles": self.cycles,
            "tpms_leadership_level_signoff": self.signoff,
        }.get(name, self.empty)


HR = {"_id": "u-hr", "full_name": "Priya (HR)"}


async def main() -> int:
    from app.models import leadership as M
    from app.services import leadership_service as svc

    # ── verbatim fidelity ─────────────────────────────────────
    section("Verbatim fidelity to the HR document")

    def opts(level, item_id):
        q = next(q for q in M.LEADERSHIP_QUESTION_SEED[level] if q["item_id"] == item_id)
        return [(o["option_id"], o["label"], o["score"]) for o in q["options"]]

    # L7 Q6 as PRINTED: a=1 (best answer, lowest score) ... d=5. Reproduced, not repaired.
    check("L7 Q6 keeps the document's inverted scoring",
          opts("L7", "L7Q6") == [
              ("a", "Goals are aligned and largely executed", 1),
              ("b", "Goals are embedded and strategy drives action", 2),
              ("c", "Goals are unclear and execution is inconsistent", 4),
              ("d", "Goals are communicated, execution is uneven", 5),
          ], "best answer still scores 1, exactly as printed")
    check("L7 Q6 is flagged blocking rather than fixed",
          M.question_review("L7Q6")["severity"] == M.SEVERITY_BLOCKING)

    check("the document's typo is preserved",
          any("delf-driven" in o[1] for o in opts("L4", "L4Q1")))
    check("L4 Q5's ungrammatical option is preserved",
          opts("L4", "L4Q5")[3][1] == "Accountable for Teams self-track")
    check("L4 Q5 keeps the option imported from L7",
          opts("L4", "L4Q5")[0][1] == "Loses accountability under scale")
    check("L6 Q6 keeps its lowercase lettering",
          [o[0] for o in opts("L6", "L6Q6")] == ["a", "b", "c", "d"])
    check("L5 Q3 keeps priority options under a communication heading",
          opts("L5", "L5Q3")[0][1] == "Everything feels urgent.")
    check("L7 Q1 keeps team-structure options under a counselling heading",
          opts("L7", "L7Q1")[0][1] == "Team depends heavily on leader")

    every = [(lv, q["item_id"], o["score"])
             for lv, qs in M.LEADERSHIP_QUESTION_SEED.items()
             for q in qs for o in q["options"]]
    check("no option is ever worth 3, on any level",
          all(sc in (1, 2, 4, 5) for _, _, sc in every), f"{len(every)} options checked")
    check("question counts match the document (5/5/6/6)",
          [len(M.LEADERSHIP_QUESTION_SEED[lv]) for lv in M.LEVELS] == [5, 5, 6, 6])

    # ── drift ─────────────────────────────────────────────────
    section("Drift from the document is reported, not repaired")

    check("a clean seed reports no drift",
          M.source_drift("L7", M.seed_rows_for_level("L7")) == [])

    corrupted = M.seed_rows_for_level("L7")
    q6 = next(r for r in corrupted if r["item_id"] == "L7Q6")
    for o in q6["options"]:            # an older build's merit-ordered scores
        o["score"] = {"a": 4, "b": 5, "c": 1, "d": 2}[o["option_id"]]
    d = M.source_drift("L7", corrupted)
    check("a database holding different scores is detected",
          len(d) == 1 and d[0]["item_id"] == "L7Q6")
    check("the drift names both values",
          any("document prints 1" in x for x in d[0]["differences"]),
          d[0]["differences"][0])
    check("the corrupted row itself is untouched",
          q6["options"][0]["score"] == 4, "reported only - nothing rewritten")

    reworded = M.seed_rows_for_level("L4")
    reworded[0]["options"][3]["label"] = "Fully self-driven, anticipates issues"
    check("an admin fixing the typo also shows as drift",
          any("delf-driven" in x for r in M.source_drift("L4", reworded)
              for x in r["differences"]),
          "the screen can always answer 'does this match the document?'")

    # ── register ──────────────────────────────────────────────
    section("Source-document register")

    flagged = {lv: [r["item_id"] for r in M.seed_rows_for_level(lv) if r["needs_review"]]
               for lv in M.LEVELS}
    check("L5 Q3/Q4/Q5 rotation is flagged",
          {"L5Q3", "L5Q4", "L5Q5"} <= set(flagged["L5"]), str(flagged["L5"]))
    check("every L7 question is flagged",
          len(flagged["L7"]) == 6, str(flagged["L7"]))
    check("L4 Q5 imported option is flagged", flagged["L4"] == ["L4Q5"])
    check("L6 is flagged only on Q5", flagged["L6"] == ["L6Q5"])
    check("clean questions carry no issue",
          M.question_review("L4Q1") is None and M.question_review("L6Q2") is None)
    check("L7 records its two unmeasured parameters",
          any(i["code"] == M.REVIEW_NOT_MEASURED for i in M.level_review("L7")))
    check("the missing '3' is raised on every level",
          all(any(i["code"] == M.REVIEW_SCALE for i in M.level_review(lv))
              for lv in M.LEVELS))

    # ── fingerprint ───────────────────────────────────────────
    section("Fingerprint")

    base = M.seed_rows_for_level("L7")
    fp = M.signoff_fingerprint(base)

    retitled = M.seed_rows_for_level("L7")
    retitled[0]["title"] = "Team structure / building"
    check("retitling a question invalidates the approval",
          M.signoff_fingerprint(retitled) != fp)

    reweighted = M.seed_rows_for_level("L7")
    reweighted[0]["weightage"] = 30.0
    check("moving a weightage invalidates the approval",
          M.signoff_fingerprint(reweighted) != fp)

    restated = M.seed_rows_for_level("L7")
    restated[0]["options"][0]["label"] = "Reworded"
    check("restating an option invalidates the approval",
          M.signoff_fingerprint(restated) != fp)

    rescored = M.seed_rows_for_level("L7")
    rescored[0]["options"][0]["score"] = 3
    check("rescoring an option invalidates the approval",
          M.signoff_fingerprint(rescored) != fp)

    reordered = list(reversed(M.seed_rows_for_level("L7")))
    check("reordering the form does NOT invalidate it",
          M.signoff_fingerprint(reordered) == fp, "no score depends on order")

    # ── sign-off lifecycle ────────────────────────────────────
    section("Sign-off lifecycle")

    h = Harness(questions=M.all_seed_rows())
    svc.get_collection = h.collection

    state = await svc.level_signoff("c1", "L6")
    check("a fresh level starts unsigned", state["signed_off"] is False)

    state = await svc.set_level_signoff("c1", "L6", "Reviewed with MD", HR)
    check("sign-off is recorded", state["signed_off"] is True)
    check("the approver is named", state["signed_off_by"] == "Priya (HR)")
    check("the open issues are stored with it",
          len(state["acknowledged_issues"]) == len(M.level_review("L6")))

    # edit AFTER approval
    await h.questions.update_one({"level": "L6", "item_id": "L6Q1"},
                                 {"$set": {"title": "Reworded after approval"}})
    state = await svc.level_signoff("c1", "L6")
    check("an edit after approval marks it stale", state["stale"] is True)
    check("a stale approval reports as NOT signed off", state["signed_off"] is False,
          "the two must be indistinguishable to a caller")

    state = await svc.set_level_signoff("c1", "L6", "Re-approved", HR)
    check("re-approving clears stale", state["signed_off"] and not state["stale"])

    await svc.clear_level_signoff("c1", "L6")
    check("approval can be withdrawn",
          (await svc.level_signoff("c1", "L6"))["signed_off"] is False)

    # ── read-time overlay (no migration) ──────────────────────
    section("Read overlay - rows seeded before the register")

    legacy = [dict(r) for r in M.seed_rows_for_level("L5")]
    for r in legacy:                      # strip the fields, as an old seed would have
        r.pop("needs_review", None)
        r.pop("review_code", None)
        r.pop("review_note", None)
    h2 = Harness(questions=legacy)
    svc.get_collection = h2.collection
    rows = await svc.get_questions("L5")
    check("legacy rows still report their issue",
          [r["item_id"] for r in rows if r["needs_review"]] == ["L5Q2", "L5Q3", "L5Q4", "L5Q5"],
          "nothing in the collection was rewritten")
    check("the note travels with the row",
          "PRIORITY SETTING" in (next(r for r in rows if r["item_id"] == "L5Q3")["review_note"]))

    # ── weightage precondition ────────────────────────────────
    section("Weightage precondition")

    broken = [dict(r) for r in M.seed_rows_for_level("L4")]
    broken[0]["weightage"] = 5.0                      # column no longer totals 100
    h3 = Harness(questions=broken)
    svc.get_collection = h3.collection
    try:
        await svc.set_level_signoff("c1", "L4", "", HR)
        check("a level not totalling 100 cannot be signed off", False)
    except ValueError as e:
        check("a level not totalling 100 cannot be signed off", True, str(e)[:52])

    # ── close gate ────────────────────────────────────────────
    section("Compute gate - sign-off blocks FREEZING a score")

    cycle = {"company_id": "c1", "cycle": "2026-C1", "status": M.CYCLE_CLOSED,
             "degree": M.DEGREE_360, "min_responses": 3, "quorum": 5}
    subjects = [{"company_id": "c1", "cycle": "2026-C1", "subject_id": "s1", "level": "L5"},
                {"company_id": "c1", "cycle": "2026-C1", "subject_id": "s2", "level": "L6"}]
    h4 = Harness(questions=M.all_seed_rows(), subjects=subjects, cycles=[cycle])
    svc.get_collection = h4.collection

    pending = await svc.unsigned_levels("c1", "2026-C1")
    check("both enrolled levels start unapproved",
          sorted(p["level"] for p in pending) == ["L5", "L6"])
    check("L7 does not block - nobody is enrolled at it",
          "L7" not in [p["level"] for p in pending])

    # The gate sits on COMPUTED, not CLOSED. Closing merely shuts the window; computing is
    # what freezes a number and is the first irreversible step toward showing it to anyone.
    try:
        await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_COMPUTED}, HR)
        check("computing is refused while a level is unapproved", False)
    except ValueError as e:
        msg = str(e)
        check("computing is refused while a level is unapproved", True)
        check("the error names the levels", "Manager" in msg and "Senior Manager" in msg,
              msg[:70])

    await svc.set_level_signoff("c1", "L5", "", HR)
    try:
        await svc.update_cycle("c1", "2026-C1", {"status": M.CYCLE_COMPUTED}, HR)
        check("one approval is not enough - L6 still blocks", False)
    except ValueError as e:
        check("one approval is not enough - L6 still blocks", "Senior Manager" in str(e))

    await svc.set_level_signoff("c1", "L6", "", HR)
    check("every enrolled level approved clears the gate",
          not await svc.unsigned_levels("c1", "2026-C1"))

    # a stale approval must re-block
    await h4.questions.update_one({"level": "L5", "item_id": "L5Q1"},
                                  {"$set": {"weightage": 40.0}})
    pending = await svc.unsigned_levels("c1", "2026-C1")
    check("editing an approved level re-blocks the compute",
          [p["level"] for p in pending] == ["L5"] and pending[0]["stale"] is True)

    # ── nothing else is gated ─────────────────────────────────
    section("Collection stays open")

    draft = {**cycle, "status": M.CYCLE_DRAFT}
    h5 = Harness(questions=M.all_seed_rows(), cycles=[draft])
    svc.get_collection = h5.collection
    updated = await svc.update_cycle("c1", "2026-C1", {"notes": "still editable"}, HR)
    check("a cycle with no approvals can still be edited",
          updated.get("notes") == "still editable")
    check("and it can still be opened",
          (await svc.update_cycle("c1", "2026-C1",
                                  {"status": M.CYCLE_OPEN}, HR)).get("status") == M.CYCLE_OPEN)
    check("and closed - shutting the window needs no approval",
          (await svc.update_cycle("c1", "2026-C1",
                                  {"status": M.CYCLE_CLOSED}, HR)).get("status") == M.CYCLE_CLOSED,
          "sign-off gates the FREEZE, so collection can be tested end to end first")

    # ── summary ───────────────────────────────────────────────
    passed, total = sum(_results), len(_results)
    print(f"\n{'=' * 66}\n{passed}/{total} checks passed"
          f"{'' if passed == total else '  <-- FAILURES ABOVE'}\n{'=' * 66}")
    return 0 if passed == total else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
