"""Payroll rule engine — pure functions, no I/O.

Every rule that carries a number, time or amount lives in PayrollConfig so the engine below
contains *logic only*. Change a policy by editing the config (which is stored in
`system_settings` and editable from the UI); the engine picks it up with no other edits.

Times are minutes since local midnight, so comparisons are integer maths with no timezone in
play. Money is in rupees.

Ported from the reference project's rule set, with its documented behaviours preserved. Two
things it gets wrong are NOT ported:
  * its payroll persists nothing and recomputes differently each call — here a run is stored;
  * its GET mutates the leave ledger — nothing here writes anything at all.
"""
from dataclasses import dataclass, field, asdict
from datetime import date, timedelta
from typing import List, Optional, Set

# ─── Configuration ──────────────────────────────────────────────────────────────


def hm(hours: int, minutes: int) -> int:
    """'HH:MM' as minutes since midnight."""
    return hours * 60 + minutes


@dataclass
class PayrollConfig:
    # Days the monthly salary is spread over.
    #   0  → use the month's ACTUAL day count (Feb pays monthly/28, July /31)
    #   >0 → fixed base, daily = monthly / N
    salary_base_days: int = 0

    shift_start: int = hm(9, 0)
    shift_end: int = hm(17, 0)
    working_hours_per_day: int = 8

    # Late entry. Both rules stack: past the first threshold a flat fine, past the second an
    # hour of salary as well.
    late_flat_fine_after: int = hm(9, 10)
    late_flat_fine_amount: float = 100.0
    late_hour_penalty_after: int = hm(9, 15)
    late_hour_penalty_hours: float = 1.0

    # Overtime accrues from shift end and pays only in COMPLETED hours — a part hour earns
    # nothing (17:45 → 0h, 18:00 → 1h, 18:30 → 1h, 19:00 → 2h).
    ot_eligible_from: int = hm(17, 0)
    ot_min_minutes: int = 60
    ot_multiplier: float = 1.0

    # Penalties, in DAYS of salary.
    unauthorized_leave_penalty_days: float = 2.0

    paid_leaves_per_year: float = 2.0

    # Above this many leave days in a month, every Sunday that month is unpaid.
    max_monthly_leaves_before_sunday_loss: float = 15.0

    professional_tax: float = 200.0

    def to_dict(self) -> dict:
        return asdict(self)


DEFAULT_CONFIG = PayrollConfig()


# ─── Input records ──────────────────────────────────────────────────────────────
@dataclass
class PunchSegment:
    start: int                     # minutes since midnight
    end: Optional[int] = None      # None while still punched in


@dataclass
class DayRecord:
    date: str                      # "YYYY-MM-DD"
    weekday: int                   # Python weekday(): Mon=0 … Sun=6
    segments: List[PunchSegment] = field(default_factory=list)


# Leave kinds the engine understands. A leave's KIND is supplied by the adapter from the leave
# type's own flags — the engine never inspects a type's name.
LEAVE_PAID = "paid"
LEAVE_UNPAID = "unpaid"
LEAVE_UNAUTHORIZED = "unauthorized"
LEAVE_REJECTED = "rejected"


@dataclass
class LeaveDay:
    date: str
    kind: str
    half: bool = False


@dataclass
class EmployeeMonth:
    year: int
    month: int
    days_in_month: int
    monthly_salary: float
    days: List[DayRecord] = field(default_factory=list)
    leaves: List[LeaveDay] = field(default_factory=list)
    holidays: List[str] = field(default_factory=list)      # "YYYY-MM-DD" in this month
    paid_leave_balance: float = 0.0
    joined_on_day: Optional[int] = None
    left_on_day: Optional[int] = None


# ─── Small helpers ──────────────────────────────────────────────────────────────
def round2(n: float) -> float:
    return round(n + 0.0, 2)


def add_days(iso: str, n: int) -> str:
    y, m, d = (int(p) for p in iso.split("-"))
    return (date(y, m, d) + timedelta(days=n)).isoformat()


def is_sunday(iso: str) -> bool:
    y, m, d = (int(p) for p in iso.split("-"))
    return date(y, m, d).weekday() == 6


# ─── Attendance rules ───────────────────────────────────────────────────────────
def worked_minutes(segments: List[PunchSegment]) -> int:
    """Total worked minutes. An `end` at or before `start` means the shift crossed midnight, so
    it wraps to the next day rather than being discarded (22:00→02:00 = 240 min, not 0)."""
    total = 0
    for s in segments:
        if s.end is None:
            continue        # still punched in — nothing to settle yet
        total += s.end - s.start if s.end > s.start else s.end + 1440 - s.start
    return total


def first_in(segments: List[PunchSegment]) -> Optional[int]:
    starts = [s.start for s in segments]
    return min(starts) if starts else None


def last_out(segments: List[PunchSegment]) -> Optional[int]:
    """Latest punch-out. A wrapped out is expressed as ≥1440 so it still compares as later than
    the shift end (02:00 after a 22:00 in → 1560, not 120)."""
    outs = [s.end if s.end > s.start else s.end + 1440 for s in segments if s.end is not None]
    return max(outs) if outs else None


def late_entry(in_minute: Optional[int], cfg: PayrollConfig) -> dict:
    """Both thresholds stack: past the first a flat fine, past the second an hour as well."""
    if in_minute is None:
        return {"flat_fine": 0.0, "penalty_hours": 0.0}
    return {
        "flat_fine": cfg.late_flat_fine_amount if in_minute > cfg.late_flat_fine_after else 0.0,
        "penalty_hours": (cfg.late_hour_penalty_hours
                          if in_minute > cfg.late_hour_penalty_after else 0.0),
    }


def _completed_hours(minutes: int, cfg: PayrollConfig) -> int:
    """Whole finished hours; anything under one full hour pays nothing."""
    if minutes < cfg.ot_min_minutes:
        return 0
    return minutes // 60


def overtime_hours(day: DayRecord, cfg: PayrollConfig, sunday: bool) -> int:
    """Completed overtime hours for one day.

    Weekday: only the tail past shift end, measured by the day's LAST punch-out — using last-out
    keeps a stray extra punch from inventing overtime, and gaps between punches are unpaid
    breaks, never OT.
    Sunday: the whole day is overtime, on actual minutes worked.
    """
    total = worked_minutes(day.segments)
    if total <= 0:
        return 0
    if sunday:
        return _completed_hours(total, cfg)
    out = last_out(day.segments)
    if out is None:
        return 0
    return _completed_hours(out - cfg.ot_eligible_from, cfg)


# ─── Leave rules ────────────────────────────────────────────────────────────────
def tally_leaves(leaves: List[LeaveDay], paid_leave_balance: float) -> dict:
    """Sort the month's leave into pay buckets. Half days count 0.5.

    Paid leave draws down the annual allowance; days past it become unpaid, so the yearly cap is
    enforced rather than granting unlimited paid leave.
    """
    t = {"paid": 0.0, "unpaid": 0.0, "unauthorized": 0.0, "total": 0.0, "paid_overflow": 0.0}
    remaining = max(0.0, paid_leave_balance)

    for leave in leaves:
        w = 0.5 if leave.half else 1.0
        if leave.kind == LEAVE_PAID:
            covered = min(w, remaining)
            remaining -= covered
            t["paid"] += covered
            overflow = w - covered
            if overflow > 0:
                t["unpaid"] += overflow
                t["paid_overflow"] += overflow
        elif leave.kind == LEAVE_UNPAID:
            t["unpaid"] += w
        elif leave.kind in (LEAVE_UNAUTHORIZED, LEAVE_REJECTED):
            t["unauthorized"] += w
        t["total"] += w
    return t


def sandwiched_sundays(sundays: List[str], leave_dates: Set[str]) -> Set[str]:
    """Sundays that become unpaid because they are flanked by leave.

    Rule A: leave on the adjacent Saturday AND the adjacent Monday.
    Rule B: two continuous leave days immediately before, or immediately after.
    """
    out = set()
    for sun in sundays:
        if add_days(sun, -1) in leave_dates and add_days(sun, 1) in leave_dates:
            out.add(sun)
            continue
        two_before = add_days(sun, -1) in leave_dates and add_days(sun, -2) in leave_dates
        two_after = add_days(sun, 1) in leave_dates and add_days(sun, 2) in leave_dates
        if two_before or two_after:
            out.add(sun)
    return out


def sunday_eligibility(sundays: List[str], unpaid_by_sandwich: Set[str],
                       total_leave_days: float, cfg: PayrollConfig,
                       resigned_on_day: Optional[int]) -> dict:
    """A Sunday is a paid weekly off unless it was sandwiched by leave, the month exceeded the
    leave ceiling, or the employee resigned mid-month."""
    all_unpaid = total_leave_days > cfg.max_monthly_leaves_before_sunday_loss
    paid, unpaid = [], []
    for sun in sundays:
        if all_unpaid or sun in unpaid_by_sandwich or resigned_on_day is not None:
            unpaid.append(sun)
        else:
            paid.append(sun)
    return {"paid": paid, "unpaid": unpaid}


def holiday_eligibility(holidays: List[str], resigned_on_day: Optional[int]) -> int:
    """Paid official holidays in the month.

    A holiday landing on a Sunday is not counted — Sunday is already a paid weekly off, so
    counting it again would pay the same day twice. A same-month resignation voids holiday pay.
    """
    if resigned_on_day is not None:
        return 0
    return len([d for d in holidays if not is_sunday(d)])


def employment_window(days_in_month: int, joined_on_day: Optional[int],
                      left_on_day: Optional[int]) -> dict:
    """How much of the month the person was actually on the payroll.

    Someone joining on the 25th of a 31-day month is owed 7/31, not the whole thing. Both bounds
    inclusive, clamped to the month.
    """
    first = min(max(joined_on_day or 1, 1), days_in_month)
    last = min(max(left_on_day or days_in_month, 1), days_in_month)
    payable = max(0, last - first + 1)
    return {"payable_days": payable,
            "fraction": payable / days_in_month if days_in_month else 0.0}


# ─── Engine ─────────────────────────────────────────────────────────────────────
def compute_payroll(emp: EmployeeMonth, cfg: PayrollConfig = DEFAULT_CONFIG) -> dict:
    """One employee, one month. Pure: same input always yields the same output."""
    notes: List[str] = []

    base_days = cfg.salary_base_days or emp.days_in_month
    daily = emp.monthly_salary / base_days if base_days else 0.0
    hourly = daily / cfg.working_hours_per_day if cfg.working_hours_per_day else 0.0

    window = employment_window(emp.days_in_month, emp.joined_on_day, emp.left_on_day)
    payable_days = window["payable_days"]
    earned_salary = round2(emp.monthly_salary * window["fraction"])
    if window["fraction"] < 1:
        notes.append(f"Prorated: {payable_days}/{emp.days_in_month} days on the payroll.")

    # Sundays in the month, derived rather than trusted from input.
    sundays = []
    for d in range(1, emp.days_in_month + 1):
        iso = f"{emp.year:04d}-{emp.month:02d}-{d:02d}"
        if date(emp.year, emp.month, d).weekday() == 6:
            sundays.append(iso)

    working_days = 0
    late_fine = 0.0
    late_hours = 0.0
    ot_hours = 0

    for day in emp.days:
        sunday = day.weekday == 6
        worked = worked_minutes(day.segments)
        if sunday:
            # Sunday work is pure overtime, not normal attendance.
            if worked > 0:
                ot_hours += overtime_hours(day, cfg, True)
            continue
        if worked > 0:
            working_days += 1
            late = late_entry(first_in(day.segments), cfg)
            late_fine += late["flat_fine"]
            late_hours += late["penalty_hours"]
            ot_hours += overtime_hours(day, cfg, False)

    # An unauthorized/rejected leave only costs the penalty if the person was actually ABSENT.
    # Fining someone who turned up and worked would be plainly wrong.
    worked_dates = {d.date for d in emp.days if worked_minutes(d.segments) > 0}
    effective = [l for l in emp.leaves
                 if not (l.kind in (LEAVE_UNAUTHORIZED, LEAVE_REJECTED) and l.date in worked_dates)]
    ignored = len(emp.leaves) - len(effective)
    if ignored:
        notes.append(f"{ignored} rejected/unauthorized leave day(s) ignored — the employee worked.")

    leaves = tally_leaves(effective, emp.paid_leave_balance)
    if leaves["paid_overflow"] > 0:
        notes.append(
            f"Paid-leave allowance exhausted: {round2(leaves['paid_overflow'])} day(s) charged as unpaid.")

    leave_dates = {l.date for l in effective}
    sandwich = sandwiched_sundays(sundays, leave_dates)
    if sandwich:
        notes.append(f"Sandwich rule: {len(sandwich)} Sunday(s) made unpaid.")
    if leaves["total"] > cfg.max_monthly_leaves_before_sunday_loss:
        notes.append(
            f">{cfg.max_monthly_leaves_before_sunday_loss} leaves: all Sundays unpaid.")

    sun = sunday_eligibility(sundays, sandwich, leaves["total"], cfg, emp.left_on_day)
    paid_holidays = holiday_eligibility(emp.holidays, emp.left_on_day)
    if emp.left_on_day is not None:
        notes.append(
            f"Left on day {emp.left_on_day}: Sundays and holidays unpaid, only worked days payable.")

    # ── Money ──
    unauthorized_penalty = round2(
        leaves["unauthorized"] * cfg.unauthorized_leave_penalty_days * daily)
    late_hour_deduction = round2(late_hours * hourly)
    unpaid_leave_deduction = round2(leaves["unpaid"] * daily)
    unpaid_sunday_deduction = round2(len(sun["unpaid"]) * daily)
    overtime_amount = round2(ot_hours * hourly * cfg.ot_multiplier)

    total_deductions = round2(
        cfg.professional_tax + late_fine + late_hour_deduction
        + unpaid_leave_deduction + unpaid_sunday_deduction + unauthorized_penalty)

    # Paid leave, paid Sundays and paid holidays are already inside the monthly salary — they
    # avoid a deduction rather than adding an earnings line.
    total_earnings = round2(earned_salary + overtime_amount)
    net = round2(max(0.0, total_earnings - total_deductions))

    return {
        "monthlySalary": round2(emp.monthly_salary),
        "earnedSalary": earned_salary,
        "payableDays": payable_days,
        "dailySalary": round2(daily),
        "hourlySalary": round2(hourly),

        "workingDays": working_days,
        "paidLeaves": round2(leaves["paid"]),
        "unpaidLeaves": round2(leaves["unpaid"] + leaves["unauthorized"]),
        "paidLeaveOverflow": round2(leaves["paid_overflow"]),
        "paidLeaveBalanceLeft": round2(max(0.0, emp.paid_leave_balance - leaves["paid"])),

        "paidSundays": len(sun["paid"]),
        "unpaidSundays": len(sun["unpaid"]),
        "paidHolidays": paid_holidays,

        "lateEntryFine": round2(late_fine),
        "lateHourDeduction": late_hour_deduction,
        "unauthorizedLeavePenalty": unauthorized_penalty,
        "professionalTax": round2(cfg.professional_tax),

        "overtimeHours": ot_hours,
        "overtimeAmount": overtime_amount,

        "totalDeductions": total_deductions,
        "totalEarnings": total_earnings,
        "netSalary": net,

        "notes": notes,
    }
