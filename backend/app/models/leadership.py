"""
TPMS ▸ Leadership Score — domain model, question master seed and payloads.

Leadership Score is one of the four matrices of the OD Matrix. It is a purely
feedback-derived score: 8 anonymous givers (2 superiors, 2 peers, 2 other-department
peers, 2 direct reports) rate one leader against level-specific expectations, once
every 2 months, and the weighted result is discussed at RRO.

ISOLATION
---------
This module owns its own collections exclusively (every name below is new). It does
not read, write, migrate or restructure any existing TPMS collection — the four
existing forms (Accountability / Ownership / Culture / Implementation Feedback), their
submissions, their assignments and their scoring are untouched by design. Where TPMS
infrastructure is reused it is reused as *pure functions* (token minting, period
arithmetic), never as shared storage.

WHY A SEPARATE QUESTION MASTER
------------------------------
`tpms_form_questions` is keyed (form_type, item_id) and its rows carry no level,
options or weightage. Leadership questions are keyed (level, item_id) and each carries
four scored options plus a weightage. Rather than widen the existing master — which
would touch rows the other four forms depend on — Leadership Score keeps its own.

SOURCE FIDELITY
---------------
LEADERSHIP_QUESTION_SEED below is transcribed VERBATIM from "Key insights of Leadership
Score", including its option scores (1 / 2 / 4 / 5 — note that 3 is never awarded) and
its original wording and typography. Several inconsistencies in the source are
preserved rather than corrected; they are listed in
docs/LEADERSHIP_SCORE_IMPLEMENTATION_PLAN.md §3 and were reported to the business.
Nothing here silently "fixes" the document. All question text, option text, option
scores and weightages are editable at runtime through the admin API, which is the
intended place to apply corrections once they are signed off.
"""
from pydantic import BaseModel, Field, field_validator
from typing import Dict, List, Optional
from datetime import datetime


# ─────────────────────────────────────────────────────────────
# Collections — ALL NEW. None of these exist in TPMS today.
# ─────────────────────────────────────────────────────────────
COLL_LS_CYCLES      = "tpms_leadership_cycles"       # one per (company, cycle)
COLL_LS_SUBJECTS    = "tpms_leadership_subjects"     # leaders enrolled into a cycle
COLL_LS_ASSIGNMENTS = "tpms_leadership_assignments"  # one mailed link per (subject, giver)
COLL_LS_RESPONSES   = "tpms_leadership_responses"    # one submitted feedback form
COLL_LS_QUESTIONS   = "tpms_leadership_questions"    # level-specific question master
COLL_LS_SCORES      = "tpms_leadership_scores"       # snapshot taken when a cycle closes


# ─────────────────────────────────────────────────────────────
# Leadership levels — "Applicable from L4 (Asst Managers) and above".
# "Feedback parameters will differ from designation to designation."
# ─────────────────────────────────────────────────────────────
LEVEL_L4 = "L4"
LEVEL_L5 = "L5"
LEVEL_L6 = "L6"
LEVEL_L7 = "L7"          # "L7 & ABOVE"

LEVELS: List[str] = [LEVEL_L4, LEVEL_L5, LEVEL_L6, LEVEL_L7]

LEVEL_LABELS: Dict[str, str] = {
    LEVEL_L4: "L-4 (Asst. Manager)",
    LEVEL_L5: "L-5 (Manager)",
    LEVEL_L6: "L-6 (Senior Manager)",
    LEVEL_L7: "L7 & Above",
}

LEVEL_THEMES: Dict[str, str] = {
    LEVEL_L4: "Self-Management + Managing Other",
    LEVEL_L5: "Managing self and other managers",
    LEVEL_L6: "Managers' productivity, measurement, innovation",
    LEVEL_L7: "Strategy, business acumen, alignment",
}


# ─────────────────────────────────────────────────────────────
# Feedback givers — "hum aapke 8 logon se feedback lenge:
# 2 superiors, 2 peers, 2 other departments, aur 2 direct reports".
# ─────────────────────────────────────────────────────────────
REL_SUPERIOR     = "superior"
REL_PEER         = "peer"              # peer of the same department
REL_OTHER_DEPT   = "other_department"  # peer of another department
REL_DIRECT_REPORT = "direct_report"    # junior

RELATIONS: List[str] = [REL_SUPERIOR, REL_PEER, REL_OTHER_DEPT, REL_DIRECT_REPORT]

RELATION_LABELS: Dict[str, str] = {
    REL_SUPERIOR: "Supervisor",
    REL_PEER: "Peer (same department)",
    REL_OTHER_DEPT: "Peer (other department)",
    REL_DIRECT_REPORT: "Junior / Direct report",
}

# The document's recommended panel: 2 of each relation = 8 givers.
RECOMMENDED_PER_RELATION = 2
RECOMMENDED_PANEL_SIZE = RECOMMENDED_PER_RELATION * len(RELATIONS)

# 180° collects from superiors and same-department peers; 360° from everyone.
# ("The feedback may be 180 degree or 360 degree.")
DEGREE_180 = "180"
DEGREE_360 = "360"
DEGREES: List[str] = [DEGREE_180, DEGREE_360]

DEGREE_RELATIONS: Dict[str, List[str]] = {
    DEGREE_180: [REL_SUPERIOR, REL_PEER],
    DEGREE_360: list(RELATIONS),
}


# ─────────────────────────────────────────────────────────────
# Cycle lifecycle
# ─────────────────────────────────────────────────────────────
CYCLE_DRAFT  = "draft"    # being set up; no links issued
CYCLE_OPEN   = "open"     # links issued, feedback being collected
CYCLE_CLOSED = "closed"   # scores frozen into COLL_LS_SCORES

CYCLE_STATUSES: List[str] = [CYCLE_DRAFT, CYCLE_OPEN, CYCLE_CLOSED]

# Assignment (link) lifecycle — mirrors the vocabulary of tpms_form_link_service so the
# admin log reads identically, without sharing its storage.
# A link exists but has NOT been mailed yet. Rows used to be created as "sent", so a link
# that was minted and never delivered still read as Sent in the admin log. The real send is
# what promotes pending -> sent.
LINK_PENDING   = "pending"
LINK_SENT      = "sent"
LINK_OPENED    = "opened"
LINK_SUBMITTED = "submitted"
LINK_EXPIRED   = "expired"      # derived from the cycle window, never written

EMAIL_PENDING = "pending"
EMAIL_SENT    = "sent"
EMAIL_FAILED  = "failed"

# How long after a successful send the same pending invitation is left alone.
#
# "Mail All Pending" is a chase button, so its natural use is to press it again a few days
# later — but nothing stopped it being pressed three times in a minute, which mailed every
# outstanding giver three times. A cooldown makes the button safe to re-press without
# making it useless: anyone mailed longer ago than this is still chased on the next click.
# A never-sent or previously-FAILED invitation is never held back.
RESEND_COOLDOWN_HOURS = 24

# ─────────────────────────────────────────────────────────────
# Invitation email template
#
# Stored in the EXISTING `tpms_mail_templates` collection, so Leadership reuses the mail
# system the rest of TPMS already uses instead of growing a second one. The collection is
# keyed (activity, side, event) and this triple is new on all three counts, so it cannot
# collide with — or be picked up by — any template that exists today:
#
#   activity  "Leadership Score"   not in ACTIVITY_SEED; no scheduled activity uses it
#   side      "company"            givers are company-side people
#   event     "leadership_invite"  a brand-new event kind, used by nothing else
#
# `get_template()` falls back to the "*" catch-all only within the SAME event, so an
# existing "*" row for schedule/reminder events can never be served as a leadership
# invitation either.
# ─────────────────────────────────────────────────────────────
TEMPLATE_ACTIVITY = "Leadership Score"
TEMPLATE_SIDE     = "company"
TEMPLATE_EVENT    = "leadership_invite"

# What an author may write in the body or subject. `leadership_link` is the important one:
# it is replaced PER RECIPIENT with that giver's own /lf/<token> URL at dispatch time, so a
# single stored template produces a different, personal mail for each of the 8 givers.
TEMPLATE_PLACEHOLDERS: List[dict] = [
    {"key": "leadership_link",     "desc": "This giver's own, single-use feedback link"},
    {"key": "giver_name",          "desc": "Name of the person being asked for feedback"},
    {"key": "subject_name",        "desc": "The leader being rated"},
    {"key": "subject_designation", "desc": "That leader's designation"},
    {"key": "level_label",         "desc": "The leader's level, e.g. 'L-5 (Manager)'"},
    {"key": "cycle_label",         "desc": "The feedback window, e.g. 'May-Jun 2026'"},
    {"key": "company_name",        "desc": "Company name"},
    {"key": "expires_on",          "desc": "Date the link stops working (YYYY-MM-DD)"},
]

DEFAULT_TEMPLATE_SUBJECT = "Leadership Feedback - {{subject_name}} ({{cycle_label}})"

# The body used when no template has been authored yet. Identical in content to what the
# module sent before templating, so behaviour is unchanged out of the box.
DEFAULT_TEMPLATE_BODY = (
    '<div style="font-family:Arial,sans-serif;font-size:14px;color:#1e293b;max-width:600px">'
    '<p>Hello {{giver_name}},</p>'
    '<p>You have been requested to give leadership feedback for '
    '<b>{{subject_name}}</b> for the cycle <b>{{cycle_label}}</b>.</p>'
    '<p>The form takes a few minutes. Your responses are <b>completely confidential</b> - '
    'the leader receives only a combined score and never sees who gave which rating.</p>'
    '<p><a href="{{leadership_link}}" style="display:inline-block;background:#4f46e5;'
    'color:#fff;padding:10px 18px;border-radius:8px;text-decoration:none;font-weight:700">'
    'Give your feedback</a></p>'
    '<p style="font-size:12px;color:#6b7280">{{leadership_link}}</p>'
    '<p style="font-size:12px;color:#6b7280">This link is personal to you and can be '
    'submitted once. It stops working after {{expires_on}}.</p></div>'
)


# Rating ceiling. The document scores every option 1, 2, 4 or 5 on a 1-5 scale.
SCALE_MIN = 1
SCALE_MAX = 5

# The weightage column must total this per level, exactly.
TOTAL_WEIGHTAGE = 100.0
WEIGHTAGE_EPSILON = 0.01


# ─────────────────────────────────────────────────────────────
# Cycle helpers — a Leadership cycle spans TWO calendar months.
#
# `cycle` is the canonical key ("2026-C3" = the 3rd two-month window of 2026,
# i.e. May-June). `period` carries the cycle's CLOSING month as "YYYY-MM" so the
# familiar TPMS period vocabulary still identifies a cycle in logs and filters.
# ─────────────────────────────────────────────────────────────
_MONTH_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
               "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def cycle_code(year: int, start_month: int) -> str:
    """(2026, 5) → '2026-C3'. Windows are Jan-Feb, Mar-Apr, … Nov-Dec."""
    return f"{year:04d}-C{((int(start_month) - 1) // 2) + 1}"


def cycle_months(cycle: str) -> tuple:
    """'2026-C3' → (2026, 5, 6) — year, first month, second month."""
    year_s, _, idx_s = str(cycle or "").partition("-C")
    year, idx = int(year_s), int(idx_s)
    if idx < 1 or idx > 6:
        raise ValueError(f"Invalid cycle '{cycle}'")
    first = (idx - 1) * 2 + 1
    return year, first, first + 1


def cycle_label(cycle: str) -> str:
    """'2026-C3' → 'May–Jun 2026'."""
    try:
        year, first, second = cycle_months(cycle)
    except (ValueError, TypeError):
        return str(cycle or "")
    return f"{_MONTH_ABBR[first - 1]}–{_MONTH_ABBR[second - 1]} {year}"


def cycle_period(cycle: str) -> str:
    """The cycle's CLOSING month as 'YYYY-MM' — '2026-C3' → '2026-06'."""
    year, _, second = cycle_months(cycle)
    return f"{year:04d}-{second:02d}"


def current_cycle(now: Optional[datetime] = None) -> str:
    now = now or datetime.utcnow()
    return cycle_code(now.year, now.month)


def recent_cycles(count: int = 6, now: Optional[datetime] = None) -> List[str]:
    """The current cycle and the ones before it, newest first."""
    now = now or datetime.utcnow()
    year, first, _ = cycle_months(current_cycle(now))
    out = []
    for _ in range(max(1, count)):
        out.append(cycle_code(year, first))
        first -= 2
        if first < 1:
            first, year = 11, year - 1
    return out


# ─────────────────────────────────────────────────────────────
# Question master seed — VERBATIM from the source document.
#
# Every option carries the exact score printed in the document. The set {1, 2, 4, 5}
# is intentional: the source awards no 3 anywhere.
#
# `weightage` is NOT specified anywhere in the document — it only states that
# "All parameters should have weightages to create scoring - HR and MD". The seed
# therefore distributes weight EQUALLY across a level's questions (summing to exactly
# 100), which is a neutral starting point, and HR/MD set the real values through
# PUT /api/leadership/questions/weightages. No weightage is invented per question.
# ─────────────────────────────────────────────────────────────
def _opts(*pairs) -> List[dict]:
    """(('A', 'text', 1), …) → option rows."""
    return [{"option_id": oid, "label": label, "score": score} for oid, label, score in pairs]


LEADERSHIP_QUESTION_SEED: Dict[str, List[dict]] = {
    # ── L-4 (Asst. Manager) — Self-Management + Managing Other ──
    LEVEL_L4: [
        {
            "item_id": "L4Q1",
            "title": "Managing himself/herself",
            "prompt": "How does he/she manage himself?",
            "options": _opts(
                ("A", "Need frequent reminder, priorities change daily.", 1),
                ("B", "Manages own work but struggles under pressure.", 2),
                ("C", "Plan work, meets commitments, handles pressure well.", 4),
                ("D", "Fully delf-driven, anticipates issues before they arise.", 5),
            ),
        },
        {
            "item_id": "L4Q2",
            "title": "Managing others",
            "prompt": "How do you rate him/her towards managing others?",
            "options": _opts(
                ("A", "Avoids correcting team; issues escalate.", 1),
                ("B", "Gives instructions but follow-up is inconsistent.", 2),
                ("C", "Regular follow-up; team usually completes work.", 4),
                ("D", "Team performs well even in leader's absence.", 5),
            ),
        },
        {
            "item_id": "L4Q3",
            "title": "Getting things done",
            "prompt": "How do you rate him/her towards getting things done?",
            "options": _opts(
                ("A", "Tasks often spill over deadlines.", 1),
                ("B", "Deadlines met only with intervention.", 2),
                ("C", "Work gets completed as planned.", 4),
                ("D", "Work completes early bottlenecks resolved proactively.", 5),
            ),
        },
        {
            "item_id": "L4Q4",
            "title": "Communication skill",
            "prompt": "How do you rate him/her communication skill?",
            "options": _opts(
                ("A", "Instructions are unclear or incomplete.", 1),
                ("B", "Communicates but assumptions remain.", 2),
                ("C", "Clear instructions with expected outcomes.", 4),
                ("D", "Communication prevents rework and confusion entirely.", 5),
            ),
        },
        {
            "item_id": "L4Q5",
            "title": "Making team accountable",
            "prompt": "How do you rate him/her towards making team accountable?",
            "options": _opts(
                # Source option A is printed truncated ("Loses accountability under scale").
                # Preserved verbatim — see the reported issue list.
                ("A", "Loses accountability under scale", 1),
                ("B", "Accountability exists only through constant intervention", 2),
                ("C", "Accountability is structured across teams/projects", 4),
                ("D", "Accountable for Teams self-track", 5),
            ),
        },
    ],

    # ── L-5 (Manager) ──
    LEVEL_L5: [
        {
            "item_id": "L5Q1",
            "title": "Managing self and other managers",
            "prompt": "How do you rate him/her towards managing self and other managers?",
            "options": _opts(
                ("A", "Manages self but struggles to manage team.", 1),
                ("B", "Manages team but firefighting is common.", 2),
                ("C", "Balances self, team, and deliverables well.", 4),
                ("D", "Team operates smoothly with minimal escalation.", 5),
            ),
        },
        {
            "item_id": "L5Q2",
            "title": "Getting things done",
            "prompt": "How do you rate him/her towards getting things done?",
            "options": _opts(
                ("A", "Delegates tasks but redoes work later.", 1),
                ("B", "Delegates but follow-up is weak.", 2),
                ("C", "Delegates with clarity and accountability.", 4),
                ("D", "Delegation builds ownership and capability.", 5),
            ),
        },
        {
            # NOTE: in the source this question's heading asks about communication skill
            # while its options describe priority-setting. Preserved exactly as printed.
            "item_id": "L5Q3",
            "title": "Communication skill",
            "prompt": "How do you rate his/her communication skill?",
            "options": _opts(
                ("A", "Everything feels urgent.", 1),
                ("B", "Priorities change frequently.", 2),
                ("C", "Clear priorities aligned to goals.", 4),
                ("D", "Priorities are clear, stable, and well-communicated.", 5),
            ),
        },
        {
            # NOTE: heading asks about team accountability while the options describe
            # communication. Preserved exactly as printed.
            "item_id": "L5Q4",
            "title": "Making the team accountable",
            "prompt": "How do you rate his/her skill towards making the team accountable?",
            "options": _opts(
                ("A", "Causes confusion or mixed messages.", 1),
                ("B", "Adequate but reactive communication.", 2),
                ("C", "Clear, timely, and structured communication.", 4),
                ("D", "Communication aligns teams and prevents issues.", 5),
            ),
        },
        {
            # NOTE: heading asks about setting priorities while the options describe
            # accountability. Preserved exactly as printed.
            "item_id": "L5Q5",
            "title": "Setting priorities",
            "prompt": "How does he set priorities? Rate him on a 1–5 scale.",
            "options": _opts(
                ("A", "Avoids tough conversations.", 1),
                ("B", "Accountability only after escalation.", 2),
                ("C", "Regular review and correction.", 4),
                ("D", "Accountability culture exists within the team.", 5),
            ),
        },
    ],

    # ── L-6 (Senior Manager) — Managers' productivity, measurement, innovation ──
    LEVEL_L6: [
        {
            "item_id": "L6Q1",
            "title": "Making managers / team productive",
            "prompt": "How is he Making Manager or Team Productive? Please rate.",
            "options": _opts(
                ("A", "Productivity depends on individuals.", 1),
                ("B", "Some teams perform, some don't.", 2),
                ("C", "Most teams perform consistently.", 4),
                ("D", "Systems drive productivity across teams.", 5),
            ),
        },
        {
            "item_id": "L6Q2",
            "title": "Self accountability",
            "prompt": "How do you rate him towards his self accountability?",
            "options": _opts(
                ("A", "Deflects responsibility", 1),
                ("B", "Accepts responsibility when pushed", 2),
                ("C", "Owns outcomes openly", 4),
                ("D", "Sets accountability standards for others", 5),
            ),
        },
        {
            "item_id": "L6Q3",
            "title": "Delegation",
            "prompt": "How do you rate him towards delegation, means whether his team is able to complete the delegation?",
            "options": _opts(
                ("A", "Micromanages managers", 1),
                ("B", "Delegates but interferes often", 2),
                ("C", "Delegates with trust and checkpoints", 4),
                ("D", "Builds leaders who independently deliver", 5),
            ),
        },
        {
            "item_id": "L6Q4",
            "title": "Measuring progress and counselling",
            "prompt": "Rate him towards Measuring the Progress of team members and subsequent counselling?",
            "options": _opts(
                ("A", "Reviews are irregular or absent", 1),
                ("B", "Reviews focus on problems only", 2),
                ("C", "Reviews track progress and corrective actions", 4),
                ("D", "Reviews lead to visible performance improvement", 5),
            ),
        },
        {
            "item_id": "L6Q5",
            "title": "Inspiring the team to achieve results",
            "prompt": "Rate him towards the methods he/she use to inspire the team to achieve results?",
            "options": _opts(
                ("A", "Repeats old methods.", 1),
                ("B", "Minor process improvements.", 2),
                ("C", "Improves workflows for efficiency.", 4),
                ("D", "Redesigns jobs to improve outcomes.", 5),
            ),
        },
        {
            "item_id": "L6Q6",
            "title": "Job design / innovation skills",
            "prompt": "Rate him towards designing the job to ensure result achievement (Rate his innovation skills)?",
            "options": _opts(
                ("a", "Job design is task-based and rigid", 1),
                ("b", "Minor improvements, but structure limits results", 2),
                ("c", "Job design supports consistent result delivery", 4),
                ("d", "Job design enables scalable and predictable results", 5),
            ),
        },
    ],

    # ── L7 & ABOVE — Strategy, business acumen, alignment ──
    LEVEL_L7: [
        {
            # NOTE: heading asks about measuring progress/counselling while the options
            # describe team structure. Preserved exactly as printed.
            "item_id": "L7Q1",
            "title": "Measuring progress and counselling",
            "prompt": "Rate him towards measuring the progress of team member and subsequent counselling?",
            "options": _opts(
                ("A", "Team depends heavily on leader", 1),
                ("B", "Some strong individuals, weak structure", 2),
                ("C", "Structured teams with clear roles", 4),
                ("D", "Self-driven leadership teams exist", 5),
            ),
        },
        {
            # NOTE: heading asks about building a strong team while the options describe
            # business impact. Preserved exactly as printed.
            "item_id": "L7Q2",
            "title": "Building a strong team",
            "prompt": "How rate him towards building a strong team?",
            "options": _opts(
                ("A", "Limited understanding of business impact", 1),
                ("B", "Understands own function only", 2),
                ("C", "Understands cross-functional business impact", 4),
                ("D", "Drives decisions based on business outcomes", 5),
            ),
        },
        {
            "item_id": "L7Q3",
            "title": "Business acumen",
            "prompt": "How do you rate his/her business acumen?",
            "options": _opts(
                ("A", "Avoids financial discussions", 1),
                ("B", "Understands budgets but not drivers", 2),
                ("C", "Understands cost, margins, profitability", 4),
                ("D", "Uses finance to drive strategy", 5),
            ),
        },
        {
            # NOTE: heading asks about business finance understanding while the options
            # describe managing scale. Preserved exactly as printed.
            "item_id": "L7Q4",
            "title": "Business finance understanding",
            "prompt": "How do you rate his/her business finance understanding?",
            "options": _opts(
                ("A", "Loses control under scale", 1),
                ("B", "Manages with stress and firefighting", 2),
                ("C", "Structured control across teams/projects", 4),
                ("D", "Scale handled through systems and leaders", 5),
            ),
        },
        {
            # NOTE: heading asks about managing multiple projects while the options
            # describe strategy. Preserved exactly as printed.
            "item_id": "L7Q5",
            "title": "Managing multiple / diversified projects",
            "prompt": "How do you rate him towards managing multiple project/diversified?",
            "options": _opts(
                ("A", "Strategy unclear to teams", 1),
                ("B", "Strategy exists but execution weak", 2),
                ("C", "Strategy understood and mostly executed", 4),
                ("D", "Strategy translates into measurable results", 5),
            ),
        },
        {
            # NOTE: the source prints these four option scores in an order that rewards
            # the weaker statements (option "a" = 1, option "c" = 4). Preserved EXACTLY as
            # printed — this is the single most important reported issue to confirm.
            "item_id": "L7Q6",
            "title": "Goal alignment and strategy execution",
            "prompt": "How do you rate him towards goal alignment and strategy execution?",
            "options": _opts(
                ("a", "Goals are aligned and largely executed", 1),
                ("b", "Goals are embedded and strategy drives action", 2),
                ("c", "Goals are unclear and execution is inconsistent", 4),
                ("d", "Goals are communicated, execution is uneven", 5),
            ),
        },
    ],
}


def seed_rows_for_level(level: str) -> List[dict]:
    """Question-master rows for one level, with weight distributed equally to total 100.

    The remainder is spread over the first questions so the column sums to exactly
    100.00 rather than 99.98 or 100.02 — the validator rejects anything else.
    """
    questions = LEADERSHIP_QUESTION_SEED.get(level) or []
    n = len(questions)
    if not n:
        return []
    base = round(TOTAL_WEIGHTAGE / n, 2)
    weights = [base] * n
    drift = round(TOTAL_WEIGHTAGE - sum(weights), 2)
    steps = int(round(abs(drift) * 100))
    step = 0.01 if drift > 0 else -0.01
    for i in range(steps):
        weights[i % n] = round(weights[i % n] + step, 2)

    return [{
        "level": level,
        "item_id": q["item_id"],
        "title": q["title"],
        "prompt": q["prompt"],
        "options": [dict(o) for o in q["options"]],
        "weightage": weights[i],
        "order": i,
        "active": True,
    } for i, q in enumerate(questions)]


def all_seed_rows() -> List[dict]:
    rows = []
    for level in LEVELS:
        rows.extend(seed_rows_for_level(level))
    return rows


# ─────────────────────────────────────────────────────────────
# Request payloads
# ─────────────────────────────────────────────────────────────
class CycleCreate(BaseModel):
    company_id: Optional[str] = None
    cycle: Optional[str] = None                 # defaults to the current 2-month window
    degree: str = DEGREE_360
    # How many responses a subject needs before a score is shown. The document does not
    # define a threshold, so the default of 1 imposes none; HR may raise it per cycle to
    # strengthen anonymity.
    min_responses: int = 1
    notes: Optional[str] = ""

    @field_validator("degree")
    @classmethod
    def _known_degree(cls, v: str) -> str:
        d = str(v or "").strip()
        if d not in DEGREES:
            raise ValueError(f"degree must be one of {', '.join(DEGREES)}")
        return d

    @field_validator("min_responses")
    @classmethod
    def _sane_threshold(cls, v: int) -> int:
        n = int(v or 1)
        if n < 1 or n > RECOMMENDED_PANEL_SIZE:
            raise ValueError(f"min_responses must be between 1 and {RECOMMENDED_PANEL_SIZE}")
        return n


class CycleUpdate(BaseModel):
    degree: Optional[str] = None
    min_responses: Optional[int] = None
    status: Optional[str] = None
    notes: Optional[str] = None

    @field_validator("degree")
    @classmethod
    def _known_degree(cls, v):
        if v is None:
            return v
        if str(v) not in DEGREES:
            raise ValueError(f"degree must be one of {', '.join(DEGREES)}")
        return str(v)

    @field_validator("status")
    @classmethod
    def _known_status(cls, v):
        if v is None:
            return v
        if str(v) not in CYCLE_STATUSES:
            raise ValueError(f"status must be one of {', '.join(CYCLE_STATUSES)}")
        return str(v)


class SubjectCreate(BaseModel):
    """Enrol one leader into a cycle at a level."""
    subject_id: str
    level: str

    @field_validator("subject_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("subject_id is required")
        return s

    @field_validator("level")
    @classmethod
    def _known_level(cls, v: str) -> str:
        lv = str(v or "").strip().upper()
        if lv not in LEVELS:
            raise ValueError(f"level must be one of {', '.join(LEVELS)}")
        return lv


class GiverItem(BaseModel):
    giver_id: str
    relation: str

    @field_validator("giver_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("giver_id is required")
        return s

    @field_validator("relation")
    @classmethod
    def _known_relation(cls, v: str) -> str:
        r = str(v or "").strip().lower()
        if r not in RELATIONS:
            raise ValueError(f"relation must be one of {', '.join(RELATIONS)}")
        return r


class GiverAssignment(BaseModel):
    """The feedback panel for one subject. Identified by HR and known only to HR."""
    givers: List[GiverItem]

    @field_validator("givers")
    @classmethod
    def _no_duplicates(cls, items: List[GiverItem]) -> List[GiverItem]:
        ids = [i.giver_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("The same person cannot be added to a panel twice")
        return items


class AnswerItem(BaseModel):
    question_id: str
    option_id: str

    @field_validator("question_id", "option_id")
    @classmethod
    def _required(cls, v: str) -> str:
        s = str(v or "").strip()
        if not s:
            raise ValueError("question_id and option_id are required")
        return s


class ResponseSubmit(BaseModel):
    answers: List[AnswerItem]

    @field_validator("answers")
    @classmethod
    def _non_empty(cls, v: List[AnswerItem]) -> List[AnswerItem]:
        if not v:
            raise ValueError("At least one answer is required")
        return v


class QuestionUpdate(BaseModel):
    """Reword a question or restate its options. `item_id` and `level` are immutable —
    they key the stored responses."""
    title: Optional[str] = None
    prompt: Optional[str] = None
    options: Optional[List[dict]] = None
    active: Optional[bool] = None

    @field_validator("options")
    @classmethod
    def _valid_options(cls, v):
        if v is None:
            return v
        if not v:
            raise ValueError("A question needs at least one option")
        seen = set()
        for o in v:
            oid = str((o or {}).get("option_id") or "").strip()
            if not oid:
                raise ValueError("Every option needs an option_id")
            if oid in seen:
                raise ValueError(f"Duplicate option_id '{oid}'")
            seen.add(oid)
            try:
                score = float((o or {}).get("score"))
            except (TypeError, ValueError):
                raise ValueError(f"Option '{oid}' needs a numeric score")
            if score < SCALE_MIN or score > SCALE_MAX:
                raise ValueError(f"Option '{oid}' score must be between {SCALE_MIN} and {SCALE_MAX}")
        return v


class WeightageItem(BaseModel):
    item_id: str
    weightage: float

    @field_validator("weightage")
    @classmethod
    def _in_range(cls, v: float) -> float:
        w = round(float(v), 2)
        if w < 0 or w > TOTAL_WEIGHTAGE:
            raise ValueError(f"weightage must be between 0 and {TOTAL_WEIGHTAGE:g}")
        return w


class WeightageUpdate(BaseModel):
    """Set a level's weightage column. It must total exactly 100 — a partially
    configured level would otherwise produce a plausible-looking wrong score."""
    level: str
    weightages: List[WeightageItem]

    @field_validator("level")
    @classmethod
    def _known_level(cls, v: str) -> str:
        lv = str(v or "").strip().upper()
        if lv not in LEVELS:
            raise ValueError(f"level must be one of {', '.join(LEVELS)}")
        return lv

    @field_validator("weightages")
    @classmethod
    def _totals_100(cls, items: List[WeightageItem]) -> List[WeightageItem]:
        if not items:
            raise ValueError("No weightages supplied")
        ids = [i.item_id for i in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Each question may appear only once")
        total = round(sum(i.weightage for i in items), 2)
        if abs(total - TOTAL_WEIGHTAGE) > WEIGHTAGE_EPSILON:
            raise ValueError(
                f"Total weightage must be exactly {TOTAL_WEIGHTAGE:g}% (currently {total:g}%)"
            )
        return items


# ─────────────────────────────────────────────────────────────
# Index specification — consumed by app/db/mongodb.py at startup.
# Every collection here is new, so no existing index is touched.
# ─────────────────────────────────────────────────────────────
LEADERSHIP_INDEXES = [
    (COLL_LS_CYCLES,      [("company_id", 1), ("cycle", 1)],
     {"unique": True, "name": "uniq_company_cycle"}),
    (COLL_LS_SUBJECTS,    [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"unique": True, "name": "uniq_company_cycle_subject"}),
    (COLL_LS_SUBJECTS,    [("company_id", 1), ("cycle", 1)],
     {"name": "by_company_cycle"}),
    (COLL_LS_ASSIGNMENTS, [("company_id", 1), ("cycle", 1), ("subject_id", 1), ("giver_id", 1)],
     {"unique": True, "name": "uniq_cycle_subject_giver"}),
    (COLL_LS_ASSIGNMENTS, [("token", 1)],
     {"unique": True, "name": "uniq_token"}),
    (COLL_LS_ASSIGNMENTS, [("company_id", 1), ("cycle", 1)],
     {"name": "by_company_cycle"}),
    (COLL_LS_RESPONSES,   [("company_id", 1), ("cycle", 1), ("subject_id", 1), ("giver_id", 1)],
     {"unique": True, "name": "uniq_cycle_subject_giver"}),
    (COLL_LS_RESPONSES,   [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"name": "by_subject"}),
    (COLL_LS_QUESTIONS,   [("level", 1), ("item_id", 1)],
     {"unique": True, "name": "uniq_level_item"}),
    (COLL_LS_QUESTIONS,   [("level", 1), ("order", 1)],
     {"name": "by_level_order"}),
    (COLL_LS_SCORES,      [("company_id", 1), ("cycle", 1), ("subject_id", 1)],
     {"unique": True, "name": "uniq_company_cycle_subject"}),
]
