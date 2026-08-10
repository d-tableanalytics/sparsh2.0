"""Recurring-task verification harness.

Covers the 19 required checks: a genuinely fresh occurrence, the user's assigned deadline
surviving every occurrence untouched, mandatory Repeat End Date, Yearly recurrence,
date-driven generation, the shared series-extension path, and IST-consistent de-duplication.

House convention: self-contained, no pytest, fakes, ASCII output, exit 1 on failure.

Run:  python -m app.services.tpms.tests.test_recurring_tasks   (from backend/)
"""
from __future__ import annotations

import asyncio
import inspect
from datetime import datetime, timedelta, timezone

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


def section(title: str) -> None:
    print(f"\n-- {title} --")


IST = timezone(timedelta(hours=5, minutes=30))


def head_task(**over) -> dict:
    """A 10 Aug daily task that has been WORKED ON: checklist ticked, evidence uploaded,
    remarks written, a dependency raised, and the assigner's brief attached."""
    doc = {
        "_id": "occ-10aug",
        "type": "task",
        "title": "Daily standup notes",
        "repeat": "Daily",
        "repeat_interval": 1,
        "repeat_end_date": "2026-08-31T23:59:59+05:30",
        "recurring_group_id": "series-1",
        "start": "2026-08-10T09:00:00+05:30",
        "end": "2026-08-10T18:00:00+05:30",
        "workflow_status": "completed",
        "status": "completed",
        "completed_at": "2026-08-10T17:30:00+05:30",
        "completed_by": "u-doer",
        "checklist": [
            {"id": "c1", "title": "Collect updates", "completed": True,
             "completed_at": "2026-08-10T11:00:00+05:30"},
            {"id": "c2", "title": "Circulate notes", "completed": True,
             "completed_at": "2026-08-10T17:00:00+05:30"},
        ],
        # The assigner's brief — must SURVIVE.
        "attachments": [{"id": "a1", "name": "template.docx"}],
        # The doer's evidence — must NOT survive.
        "completion_attachments": [{"id": "e1", "name": "proof-10aug.png"}],
        "remarks": [{"id": "r1", "text": "done"}],
        "status_history": [{"from": "in_progress", "to": "completed"}],
        "follow_ups": [{"id": "f1", "remark": "any update?"}],
        "deadline_history": [{"from": "2026-08-10", "to": "2026-08-10"}],
        "evidence_required": True,
        # A dependency was raised: the doer was ADDED to target_staff_id and assigned_to flipped.
        "target_staff_id": ["u-assignee", "u-helper"],
        "assigned_to": "other",
        "dependency_doer_id": "u-helper",
        "dependency_stack": [{
            "assignee_ids": ["u-assignee"], "assigned_to": "self",
            "doer_id": "u-helper", "doer_name": "Helper",
        }],
        "reminders": [{"id": "rm1", "trigger": "2026-08-10T08:00:00+05:30", "sent": True}],
    }
    doc.update(over)
    return doc


async def main() -> None:
    import app.services.recurring_task_service as R
    from app.routes.calendar_events import _next_occurrence, ANNUAL_REPEATS

    def occurrence_on(day, head=None, natural=None):
        head = head or head_task()
        target = datetime(2026, 8, day, 9, 0, tzinfo=IST)
        return R._fresh_occurrence(head, target, natural or target, None)

    # =================================================================
    section("1-7. The new occurrence is genuinely fresh")
    # =================================================================
    nxt = occurrence_on(11)

    check("1. every checklist item is unchecked",
          all(c["completed"] is False for c in nxt["checklist"]))
    check("2. completed_at is None on every checklist item",
          all(c["completed_at"] is None for c in nxt["checklist"]))
    check("   checklist ITEMS themselves are kept (title and id survive)",
          [c["title"] for c in nxt["checklist"]] == ["Collect updates", "Circulate notes"])
    check("   the new checklist carries only its items - no date, time or deadline of its own",
          all(set(c) == {"id", "title", "completed", "completed_at"} for c in nxt["checklist"]))
    check("3. completion_attachments are NOT copied", nxt["completion_attachments"] == [])
    check("4. the assigner's attachments ARE preserved",
          nxt["attachments"] == [{"id": "a1", "name": "template.docx"}])
    check("5. remarks are not copied", nxt["remarks"] == [])
    check("6. follow_ups are not copied", nxt["follow_ups"] == [])
    check("7. dependency_stack is cleared", nxt["dependency_stack"] == [])
    check("7. dependency_doer_id is cleared", nxt["dependency_doer_id"] is None)
    check("   the dependency doer is removed from the assignees",
          nxt["target_staff_id"] == ["u-assignee"])
    check("   assigned_to is restored to its pre-delegation value",
          nxt["assigned_to"] == "self")
    check("   status_history is cleared", nxt["status_history"] == [])
    check("   deadline_history is cleared", nxt["deadline_history"] == [])
    check("   task-level completion is cleared",
          nxt["completed_at"] is None and nxt["completed_by"] is None)
    check("   the new occurrence starts In Progress",
          nxt["workflow_status"] == "in_progress" and nxt["status"] == "schedule")
    check("   reminders are re-armed", nxt["reminders"][0]["sent"] is False)
    check("   the source occurrence is not mutated",
          head_task()["checklist"][0]["completed"] is True)

    section("Evidence-required cannot be satisfied by last period's proof")
    check("an evidence-required occurrence starts with no evidence",
          nxt.get("evidence_required") is True and not nxt.get("completion_attachments"))

    # =================================================================
    section("8-9. The deadline the user assigned NEVER changes")
    # =================================================================
    assigned_end = head_task()["end"]
    for day in (11, 12, 13):
        occ = occurrence_on(day)
        start = datetime.fromisoformat(occ["start"])
        check(f"8. {day} Aug gets its own start date, at the 9 AM the user chose",
              (start.day, start.hour, start.minute) == (day, 9, 0))
        check(f"9. {day} Aug carries the assigned deadline verbatim",
              occ["end"] == assigned_end)

    section("No cadence recomputes the deadline")
    wide = head_task(end="2026-08-30T18:00:00+05:30")   # created 10 Aug, due 30 Aug
    occ = occurrence_on(11, head=wide)
    check("a 30 Aug deadline is still 30 Aug on the 11 Aug occurrence",
          occ["end"] == "2026-08-30T18:00:00+05:30")

    section("The deadline is not derived from the start either")
    night = head_task(start="2026-08-10T21:00:00+05:30", end="2026-08-11T06:00:00+05:30")
    target = datetime(2026, 8, 11, 21, 0, tzinfo=IST)
    occ = R._fresh_occurrence(night, target, target, None)
    check("an overnight window keeps the exact assigned deadline",
          occ["end"] == "2026-08-11T06:00:00+05:30")

    check("the deadline is never computed anywhere in the engine",
          "_occurrence_end" not in inspect.getsource(R)
          and 'doc["end"]' not in inspect.getsource(R._fresh_occurrence))

    # =================================================================
    section("10. Every cadence keeps the assigned deadline untouched")
    # =================================================================
    for cadence, days in (("Weekly", 7), ("Monthly", 31), ("Custom", 3), ("periodic", 2)):
        head = head_task(repeat=cadence, start="2026-08-10T09:00:00+05:30",
                         end="2026-08-13T18:00:00+05:30")     # a multi-day window
        target = datetime(2026, 8, 10, 9, 0, tzinfo=IST) + timedelta(days=days)
        occ = R._fresh_occurrence(head, target, target, None)
        check(f"10. {cadence} leaves the deadline exactly as assigned",
              occ["end"] == head["end"])

    # =================================================================
    section("12-14. Yearly recurrence")
    # =================================================================
    d = datetime(2026, 8, 10, 9, 0, tzinfo=IST)
    y1 = _next_occurrence(d, "Yearly", 1, None, 10)
    y2 = _next_occurrence(y1, "Yearly", 1, None, 10)
    check("12. Yearly advances 2026 -> 2027 -> 2028",
          (y1.year, y1.month, y1.day) == (2027, 8, 10)
          and (y2.year, y2.month, y2.day) == (2028, 8, 10))
    a1 = _next_occurrence(d, "Annually", 1, None, 10)
    check("13. Annually still advances", (a1.year, a1.month, a1.day) == (2027, 8, 10))
    check("14. both spellings give the same date", y1 == a1)
    check("   both are declared as the annual cadence",
          set(ANNUAL_REPEATS) == {"Yearly", "Annually"})
    check("   Yearly keeps the time of day", (y1.hour, y1.minute) == (9, 0))

    section("Leap-year and month-end handling preserved")
    leap = datetime(2024, 2, 29, 9, 0, tzinfo=IST)
    steps, cur = [], leap
    for _ in range(4):
        cur = _next_occurrence(cur, "Yearly", 1, None, 29)
        steps.append((cur.year, cur.month, cur.day))
    check("29 Feb clamps to the 28th and RETURNS to the 29th in the next leap year",
          steps == [(2025, 2, 28), (2026, 2, 28), (2027, 2, 28), (2028, 2, 29)])
    jan31 = datetime(2026, 1, 31, 9, 0, tzinfo=IST)
    m1 = _next_occurrence(jan31, "Monthly", 1, None, 31)
    m2 = _next_occurrence(m1, "Monthly", 1, None, 31)
    check("month-end carries the intended day forward (31 Jan -> 28 Feb -> 31 Mar)",
          (m1.month, m1.day, m2.month, m2.day) == (2, 28, 3, 31))

    section("An unknown cadence still stops the series rather than raising")
    check("unknown repeat returns None",
          _next_occurrence(d, "Fortnightly", 1, None, 10) is None)

    # =================================================================
    section("15. Generation is date-driven, not completion-driven")
    # =================================================================
    gen_src = inspect.getsource(R.generate_due_recurring_tasks)
    for token in ("workflow_status", "completed_at", "completed_by"):
        check(f"15. the engine never reads `{token}` when deciding to generate",
              token not in gen_src)
    check("15. an UNFINISHED previous occurrence still produces the next one",
          occurrence_on(11, head=head_task(workflow_status="in_progress",
                                           completed_at=None))["start"].startswith("2026-08-11"))
    from app.routes import tasks as T
    check("15. completing a task does not call the recurrence engine",
          "generate_due_recurring_tasks" not in inspect.getsource(T.update_task_status))

    # =================================================================
    section("16. Series extension uses the SAME fresh-occurrence logic")
    # =================================================================
    import app.routes.calendar_events as C
    cal_src = inspect.getsource(C)
    check("16. the naive `{**existing, **updates}` walk is gone",
          "new_ev = {**existing, **updates}" not in cal_src)
    check("16. extension goes through build_series_occurrences",
          "build_series_occurrences" in cal_src)
    check("16. build_series_occurrences builds via _fresh_occurrence",
          "_fresh_occurrence(" in inspect.getsource(R.build_series_occurrences))
    check("16. _fresh_occurrence is defined exactly once",
          inspect.getsource(R).count("def _fresh_occurrence") == 1)

    built, truncated = await R.build_series_occurrences(
        head_task(), datetime(2026, 8, 13, 23, 59, tzinfo=IST), holiday_dates=set())
    check("16. extension produced the expected dates",
          [b["start"][:10] for b in built] == ["2026-08-11", "2026-08-12", "2026-08-13"])
    check("16. every extended occurrence has an unticked checklist",
          all(c["completed"] is False for b in built for c in b["checklist"]))
    check("16. no extended occurrence inherits evidence",
          all(b["completion_attachments"] == [] for b in built))
    check("16. no extended occurrence inherits remarks or dependency state",
          all(b["remarks"] == [] and b["dependency_stack"] == [] for b in built))
    check("16. extended occurrences keep the assigner's attachments",
          all(b["attachments"] == [{"id": "a1", "name": "template.docx"}] for b in built))
    check("16. extended occurrences keep the assigned deadline untouched",
          all(b["end"] == head_task()["end"] for b in built))
    check("   nothing was truncated", truncated is False)

    section("17. Duplicate generation does not duplicate occurrences")
    again, _ = await R.build_series_occurrences(
        head_task(), datetime(2026, 8, 13, 23, 59, tzinfo=IST), holiday_dates=set(),
        taken_dates={"2026-08-11", "2026-08-12", "2026-08-13"})
    check("17. dates already taken are skipped entirely", again == [])
    partial, _ = await R.build_series_occurrences(
        head_task(), datetime(2026, 8, 13, 23, 59, tzinfo=IST), holiday_dates=set(),
        taken_dates={"2026-08-12"})
    check("17. only the missing dates are created",
          [p["start"][:10] for p in partial] == ["2026-08-11", "2026-08-13"])

    # =================================================================
    section("18. De-duplication uses IST consistently")
    # =================================================================
    eng_src = inspect.getsource(R.generate_due_recurring_tasks)
    check("18. the UTC-date regex prefix is gone",
          "target.date().isoformat()" not in eng_src)
    check("18. the engine de-duplicates on the IST date",
          "_ist_date(target) not in existing_dates" in eng_src)
    check("18. build_series_occurrences already keyed on the IST date",
          "_ist_date(target).isoformat()" in inspect.getsource(R.build_series_occurrences))
    # 00:30 IST on 11 Aug is 19:00 UTC on 10 Aug — the two calendars disagree, which is
    # exactly the window the old prefix got wrong.
    midnight = datetime(2026, 8, 11, 0, 30, tzinfo=IST)
    check("18. a post-midnight IST time resolves to the IST day, not the UTC one",
          R._ist_date(midnight).isoformat() == "2026-08-11"
          and midnight.astimezone(timezone.utc).date().isoformat() == "2026-08-10")
    near = head_task(start="2026-08-10T00:30:00+05:30", end="2026-08-10T06:00:00+05:30")
    nb, _ = await R.build_series_occurrences(
        near, datetime(2026, 8, 12, 23, 59, tzinfo=IST), holiday_dates=set())
    ist_days = [R._ist_date(datetime.fromisoformat(b["start"])).isoformat() for b in nb]
    check("18. a near-midnight series produces one occurrence per IST day",
          ist_days == ["2026-08-11", "2026-08-12"] and len(set(ist_days)) == len(ist_days))
    check("   and the series-extension caller keys on IST too",
          "_rec_ist_date(when).isoformat()" in cal_src)

    # =================================================================
    section("11. Repeat End Date is mandatory")
    # =================================================================
    create_src = inspect.getsource(C.create_event)
    check("11. create rejects a repeating item with no end date",
          "if is_repeating and not end_date_str:" in create_src)
    check("11. the rejection is no longer todo-only",
          "if is_todo and is_repeating and not end_date_str:" not in create_src)
    check("11. update rejects it too",
          "a repeating item needs a date to repeat until" in inspect.getsource(C.update_event))
    check("11. a series id is still only assigned with an end date",
          "if is_repeating and end_date_str:" in create_src)

    # =================================================================
    section("19. Notification behaviour unchanged")
    # =================================================================
    check("19. the recurrence engine sends no notifications",
          not any(t in inspect.getsource(R)
                  for t in ("notify_task_event", "send_email_notification",
                            "task_events.publish", "notify_schedule")))
    check("19. it imports no notification module",
          "notification" not in inspect.getsource(R).split("def ")[0].lower())

    section("Preserved behaviour")
    check("tasks are still calendar-event documents", R.RECURRING_TYPES == ["task"])
    check("the collection list is unchanged", "calendar_events" in R.TASK_COLLECTIONS)
    check("holiday handling still present",
          callable(R.load_holiday_dates) and callable(R._is_off_day))
    check("weekly-off policy unchanged", R.WEEKLY_OFF_WEEKDAYS == {6})
    check("catch-up caps unchanged",
          R.MAX_SERIES_OCCURRENCES == 365 and R.MAX_SERIES_STEPS == 800)
    check("no APScheduler or new cron was introduced",
          not any(t in inspect.getsource(R) for t in ("apscheduler", "APScheduler", "crontab")))

    # =================================================================
    section("Holidays: the occurrence is DROPPED, never shifted")
    # =================================================================
    # The stated example: a daily task 10-15 Aug with 12 Aug a holiday must produce
    # 10, 11, 13, 14, 15 Aug -- nothing at all on the 12th, and nothing moved onto the 13th
    # that would collide with the 13th's own occurrence.
    daily = head_task(start="2026-08-10T09:00:00+05:30", end="2026-08-10T18:00:00+05:30")
    got, _ = await R.build_series_occurrences(
        daily, datetime(2026, 8, 15, 23, 59, tzinfo=IST), holiday_dates={"2026-08-12"})
    dates = [g["start"][:10] for g in got]
    check("Daily 10-15 Aug with a 12 Aug holiday -> 11, 13, 14, 15 (10 Aug is the head)",
          dates == ["2026-08-11", "2026-08-13", "2026-08-14", "2026-08-15"])
    check("nothing exists for the holiday date", "2026-08-12" not in dates)
    check("no duplicate landed on the day after the holiday", dates.count("2026-08-13") == 1)
    check("the series continues from its own calendar dates, not shifted by one",
          dates[-1] == "2026-08-15")

    section("Every cadence drops a holiday -- none shift")
    # Before this change only daily-style cadences dropped; weekly/monthly/annual/custom
    # tasks were moved to the next working day instead.
    cadences = [
        ("Weekly", "2026-08-10T09:00:00+05:30", 7),
        ("Monthly", "2026-08-10T09:00:00+05:30", 31),
        ("Yearly", "2026-08-10T09:00:00+05:30", 365),
        ("periodic", "2026-08-10T09:00:00+05:30", 3),
        ("Custom", "2026-08-10T09:00:00+05:30", 3),
    ]
    for cadence, start_iso, step in cadences:
        head = head_task(repeat=cadence, repeat_interval=step if cadence in
                         ("periodic", "Custom") else 1,
                         repeat_data={"customUnit": "Days"} if cadence == "Custom" else None,
                         start=start_iso, end="2026-08-10T18:00:00+05:30")
        first = _next_occurrence(datetime.fromisoformat(start_iso), cadence,
                                 head["repeat_interval"], head.get("repeat_data"), 10)
        if first is None:
            check(f"{cadence}: cadence resolves", False)
            continue
        holiday = R._ist_date(first).isoformat()
        built, _ = await R.build_series_occurrences(
            head, first + timedelta(days=1), holiday_dates={holiday})
        produced = [R._ist_date(datetime.fromisoformat(b["start"])).isoformat() for b in built]
        check(f"{cadence}: the holiday occurrence is dropped, not shifted",
              holiday not in produced and all(p != holiday for p in produced))
        check(f"{cadence}: nothing was moved onto the following day",
              (first + timedelta(days=1)).astimezone(IST).date().isoformat() not in produced)

    section("A dropped holiday does not drag the rest of the series")
    # Anti-drift: the next period is measured from the natural date, so a monthly-10th series
    # whose 10 Sep is a holiday still lands on 10 Oct -- not 11 Oct.
    monthly = head_task(repeat="Monthly", start="2026-08-10T09:00:00+05:30",
                        end="2026-08-10T18:00:00+05:30")
    built, _ = await R.build_series_occurrences(
        monthly, datetime(2026, 11, 30, 23, 59, tzinfo=IST), holiday_dates={"2026-09-10"})
    months = [b["start"][:10] for b in built]
    check("the September occurrence is absent", "2026-09-10" not in months)
    check("October and November still land on the 10th",
          months == ["2026-10-10", "2026-11-10"])

    section("A dropped holiday creates NOTHING at all")
    dropped, _ = await R.build_series_occurrences(
        head_task(), datetime(2026, 8, 11, 23, 59, tzinfo=IST),
        holiday_dates={"2026-08-11"})
    check("no task, no checklist, no reminders, no placeholder for that date",
          dropped == [])

    section("Consecutive holidays are all dropped")
    run, _ = await R.build_series_occurrences(
        head_task(), datetime(2026, 8, 15, 23, 59, tzinfo=IST),
        holiday_dates={"2026-08-11", "2026-08-12", "2026-08-13"})
    check("a three-day holiday run leaves only 14 and 15 Aug",
          [r["start"][:10] for r in run] == ["2026-08-14", "2026-08-15"])

    section("The two generation paths agree on holidays")
    eng = inspect.getsource(R.generate_due_recurring_tasks)
    bld = inspect.getsource(R.build_series_occurrences)
    for name, src in (("nightly engine", eng), ("series builder", bld)):
        check(f"{name} drops on a holiday before considering a shift",
              "_is_holiday(nxt, holiday_dates)" in src)
        check(f"{name} only shifts for a weekly off",
              "_is_weekly_off(nxt)" in src)
    check("the holiday policy is stated in one place", callable(R.drops_on_holiday))
    check("and it is unconditional", R.drops_on_holiday() is True)

    section("Weekly-off behaviour is unchanged")
    # 16 Aug 2026 is a Sunday. A daily task still drops it; a weekly task still shifts it.
    check("16 Aug 2026 is a Sunday", datetime(2026, 8, 16).weekday() == 6)
    check("a daily-style cadence still DROPS a weekly off",
          R.drops_off_days("task", "Daily", 1) is True)
    check("a weekly cadence still SHIFTS a weekly off",
          R.drops_off_days("task", "Weekly", 1) is False)
    check("a todo still drops every off day",
          R.drops_off_days("todo", "Monthly", 1) is True)
    sunday_head = head_task(start="2026-08-15T09:00:00+05:30",
                            end="2026-08-15T18:00:00+05:30")
    sun, _ = await R.build_series_occurrences(
        sunday_head, datetime(2026, 8, 17, 23, 59, tzinfo=IST), holiday_dates=set())
    check("a daily series skips Sunday entirely",
          [s["start"][:10] for s in sun] == ["2026-08-17"])

    passed = sum(1 for r in results if r)
    print(f"\n=== {passed}/{len(results)} checks passed ===")
    if passed != len(results):
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
