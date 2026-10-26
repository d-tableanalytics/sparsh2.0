"""HRMS > Payroll > controlled formula engine (Phase 1 FRD §24-§25).

"The calculation engine should support controlled expressions and variables rather than
arbitrary executable code." So a formula is parsed with Python's `ast` and then EVALUATED
BY THIS MODULE, node by node, against a short allow-list -- it is never passed to `eval`.
Anything outside the list (attribute access, indexing, lambdas, comprehensions, imports,
unknown names or functions) is refused when the formula is SAVED, not when payroll runs.

Language
  numbers, + - * / % and parentheses, comparisons (> >= < <= == !=), AND / OR / NOT,
  and the functions IF(condition, then, else), MIN(...), MAX(...), ROUND(x[, digits]),
  FLOOR(x), CEIL(x), ABS(x).
Variables (upper case)
  * any component code already worked out earlier in the structure (by sequence)
  * GROSS (the earnings resolved so far), CTC (annual), MONTHLY_CTC
  * ATTENDANCE (§25 "attendance/payable days/LOP"): PAYABLE_DAYS, LOP_DAYS, PRESENT_DAYS,
    WORKING_DAYS, CALENDAR_DAYS, LOP_RATIO, PAYABLE_RATIO
  * EMPLOYEE FIELDS (§25 "Employee fields"): EMP_GRADE, EMP_LEVEL, EMP_LOCATION,
    EMP_CATEGORY, EMP_DEPARTMENT, EMP_PAYROLL_GROUP, EMP_SERVICE_MONTHS
  * CONSTANTS a company defines (§28 CALCULATION_VARIABLE), supplied by the caller

Examples
  IF(BASIC > 21000, 0, ROUND(GROSS * 0.0075, 0))
  IF(PAYABLE_DAYS < 15, 0, 1500)                     -- a full-attendance allowance
  ROUND(BASIC / CALENDAR_DAYS * LOP_DAYS, 0)         -- an explicit LOP recovery

An employee-field variable is a NUMBER or 0: the engine does arithmetic, not string
comparison, so EMP_GRADE is the grade's numeric suffix where it has one (M3 -> 3) and 0
otherwise. Comparing grades as text is what APPLICABILITY is for, and doing it in a formula
instead would be a second, weaker way to express the same thing.

A SLAB table maps a base value onto an amount: [{"upto": 7500, "amount": 0},
{"upto": 10000, "amount": 175}, {"upto": null, "amount": 200}] -- the first row whose
`upto` is at least the base (null = no ceiling). A row may carry `percent` instead of
`amount` to take a percentage of the base.
"""
import ast
import math
import re

from fastapi import HTTPException

# §25 Variables. Kept as three named sets rather than one blob because they come from
# three different places at evaluation time, and a reader debugging "why is this zero"
# needs to know which.
STRUCTURE_VARS  = {"GROSS", "CTC", "MONTHLY_CTC"}
ATTENDANCE_VARS = {"PAYABLE_DAYS", "LOP_DAYS", "PRESENT_DAYS", "WORKING_DAYS",
                   "CALENDAR_DAYS", "LOP_RATIO", "PAYABLE_RATIO"}
EMPLOYEE_VARS   = {"EMP_GRADE", "EMP_LEVEL", "EMP_LOCATION", "EMP_CATEGORY",
                   "EMP_DEPARTMENT", "EMP_PAYROLL_GROUP", "EMP_SERVICE_MONTHS"}
# §25 "payroll inputs": the maker's monthly figures for THIS period (FRD §10) and the two
# roll-ups the run adds itself, by the record field each one reads.
INPUT_FIELDS = {"INPUT_ARREARS": "arrears", "INPUT_REIMBURSEMENTS": "reimbursements",
                "INPUT_OTHER_EARNINGS": "other_earnings", "INPUT_BONUS": "bonus",
                "INPUT_OTHER_DEDUCTIONS": "other_deductions",
                "INPUT_NOTICE_RECOVERY": "notice_recovery",
                "INPUT_ADVANCE_RECOVERY": "advance_recovery",
                "INPUT_VARIABLE_PAY": "variable_pay_payout"}
INPUT_VARS = set(INPUT_FIELDS)
BUILT_INS = STRUCTURE_VARS | ATTENDANCE_VARS | EMPLOYEE_VARS | INPUT_VARS
FUNCTIONS = {
    "IF": None,                                   # evaluated lazily, see _eval
    "MIN": lambda *a: min(a),
    "MAX": lambda *a: max(a),
    "ROUND": lambda x, n=0: round(x, int(n)),
    "FLOOR": lambda x: float(math.floor(x)),
    "CEIL": lambda x: float(math.ceil(x)),
    "ABS": lambda x: abs(x),
}
MAX_FORMULA_LENGTH = 500
_BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b if b else 0.0,
        ast.Mod: lambda a, b: a % b if b else 0.0}
_CMP = {ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b,
        ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
        ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}


def _normalise(expr: str) -> str:
    """Accept the spreadsheet spellings AND / OR / NOT as well as Python's."""
    text = str(expr or "").strip()
    for word, py in (("AND", "and"), ("OR", "or"), ("NOT", "not")):
        text = re.sub(rf"\b{word}\b", py, text)
    return text


def parse(expr: str) -> ast.Expression:
    text = _normalise(expr)
    if not text:
        raise HTTPException(status_code=422, detail="The formula is empty.")
    if len(text) > MAX_FORMULA_LENGTH:
        raise HTTPException(status_code=422, detail="The formula is too long.")
    try:
        tree = ast.parse(text, mode="eval")
    except SyntaxError:
        raise HTTPException(status_code=422, detail="The formula is not valid — check brackets "
                                                    "and operators.")
    for node in ast.walk(tree):
        ok = isinstance(node, (ast.Expression, ast.BinOp, ast.UnaryOp, ast.Compare, ast.BoolOp,
                               ast.Call, ast.Name, ast.Constant, ast.Load, ast.IfExp,
                               ast.And, ast.Or, ast.Not, ast.USub, ast.UAdd)) \
            or type(node) in _BIN or type(node) in _CMP
        if not ok:
            raise HTTPException(status_code=422,
                                detail=f"'{type(node).__name__}' is not allowed in a formula.")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, float)):
            raise HTTPException(status_code=422, detail="Only numbers can appear in a formula.")
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id.upper() not in FUNCTIONS:
                raise HTTPException(status_code=422,
                                    detail="Only IF, MIN, MAX, ROUND, FLOOR, CEIL and ABS can be "
                                           "used as functions.")
            if node.keywords:
                raise HTTPException(status_code=422, detail="Named arguments are not allowed.")
            if node.func.id.upper() == "IF" and len(node.args) != 3:
                raise HTTPException(status_code=422, detail="IF needs exactly 3 parts: "
                                                            "IF(condition, then, else).")
    return tree


def references(expr: str) -> set:
    """Every variable a formula reads (function names excluded)."""
    tree = parse(expr)
    funcs = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    return {n.id.upper() for n in ast.walk(tree)
            if isinstance(n, ast.Name) and id(n) not in funcs}


def validate(expr: str, known_codes: set, constants: set = None) -> set:
    """Parse and check every variable exists. Returns the referenced variables.

    Refusing an unknown name HERE, when the formula is saved, is what makes adding
    variables safe: no formula already stored can reference one that did not exist when it
    was written, so widening BUILT_INS can never change an existing result.
    """
    refs = references(expr)
    allowed = BUILT_INS | set(known_codes) | set(constants or ())
    unknown = sorted(r for r in refs if r not in allowed)
    if unknown:
        raise HTTPException(
            status_code=422,
            detail=f"Unknown name(s) in the formula: {', '.join(unknown)}. Use component "
                   f"codes, a company constant, or one of: "
                   f"{', '.join(sorted(BUILT_INS))}.")
    return refs


def _numeric_suffix(value) -> float:
    """The number in a code like "M3" or "L-2", or 0. See the module docstring for why an
    employee field is a number here rather than a string."""
    import re as _re
    match = _re.search(r"(\d+(?:\.\d+)?)", str(value or ""))
    return float(match.group(1)) if match else 0.0


def employee_variables(profile: dict, period_end: str = None) -> dict:
    """The EMP_* half of a formula's environment (§25 "Employee fields")."""
    profile = profile or {}
    out = {
        "EMP_GRADE": _numeric_suffix(profile.get("grade")),
        "EMP_LEVEL": _numeric_suffix(profile.get("level")),
        "EMP_LOCATION": _numeric_suffix(profile.get("work_location")),
        "EMP_CATEGORY": _numeric_suffix(profile.get("employee_category")),
        "EMP_DEPARTMENT": _numeric_suffix(profile.get("department_id")),
        "EMP_PAYROLL_GROUP": _numeric_suffix(profile.get("payroll_group")),
        "EMP_SERVICE_MONTHS": 0.0,
    }
    joined, end = profile.get("joined_on"), period_end
    if joined and end and len(str(joined)) >= 7 and len(str(end)) >= 7:
        try:
            out["EMP_SERVICE_MONTHS"] = float(
                (int(end[:4]) - int(joined[:4])) * 12 + (int(end[5:7]) - int(joined[5:7])))
        except (ValueError, IndexError):
            pass
    return out


def attendance_variables(days: dict) -> dict:
    """The attendance half (§25 "attendance/payable days/LOP"), from the frozen basis the
    run already computed -- never re-derived, so a formula and the payable-days arithmetic
    can never disagree."""
    days = days or {}
    calendar = float(days.get("days_in_period") or 0)
    payable = float(days.get("payable_days") or 0)
    return {
        "PAYABLE_DAYS": payable,
        "LOP_DAYS": float(days.get("lop_days") or 0),
        "PRESENT_DAYS": float(days.get("present_days") or 0),
        "WORKING_DAYS": float(days.get("working_days") or 0),
        "CALENDAR_DAYS": calendar,
        "LOP_RATIO": (float(days.get("lop_days") or 0) / calendar) if calendar else 0.0,
        "PAYABLE_RATIO": (payable / calendar) if calendar else 0.0,
    }


def input_variables(inputs: dict) -> dict:
    """The INPUT_* part (§25 "payroll inputs"): what this period's record carries, 0 where
    nothing was entered."""
    inputs = inputs or {}
    return {var: float(inputs.get(field) or 0) for var, field in INPUT_FIELDS.items()}


def evaluate(expr: str, variables: dict) -> float:
    tree = parse(expr)
    upper = {str(k).upper(): v for k, v in variables.items()}
    return float(_eval(tree.body, upper))


def _eval(node, env):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return float(env.get(node.id.upper(), 0.0) or 0.0)
    if isinstance(node, ast.UnaryOp):
        v = _eval(node.operand, env)
        if isinstance(node.op, ast.USub):
            return -v
        if isinstance(node.op, ast.Not):
            return not v
        return v
    if isinstance(node, ast.BinOp):
        return _BIN[type(node.op)](_eval(node.left, env), _eval(node.right, env))
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comp in zip(node.ops, node.comparators):
            right = _eval(comp, env)
            if not _CMP[type(op)](left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.IfExp):
        return _eval(node.body, env) if _eval(node.test, env) else _eval(node.orelse, env)
    if isinstance(node, ast.Call):
        name = node.func.id.upper()
        if name == "IF":
            cond, a, b = node.args
            return _eval(a, env) if _eval(cond, env) else _eval(b, env)
        return FUNCTIONS[name](*[_eval(a, env) for a in node.args])
    raise HTTPException(status_code=422, detail="Unsupported formula.")


def clean_slabs(slabs) -> list:
    rows = []
    for raw in slabs or []:
        raw = raw if isinstance(raw, dict) else dict(raw)
        upto = raw.get("upto")
        upto = None if upto in (None, "") else float(upto)
        row = {"upto": upto}
        if raw.get("percent") not in (None, ""):
            row["percent"] = float(raw["percent"])
        else:
            row["amount"] = float(raw.get("amount") or 0)
        rows.append(row)
    if not rows:
        raise HTTPException(status_code=422, detail="A slab component needs at least one slab.")
    ceilings = [r["upto"] for r in rows if r["upto"] is not None]
    if ceilings != sorted(ceilings) or len(set(ceilings)) != len(ceilings):
        raise HTTPException(status_code=422, detail="Slabs must go up in order of 'up to'.")
    if any(r["upto"] is None for r in rows[:-1]):
        raise HTTPException(status_code=422, detail="Only the last slab can have no ceiling.")
    return rows


def slab_amount(slabs: list, base: float) -> float:
    for row in slabs:
        if row["upto"] is None or base <= row["upto"]:
            if "percent" in row:
                return base * row["percent"] / 100.0
            return row["amount"]
    return 0.0


def dependencies(component: dict) -> set:
    """What a component reads: its percentage / slab base, or its formula's variables."""
    method = component.get("calculation_method")
    if method == "Formula" and component.get("formula"):
        try:
            return references(component["formula"]) - BUILT_INS
        except HTTPException:
            return set()
    if method in ("Percentage", "Slab") and component.get("calculation_base"):
        base = str(component["calculation_base"])
        return set() if base.upper() in BUILT_INS else {base}
    return set()


def find_cycle(components: dict) -> list:
    """A dependency loop through the component master, as a path, or []."""
    graph = {code: dependencies(c) for code, c in components.items()}
    state, path = {}, []

    def visit(code):
        state[code] = 1
        path.append(code)
        for dep in graph.get(code, ()):
            if state.get(dep) == 1:
                return path[path.index(dep):] + [dep]
            if state.get(dep) is None and dep in graph:
                found = visit(dep)
                if found:
                    return found
        state[code] = 2
        path.pop()
        return []

    for code in graph:
        if state.get(code) is None:
            found = visit(code)
            if found:
                return found
    return []


def dependants(components: dict, code: str) -> list:
    """Every component that (directly or indirectly) reads `code` -- the impact of
    changing it (FRD §25 Dependency Validation)."""
    graph = {c: dependencies(v) for c, v in components.items()}
    out, frontier = set(), {code}
    while frontier:
        nxt = {c for c, deps in graph.items() if deps & frontier and c not in out}
        out |= nxt
        frontier = nxt
    return sorted(out)
