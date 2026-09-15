"""
Company-scoped usernames — a login identity that is unique even when an email is not.

WHY THIS EXISTS
---------------
One person can legitimately hold an account in several client companies: the same consultant
works for two of them, and wants the same mailbox on both. Email was the login identity and
the session identity, so two accounts sharing an address were indistinguishable — and because
`get_user_from_token` resolved the session by email, the second account would have silently
inherited whichever document Mongo happened to return first. A username fixes both halves:
it is unique by construction, and the session now travels on the user's `_id`.

SHAPE
-----
    <PREFIX>_Users<NNN>          e.g.  PTP_Users001

`PREFIX` belongs to the company ("People to Process" -> "PTP") and is stored on the company
document, so it is derived once and can be corrected by an admin afterwards. The number is the
next free one in that company, zero-padded to three digits and allowed to outgrow it (a
company with a thousand people gets `PTP_Users1000`, not a collision).

UNIQUENESS
----------
Users live in two collections (`staff` and `learners`), and Mongo cannot span a unique index
across both — so the index on each is a safety net and the real check is
`username_exists()`, which looks in both before handing a name out. Generation also re-checks
inside its loop, because two admins importing rosters at the same instant would otherwise both
be told `PTP_Users004` is free.
"""
import logging
import re
from typing import Optional

from app.db.mongodb import get_collection

logger = logging.getLogger(__name__)

USER_COLLECTIONS = ("staff", "learners")

# The literal middle of the pattern. Kept as a constant so the parser and the formatter can
# never disagree about what a username looks like.
USERNAME_INFIX = "_Users"
SEQUENCE_PAD = 3

PREFIX_MIN = 2
PREFIX_MAX = 6
SINGLE_WORD_PREFIX_LEN = 4
FALLBACK_PREFIX = "ORG"

# Dropped before initials are taken. These say what KIND of company it is, not which one, so
# they make every prefix longer without making any of it more distinctive.
_CORPORATE_NOISE = {
    "pvt", "private", "ltd", "limited", "llp", "llc", "inc", "incorporated",
    "co", "corp", "corporation", "company", "and", "the",
}


def derive_prefix(company_name: str) -> str:
    """A company's default username prefix: the initials of its name.

    "People to Process" -> "PTP", exactly as an admin would write it by hand. Short words are
    deliberately KEPT ("to" is the T in PTP) because dropping them produces a prefix nobody
    recognises as their own company.

    Two conventions in this roster are stripped first: a trailing " - Industry" tag
    ("Jolly Healthcare - Pharmaceuticals") describes the sector rather than the business, and
    corporate suffixes ("Pvt. Ltd") are the same on half the list.

    This is only a DEFAULT. It is stored on the company and editable, because no rule gets
    every name right and the prefix is something people read every day.
    """
    name = str(company_name or "").strip()
    # "Jolly Healthcare - Pharmaceuticals" -> "Jolly Healthcare". Only a dash with space
    # around it, so a hyphenated name ("Icare Lifts-Logistics") is not cut in half by accident.
    name = re.split(r"\s+[-–—]\s+", name)[0].strip() or name

    words = [w for w in re.split(r"[^A-Za-z0-9]+", name) if w]
    meaningful = [w for w in words if w.lower() not in _CORPORATE_NOISE] or words
    initials = "".join(w[0] for w in meaningful if w[0].isalpha()).upper()

    if len(initials) < PREFIX_MIN:
        # A one-word name ("Kutchina") has only one initial, which is not a prefix anybody
        # could tell apart — use the start of the word itself instead. Four letters, not six:
        # "KUTC" reads as a short code, "KUTCHI" reads as a truncated word.
        letters = re.sub(r"[^A-Za-z]", "", "".join(meaningful)).upper()
        initials = letters[:SINGLE_WORD_PREFIX_LEN] if letters else ""

    return (initials[:PREFIX_MAX] or FALLBACK_PREFIX)


def format_username(prefix: str, sequence: int) -> str:
    """(PTP, 1) -> 'PTP_Users001'. Numbers past 999 simply get longer rather than wrapping."""
    return f"{prefix}{USERNAME_INFIX}{sequence:0{SEQUENCE_PAD}d}"


def parse_username(username: str) -> Optional[tuple]:
    """'PTP_Users001' -> ('PTP', 1), or None when it does not follow the pattern.

    A username an admin has typed by hand need not match, which is why the sequence scan
    ignores anything this cannot read rather than guessing a number out of it.
    """
    m = re.fullmatch(rf"([A-Za-z0-9]+){re.escape(USERNAME_INFIX)}(\d+)", str(username or "").strip())
    return (m.group(1), int(m.group(2))) if m else None


async def username_exists(username: str, exclude_id: Optional[str] = None) -> bool:
    """Whether this username is taken anywhere. Case-insensitive: two accounts differing only
    in case would be indistinguishable at a login prompt, so they are treated as the same."""
    if not username:
        return False
    pattern = {"$regex": f"^{re.escape(str(username).strip())}$", "$options": "i"}
    for coll in USER_COLLECTIONS:
        query = {"username": pattern}
        if exclude_id:
            from bson import ObjectId
            try:
                query["_id"] = {"$ne": ObjectId(str(exclude_id))}
            except Exception:
                pass
        if await get_collection(coll).find_one(query, {"_id": 1}):
            return True
    return False


async def company_prefix(company_id: Optional[str]) -> str:
    """The stored prefix for a company, deriving and saving one on first use.

    Written back so the prefix is stable: deriving it fresh each time would silently renumber
    everyone the day somebody corrects a typo in the company name.
    """
    if not company_id:
        return FALLBACK_PREFIX
    from bson import ObjectId
    col = get_collection("companies")
    try:
        doc = await col.find_one({"_id": ObjectId(str(company_id))})
    except Exception:
        return FALLBACK_PREFIX
    if not doc:
        return FALLBACK_PREFIX

    stored = str(doc.get("username_prefix") or "").strip().upper()
    if stored:
        return stored

    prefix = derive_prefix(doc.get("name"))
    # Two companies can derive the same initials ("Amrit Cement" and "ATMA Consulting" are
    # both AC). Only the first keeps it; the rest get a digit, so a username still names one
    # company unambiguously.
    taken = {str(c.get("username_prefix") or "").strip().upper()
             for c in await col.find({"_id": {"$ne": doc["_id"]}},
                                     {"username_prefix": 1}).to_list(1000)}
    taken.discard("")
    candidate, n = prefix, 1
    while candidate in taken:
        n += 1
        candidate = f"{prefix[:PREFIX_MAX - len(str(n))]}{n}"
    await col.update_one({"_id": doc["_id"]}, {"$set": {"username_prefix": candidate}})
    return candidate


async def next_username(company_id: Optional[str]) -> str:
    """The next free username for a company.

    The sequence is derived from the usernames already issued rather than from a counter, so a
    deleted user's number is not reused while their old records still name it, and nothing
    breaks if rows are imported out of order.
    """
    prefix = await company_prefix(company_id)
    highest = 0
    for coll in USER_COLLECTIONS:
        async for doc in get_collection(coll).find(
                {"username": {"$regex": f"^{re.escape(prefix)}{re.escape(USERNAME_INFIX)}\\d+$",
                              "$options": "i"}},
                {"username": 1}):
            parsed = parse_username(doc.get("username"))
            if parsed and parsed[1] > highest:
                highest = parsed[1]

    # Re-checked in the loop, not just once: two imports running at the same moment would
    # otherwise both be handed the same "next" number.
    for candidate_seq in range(highest + 1, highest + 1000):
        candidate = format_username(prefix, candidate_seq)
        if not await username_exists(candidate):
            return candidate
    raise RuntimeError(f"Could not find a free username for prefix '{prefix}'")


async def assign_username(user_doc: dict, company_id: Optional[str] = None) -> str:
    """Give a user document a username, leaving any existing one alone.

    Mutates and returns, so the callers that build a dict then insert it can simply call this
    before the insert.
    """
    existing = str(user_doc.get("username") or "").strip()
    if existing:
        return existing
    username = await next_username(company_id or user_doc.get("company_id"))
    user_doc["username"] = username
    return username


async def backfill_usernames(company_id: Optional[str] = None, dry_run: bool = False) -> dict:
    """Give every user without a username one. Idempotent: an account that has one is skipped.

    Ordered by creation date so the numbers follow the order people actually joined, which is
    what anybody reading a list of usernames will assume they mean.
    """
    scope = {"username": {"$in": [None, ""]}}
    if company_id:
        scope["company_id"] = str(company_id)

    pending = []
    for coll in USER_COLLECTIONS:
        async for doc in get_collection(coll).find(
                scope, {"company_id": 1, "created_at": 1, "full_name": 1, "email": 1}):
            pending.append({**doc, "_coll": coll})
    pending.sort(key=lambda d: (str(d.get("company_id") or ""), str(d.get("created_at") or "")))

    # The sequence is advanced IN MEMORY, per company, rather than by re-reading the database
    # for each user. Two reasons, and the first is a correctness one:
    #
    #   · next_username() derives the next number from the usernames already stored, so during
    #     a dry run — where nothing is stored — it would hand out 001 to everybody and the
    #     preview would be a lie. The counter has to live outside the database for the preview
    #     to mean anything, and a preview nobody can trust is worse than no preview.
    #   · it turns 287 full scans of both collections into one scan per company.
    #
    # Each company's starting point still comes from the database, so a backfill that is run
    # twice, or after new users have been created, continues rather than restarting.
    counters: dict = {}
    assigned, skipped = [], 0

    for doc in pending:
        # Internal staff have no company. They still need something to sign in with, so they
        # are issued a name under the fallback prefix rather than left without one.
        cid = doc.get("company_id") or None
        key = str(cid or "")

        if key not in counters:
            try:
                seed = await next_username(cid)
            except RuntimeError as e:
                logger.error(f"Username backfill: {e}")
                skipped += 1
                continue
            parsed = parse_username(seed)
            counters[key] = {"prefix": parsed[0], "next": parsed[1]} if parsed else None
        state = counters.get(key)
        if not state:
            skipped += 1
            continue

        username = format_username(state["prefix"], state["next"])
        state["next"] += 1
        assigned.append({"id": str(doc["_id"]), "collection": doc["_coll"],
                         "name": doc.get("full_name") or doc.get("email"),
                         "company_id": key, "username": username})
        if not dry_run:
            await get_collection(doc["_coll"]).update_one(
                {"_id": doc["_id"]}, {"$set": {"username": username}})

    return {"assigned": len(assigned), "skipped": skipped,
            "dry_run": dry_run, "usernames": assigned}
