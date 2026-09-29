"""No HRMS service may look a record up by its business number ALONE.

Every business number here — ASM-, INT-, HR-REQ-, JD-, SCR-, TEL-, CAN- ... — is issued per
company, so every tenant has its own ASM-2026-001. A read or write keyed on the number and
nothing else therefore reaches whichever company's record the driver happens to return first.

That is not hypothetical. It is how an assessment reviewed in one company resolved another
company's assessment instead (test_assessment_tenant_isolation), and how rescheduling an
interview could notify another company's panel and candidate. Both were one-key lookups
written straight after a correctly scoped write, which is exactly the shape that reads as
safe in review.

This scans the service sources for that shape, so the next one fails here rather than in
production. It is a guard, not a proof: a lookup built dynamically will not be seen. It
catches the common case, which is the one that was written three times.

House convention: self-contained, no pytest, ASCII output, exit 1 on fail.

Run:  python -m app.services.hrms.tests.test_business_no_scoping   (from backend/)
"""
from __future__ import annotations

import pathlib
import re
import sys

results: list[bool] = []


def check(label: str, condition: bool) -> bool:
    results.append(bool(condition))
    print(f"  {'PASS' if condition else 'FAIL'}  {label}")
    return bool(condition)


# A Mongo call whose filter is a dict literal holding ONE key that ends in `_no`, e.g.
#   find_one({"assessment_no": assessment_no})
#   update_one({"interview_no": doc["interview_no"]}, ...)
ONE_KEY_NO = re.compile(
    r"\.(find_one|find|update_one|update_many|delete_one|delete_many|count_documents)"
    r"\(\s*\{\s*\"([a-z_]+_no)\"\s*:\s*[^,{}]+\}")


def main() -> int:
    services = pathlib.Path(__file__).resolve().parents[2]
    files = sorted(p for p in services.glob("hrms*.py"))
    print(f"-- scanning {len(files)} HRMS service module(s) --")

    offenders = []
    for path in files:
        text = path.read_text(encoding="utf-8")
        for m in ONE_KEY_NO.finditer(text):
            line = text.count("\n", 0, m.start()) + 1
            offenders.append(f"{path.name}:{line}  {m.group(1)}({{\"{m.group(2)}\": ...}})")

    for o in offenders:
        print(f"      {o}")
    check("no service looks a record up by its business number alone", not offenders)

    # The two services that had it, named, so a regression reads as the regression it is.
    for name in ("hrms_assessment_service.py", "hrms_interview_service.py"):
        text = (services / name).read_text(encoding="utf-8")
        check(f"{name} scopes every read by company", not ONE_KEY_NO.search(text))

    print("\n" + "=" * 64)
    print(f"  {sum(results)}/{len(results)} checks passed")
    print("=" * 64)
    return 0 if all(results) else 1


if __name__ == "__main__":
    sys.exit(main())
