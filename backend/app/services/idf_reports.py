"""Inter-Departmental Feedback — reports, Excel import/export, and the MD-only email.

* compiled_workbook  — the client's own format (docs/hrms/Report Interdepartmental_Feedback_
                       Compiled.xls): a "Company" sheet, one "FEEDBACK FOR: <dept>" sheet per
                       rated department (rater departments as columns, then Final and Comments,
                       with Strength, Improvement and Average Score), and the legend sheet.
                       The MD downloads it every month; the same layout imports back in.
* analysis_workbook / analysis_pdf — the report package of document §10A: company score,
                       department scorecard, parameter analysis, feedback matrix, strengths &
                       improvements, hotspots, action plan and management summary.
* email_md_package   — sent to the MD only, never HR (document §10B). The email log records
                       that the package went out, never its content.

Rater identities never appear: every report speaks in departments.
"""
import io
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException

from app.db.mongodb import get_collection

TITLE = "Interdepartmental Feedback Questionnaire"
SCALE = ("Scale: 1 = Poor | 2 = Below Average | 3 = Average | 4 = Good | 5 = Excellent | "
         "Blank = Not applicable this cycle")
# Exactly as the client's sample ("s" is the sample's own header text).
STRENGTH_LABEL = "One thing this department does well."
IMPROVEMENT_LABEL = "One thing this department should improve."
LEGEND = [("s", "Meaning"), ("Below 60%", "Poor"), ("60 to 79.9%", "Average"), ("80 And Above", "Good")]
BAND_FILL = {"Red": "F8D7DA", "Amber": "FFF3CD", "Green": "D4EDDA"}


async def _company_name(company_id: str) -> str:
    from bson import ObjectId
    try:
        c = await get_collection("companies").find_one({"_id": ObjectId(company_id)}, {"name": 1})
    except Exception:
        c = None
    return (c or {}).get("name") or "Company"


def _r(v, nd=2):
    """Values are stored at full precision, exactly as the client's workbook does (3.8333…);
    the cell's number format shows 2 decimals. `nd` is kept for call-site readability."""
    return None if v is None else float(v)


def _fraction(avg):
    """Average Score % as the sample stores it: average ÷ 5 (0.8 shown as 80%)."""
    return None if avg is None else avg / 5


# The sample's number formats: a rater's rating '0', Final / averages '0.00', the score '0%'.
FMT_RATING, FMT_AVG, FMT_PCT = "0", "0.00", "0%"


def _number_formats(ws, header_row: int, n_params: int, n_cols: int, rating_cols: bool) -> None:
    """Apply the sample's number formats. Columns 3..(n_cols) hold the department/rater values,
    then Final (or Company), then Comments / the % cell."""
    first, last_val = 3, n_cols                       # value columns incl. Final/Company
    for r in range(header_row + 1, header_row + 1 + n_params):
        for c in range(first, last_val + 1):
            final = c == last_val
            ws.cell(row=r, column=c).number_format = FMT_AVG if (final or not rating_cols) else FMT_RATING
    avg_row = header_row + n_params + 4               # Open feedback, Strength, Improvement, Average
    for c in range(first, last_val + 1):
        ws.cell(row=avg_row, column=c).number_format = FMT_AVG
    ws.cell(row=avg_row, column=last_val + 1).number_format = FMT_PCT


# ─────────────────────────────────────────────────────────────
# The client's compiled workbook
# ─────────────────────────────────────────────────────────────
def compiled_workbook(cycle: dict, result: dict, subs: List[dict], company_name: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    params = cycle.get("parameters") or []
    bold = Font(bold=True)
    head_fill = PatternFill("solid", fgColor="DDE3FF")
    wrap = Alignment(wrap_text=True, vertical="top")
    by_dept = {d["id"]: d for d in result["departments"]}

    # Rated departments in mapping order; raters per rated department from the cycle's pairs.
    receivers: List[Tuple[str, str]] = []
    raters_of: Dict[str, List[Tuple[str, str]]] = {}
    for p in cycle.get("pairs") or []:
        if (p["receiver_dept_id"], p["receiver_name"]) not in receivers:
            receivers.append((p["receiver_dept_id"], p["receiver_name"]))
        lst = raters_of.setdefault(p["receiver_dept_id"], [])
        if (p["giver_dept_id"], p["giver_name"]) not in lst:
            lst.append((p["giver_dept_id"], p["giver_name"]))
    sub_of = {(s["giver_dept_id"], s["receiver_dept_id"]): s for s in subs}

    wb = Workbook()
    ws = wb.active
    ws.title = "Company"
    scored = [(rid, name) for rid, name in receivers if by_dept.get(rid, {}).get("pct") is not None]
    ws.append([TITLE]); ws.append([SCALE]); ws.append(["FEEDBACK FROM:", company_name]); ws.append([])
    ws.append(["Topic", "Question"] + [n for _, n in scored] + ["Company", "Comments"])
    for p in params:
        ws.append([p["name"], p.get("report_question") or p["question"]] + [_r(by_dept[rid]["param_avg"].get(p["code"])) for rid, _ in scored]
                  + [_r(result["company"]["param_avg"].get(p["code"])), ""])
    ws.append(["Open feedback"])
    ws.append(["Strength", "One thing what departments does well."])
    ws.append(["Improvement", "One thing what department should improve."])
    ws.append(["Average Score", "Average rating across scored topics"]
              + [_r(by_dept[rid]["avg"]) for rid, _ in scored]
              + [_r(result["company"]["avg"]), _fraction(result["company"]["avg"])])
    _style(ws, 5, bold, head_fill, wrap, len(scored) + 4)
    _number_formats(ws, 5, len(params), 2 + len(scored) + 1, rating_cols=False)

    notes = {}
    for n in cycle.get("imported_notes") or []:
        notes.setdefault((n["receiver_dept_id"], n.get("parameter")), []).append(n["text"])
    for rid, rname in receivers:
        sh = wb.create_sheet(_sheet_title(rname, wb))
        raters = raters_of.get(rid, [])
        d = by_dept.get(rid) or {}
        sh.append([TITLE]); sh.append([SCALE]); sh.append([]); sh.append(["FEEDBACK FOR:", rname]); sh.append([])
        sh.append(["Topic", "Question"] + [n for _, n in raters] + ["Final", "Comments"])
        for p in params:
            row = [p["name"], p.get("report_question") or p["question"]]
            texts = list(notes.get((rid, p["code"]), []))
            for gid, gname in raters:
                s = sub_of.get((gid, rid))
                v = (s or {}).get("ratings", {}).get(p["code"])
                row.append(v if isinstance(v, (int, float)) and 1 <= v <= 5 else None)
                if s and (s.get("comments") or {}).get(p["code"]):
                    texts.append(f"{gname}: {s['comments'][p['code']]}")
            row += [_r((d.get("param_avg") or {}).get(p["code"])), " | ".join(texts)]
            sh.append(row)
        sh.append([f"Open feedback for {rname}"])
        # An imported file may carry the HOD's text in the label column; it is written back there.
        sh.append(["Strength", " ".join(notes.get((rid, "strength"), [])) or STRENGTH_LABEL]
                  + [(sub_of.get((gid, rid)) or {}).get("strength") or None for gid, _ in raters])
        sh.append(["Improvement", " ".join(notes.get((rid, "improvement"), [])) or IMPROVEMENT_LABEL]
                  + [(sub_of.get((gid, rid)) or {}).get("improvement") or None for gid, _ in raters])
        rater_avg = []
        for gid, _ in raters:
            s = sub_of.get((gid, rid))
            vals = [v for v in ((s or {}).get("ratings") or {}).values() if isinstance(v, (int, float)) and 1 <= v <= 5]
            rater_avg.append(_r(sum(vals) / len(vals)) if vals else None)
        sh.append(["Average Score", "Average rating across scored topics"] + rater_avg
                  + [_r(d.get("avg")), _fraction(d.get("avg"))])
        _style(sh, 6, bold, head_fill, wrap, len(raters) + 4)
        _number_formats(sh, 6, len(params), 2 + len(raters) + 1, rating_cols=True)

    leg = wb.create_sheet("Sheet1")
    for row in LEGEND:
        leg.append(list(row))
    leg["A1"].font = bold; leg["B1"].font = bold
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _sheet_title(name: str, wb) -> str:
    bad = '[]:*?/\\'
    base = "".join("_" if ch in bad else ch for ch in name)[:31] or "Department"
    title, n = base, 2
    while title in wb.sheetnames:
        title = f"{base[:28]}_{n}"; n += 1
    return title


def _style(ws, header_row, bold, fill, wrap, ncols):
    ws["A1"].font = Font_big()
    for c in ws[header_row]:
        c.font = bold; c.fill = fill
    for row in ws.iter_rows(min_row=header_row + 1):
        for c in row:
            c.alignment = wrap
    ws.column_dimensions["A"].width = 24
    ws.column_dimensions["B"].width = 60
    from openpyxl.utils import get_column_letter
    for i in range(3, ncols + 2):
        ws.column_dimensions[get_column_letter(i)].width = 14
    ws.column_dimensions[get_column_letter(ncols + 1)].width = 40


def Font_big():
    from openpyxl.styles import Font
    return Font(bold=True, size=13)


# ─────────────────────────────────────────────────────────────
# Analysis workbook + PDF (document §10A)
# ─────────────────────────────────────────────────────────────
def band_of(pct):
    return None if pct is None else "Red" if pct < 60 else "Amber" if pct < 80 else "Green"


def summary_sections(result: dict, company_name: str) -> List[Tuple[str, List[str]]]:
    """Document §10A Management Summary: key findings, major concerns, recommended focus areas."""
    c, depts = result["company"], [d for d in result["departments"] if d["pct"] is not None]
    if c["pct"] is None:
        return [("Key findings", ["No feedback scores yet for this cycle."])]
    count = {b: sum(1 for d in depts if d["band"] == b) for b in ("Red", "Amber", "Green")}
    hs = result["hotspots"]
    reds = [d for d in depts if d["band"] == "Red"]
    ambers = [d for d in depts if d["band"] == "Amber"]
    greens = [d for d in depts if d["band"] == "Green"]
    drops = [d for d in depts if d.get("dropped")]

    findings = [f"{company_name} scores {c['pct']}% overall, which places it in the {c['band']} band"
                f"{' (' + c['stage'] + ')' if c.get('stage') else ''}.",
                f"Of the {len(depts)} departments rated, {count['Red']} are Red, {count['Amber']} Amber and "
                f"{count['Green']} Green."]
    if result.get("highest"):
        findings.append(f"Highest-scoring department: {result['highest']}; lowest: {result['lowest']}.")
    if c.get("previous_pct") is not None:
        diff = round(c["pct"] - c["previous_pct"], 1)
        findings.append(f"Compared with the previous cycle the company score moved {'+' if diff >= 0 else ''}{diff} "
                        f"points (from {c['previous_pct']}%).")
    if greens:
        findings.append("Recognition — Green, Performing: " + ", ".join(f"{d['name']} ({d['pct']}%)" for d in greens)
                        + ". Their successful practices should be captured and shared with other departments.")

    concerns = []
    if hs:
        concerns.append(f"{len(hs)} relationship(s) fall below 60% and get the Red repair steps even where the "
                        f"department is Amber: " + "; ".join(f"{h['from']} → {h['to']} ({h['pct']}%)" for h in hs) + ".")
    else:
        concerns.append("No department-to-department relationship falls below 60%.")
    if reds:
        concerns.append("Red departments (Storming): " + ", ".join(f"{d['name']} ({d['pct']}%)" for d in reds) + ".")
    if c.get("weakest_param"):
        concerns.append(f"The weakest parameter company-wide is {c['weakest_param']} ({c['weakest_param_pct']}%).")
    if drops:
        concerns.append("Dropped 5+ points since the last cycle (Amber process triggered): "
                        + ", ".join(d["name"] for d in drops) + ".")

    focus = []
    if c.get("weakest_param"):
        focus.append(f"Company-wide theme: {c['weakest_param']} — the main area to work on this cycle.")
    for h in hs:
        focus.append(f"{h['from']} → {h['to']}: facilitated repair meeting within 7 days"
                     f"{' on ' + h['weakest'] if h.get('weakest') else ''}; hand-off agreement; weekly WRM review.")
    for d in reds:
        if not any(h["to_id"] == d["id"] for h in hs):
            focus.append(f"{d['name']}: department repair — 5-Why root cause and a re-score after 30 days.")
    for d in ambers:
        focus.append(f"{d['name']}: 30-minute interface meeting within 15 days on {d.get('weakest_param') or 'its weakest parameter'}"
                     f"{' with ' + d['lowest_rater'] if d.get('lowest_rater') else ''}.")
    if greens:
        focus.append("Sustain: " + ", ".join(d["name"] for d in greens) + " — share practices and support other departments.")
    return [("Key findings", findings), ("Major concerns", concerns), ("Recommended focus areas", focus or ["—"])]


def management_summary(result: dict, company_name: str) -> List[str]:
    lines = []
    for title, items in summary_sections(result, company_name):
        lines.append(f"{title}:")
        lines += items
    return lines


def analysis_workbook(result: dict, actions: List[dict], company_name: str) -> bytes:
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    params = result["parameters"]
    bold = Font(bold=True)

    def sheet(wb, title, header, rows, band_col=None):
        ws = wb.create_sheet(title) if wb.worksheets and wb.active.title != "Sheet" else wb.active
        if ws.title == "Sheet":
            ws.title = title
        ws.append(header)
        for c in ws[1]:
            c.font = bold
            c.fill = PatternFill("solid", fgColor="DDE3FF")
        for r in rows:
            ws.append(r)
            if band_col is not None and r[band_col] in BAND_FILL:
                ws.cell(row=ws.max_row, column=band_col + 1).fill = PatternFill("solid", fgColor=BAND_FILL[r[band_col]])
        for i, _ in enumerate(header, start=1):
            ws.column_dimensions[ws.cell(row=1, column=i).column_letter].width = 22
        return ws

    wb = Workbook()
    c = result["company"]
    sheet(wb, "Company Overall", ["Company", "Cycle", "Overall %", "Band", "Team Stage", "Previous cycle %",
                                  "Feedback completion %"],
          [[company_name, result["cycle"]["period"], c["pct"], c["band"], c.get("stage"), c.get("previous_pct"),
            result["completion"]["percent"]]], band_col=3)
    sheet(wb, "Department Scorecard", ["Department"] + [p["name"] for p in params]
          + ["Overall %", "Band", "Team Stage", "Previous %", "Change"],
          [[d["name"]] + [d["param_pct"].get(p["code"]) for p in params]
           + [d["pct"], d["band"], d.get("stage"), d.get("previous_pct"), d.get("change")] for d in result["departments"]]
          + [["Company"] + [c["param_pct"].get(p["code"]) for p in params]
             + [c["pct"], c["band"], c.get("stage"), c.get("previous_pct"), None]],
          band_col=len(params) + 2)
    sheet(wb, "Parameter Analysis", ["Parameter", "Company %", "Band", "Weakest department", "Weakest department %"],
          [[p["name"], c["param_pct"].get(p["code"]), band_of(c["param_pct"].get(p["code"]))]
           + (lambda w: [w["name"], w["param_pct"].get(p["code"])] if w else [None, None])(
               min((d for d in result["departments"] if d["param_pct"].get(p["code"]) is not None),
                   key=lambda d: d["param_pct"][p["code"]], default=None))
           for p in params])
    sheet(wb, "Feedback Matrix", ["Rater → Rated", "Rated department", "Rating department"]
          + [p["name"] for p in params] + ["Score %", "Band"],
          [[f"{r['from']} → {r['to']}", r["to"], r["from"]] + [r["ratings"].get(p["code"]) for p in params]
           + [r["pct"], r["band"]] for r in result["relationships"]], band_col=3 + len(params) + 1)
    sheet(wb, "Strength & Improvement", ["Department", "Type", "From department", "Parameter", "Comment"],
          [[d["name"], "Strength", s["from"], "", s["text"]] for d in result["departments"] for s in d["strengths"]]
          + [[d["name"], "Improvement", s["from"], "", s["text"]] for d in result["departments"] for s in d["improvements"]]
          + [[d["name"], "Comment", s["from"], s["parameter"], s["text"]] for d in result["departments"] for s in d["comments"]])
    sheet(wb, "Hotspots", ["Relationship (rater → rated)", "Score %", "Weakest parameter"],
          [[f"{h['from']} → {h['to']}", h["pct"], h["weakest"]] for h in result["hotspots"]])
    sheet(wb, "Action Plan", ["Department", "Feedback From", "Parameter", "Current Score %", "Band", "Team Stage",
                              "Type", "Improvement Steps", "Action Owner", "Target Date", "Status", "Remarks",
                              "Review Date", "Re-score Date"],
          [[a["department"], a.get("feedback_from"), a.get("parameter"), a.get("current_score"), a.get("band"),
            a.get("stage"), a.get("type"),
            "\n".join(f"{i}. {s}" for i, s in enumerate(a.get("steps") or [], 1)) or a.get("improvement_action"),
            a.get("owner_name"), a.get("target_date"), a.get("status"),
            " | ".join(r.get("text", "") for r in a.get("remarks") or []), a.get("review_date"),
            a.get("rescore_date")] for a in actions],
          band_col=4)
    ws = wb.create_sheet("Management Summary")
    ws.append(["Management Summary"]); ws["A1"].font = Font(bold=True, size=13)
    for title, items in summary_sections(result, company_name):
        ws.append([title])
        ws.cell(row=ws.max_row, column=1).font = Font(bold=True, size=11)
        for line in items:
            ws.append([f"• {line}"])
        ws.append([])
    ws.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def analysis_pdf(result: dict, actions: List[dict], company_name: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

    styles = getSampleStyleSheet()
    small = styles["BodyText"].clone("small", fontSize=8, leading=10)
    params = result["parameters"]
    band_color = {"Red": colors.HexColor("#F8D7DA"), "Amber": colors.HexColor("#FFF3CD"),
                  "Green": colors.HexColor("#D4EDDA")}

    def table(header, rows, band_idx=None, widths=None):
        data = [[Paragraph(f"<b>{h}</b>", small) for h in header]] + \
               [[Paragraph("" if v is None else str(v), small) for v in r] for r in rows]
        t = Table(data, colWidths=widths, repeatRows=1)
        st = [("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
              ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#DDE3FF")), ("VALIGN", (0, 0), (-1, -1), "TOP")]
        if band_idx is not None:
            for i, r in enumerate(rows, start=1):
                if r[band_idx] in band_color:
                    st.append(("BACKGROUND", (band_idx, i), (band_idx, i), band_color[r[band_idx]]))
        t.setStyle(TableStyle(st))
        return t

    c = result["company"]
    story = [Paragraph(f"Inter-Departmental Feedback Report — {company_name}", styles["Title"]),
             Paragraph(f"Cycle {result['cycle']['period']} · Confidential — for the MD only", styles["Italic"]),
             Spacer(1, 4 * mm),
             Paragraph("1. Company overall score", styles["Heading2"]),
             table(["Overall %", "Band", "Previous cycle %", "Feedback completion %"],
                   [[c["pct"], c["band"], c.get("previous_pct"), result["completion"]["percent"]]], band_idx=1),
             Paragraph("2. Department-wise scorecard", styles["Heading2"]),
             table(["Department"] + [p["name"] for p in params] + ["Overall %", "Band", "Team Stage", "Change"],
                   [[d["name"]] + [d["param_pct"].get(p["code"]) for p in params]
                    + [d["pct"], d["band"], d.get("stage"), d.get("change")] for d in result["departments"]]
                   + [["Company"] + [c["param_pct"].get(p["code"]) for p in params] + [c["pct"], c["band"], c.get("stage"), None]],
                   band_idx=len(params) + 2),
             Paragraph("3. Parameter-wise analysis", styles["Heading2"]),
             table(["Parameter", "Company %", "Band", "Weakest department", "Weakest department %"],
                   [[p["name"], c["param_pct"].get(p["code"]), band_of(c["param_pct"].get(p["code"]))]
                    + (lambda w: [w["name"], w["param_pct"].get(p["code"])] if w else ["—", None])(
                        min((d for d in result["departments"] if d["param_pct"].get(p["code"]) is not None),
                            key=lambda d: d["param_pct"][p["code"]], default=None))
                    for p in params], band_idx=2),
             Paragraph("4. Inter-departmental feedback matrix", styles["Heading2"]),
             table(["Rater → Rated"] + [p["name"] for p in params] + ["Score %", "Band"],
                   [[f"{r['from']} → {r['to']}"] + [r["ratings"].get(p["code"]) for p in params] + [r["pct"], r["band"]]
                    for r in result["relationships"]], band_idx=len(params) + 2),
             Paragraph("5. Hotspots — relationships below 60%", styles["Heading2"]),
             table(["Relationship", "Score %", "Weakest parameter"],
                   [[f"{h['from']} → {h['to']}", h["pct"], h["weakest"]] for h in result["hotspots"]] or [["None", "", ""]]),
             Paragraph("6. Strengths & improvements", styles["Heading2"]),
             table(["Department", "Type", "From", "Comment"],
                   [[d["name"], "Strength", s["from"], s["text"]] for d in result["departments"] for s in d["strengths"]]
                   + [[d["name"], "Improvement", s["from"], s["text"]] for d in result["departments"] for s in d["improvements"]]
                   or [["—", "", "", ""]], widths=[35 * mm, 25 * mm, 35 * mm, 160 * mm]),
             Paragraph("7. Department-wise action plan", styles["Heading2"]),
             table(["Department", "From", "Parameter", "Score %", "Band", "Action", "Owner", "Target", "Status"],
                   [[a["department"], a.get("feedback_from"), a.get("parameter"), a.get("current_score"), a.get("band"),
                     "<br/>".join(f"{i}. {s}" for i, s in enumerate(a.get("steps") or [], 1)) or a.get("improvement_action"),
                     a.get("owner_name"), a.get("target_date"), a.get("status")]
                    for a in actions] or [["—"] * 9], band_idx=4,
                   widths=[25 * mm, 22 * mm, 25 * mm, 15 * mm, 15 * mm, 85 * mm, 28 * mm, 20 * mm, 18 * mm]),
             Paragraph("8. Management summary", styles["Heading2"])]
    for title, items in summary_sections(result, company_name):
        story.append(Paragraph(title, styles["Heading3"]))
        story += [Paragraph(f"• {line}", styles["BodyText"]) for line in items]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                      topMargin=12 * mm, bottomMargin=12 * mm).build(story)
    return buf.getvalue()


async def package(cycle: dict) -> Dict[str, bytes]:
    from app.services.idf_analysis import analyse, submissions_for, COLL_ACTIONS
    result = await analyse(cycle)
    subs = await submissions_for(cycle)
    actions = await get_collection(COLL_ACTIONS).find({"cycle_id": str(cycle["_id"])}).to_list(2000)
    name = await _company_name(cycle["company_id"])
    p = cycle.get("period") or "cycle"
    return {f"Interdepartmental_Feedback_Compiled_{p}.xlsx": compiled_workbook(cycle, result, subs, name),
            f"Interdepartmental_Feedback_Analysis_{p}.xlsx": analysis_workbook(result, actions, name),
            f"Interdepartmental_Feedback_Report_{p}.pdf": analysis_pdf(result, actions, name)}


async def email_md_package(cycle: dict) -> int:
    """Document §10B: the report package to the MD ONLY (never HR). Returns emails sent."""
    from email.mime.application import MIMEApplication
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from app.config.settings import settings
    from app.services import smtp_delivery
    from app.services.notification_service import log_notification
    from app.services.idf_service import company_mds, _name
    from app.services.idf_process import render_idf_mail, _month
    mds = [u for u in await company_mds(cycle["company_id"]) if u.get("email")]
    if not mds or not settings.SMTP_USERNAME or not settings.SMTP_PASSWORD:
        return 0
    files = await package(cycle)
    sent = 0
    for md in mds:
        msg = MIMEMultipart()
        msg["From"], msg["To"] = settings.SMTP_USERNAME, md["email"]
        # Subject and body: the "Final Report to MD" Notification Template (built-in default
        # until an admin edits it). Switched off there -> no email.
        rendered = await render_idf_mail("idf_md_report", {
            "name": _name(md) or "MD", "cycle_month": _month(cycle.get("period")),
            "results_meeting_date": (datetime.fromisoformat(cycle["results_meeting_date"]).strftime("%d %b %Y")
                                     if cycle.get("results_meeting_date") else "the date HR confirms")},
            cycle["company_id"])
        if not rendered:
            continue
        msg["Subject"] = rendered[0]
        msg.attach(MIMEText(rendered[1], "html"))
        for fname, data in files.items():
            part = MIMEApplication(data, Name=fname)
            part["Content-Disposition"] = f'attachment; filename="{fname}"'
            msg.attach(part)
        try:
            ok, err = await smtp_delivery.send_message(msg, [md["email"]])
        except Exception as exc:
            ok, err = False, str(exc)
        sent += 1 if ok else 0
        try:
            await log_notification(str(md["_id"]), md["email"], "email", "idf_md_report",
                                   "Confidential Inter-Departmental Feedback report package (contents not logged)",
                                   "sent" if ok else "failed", None if ok else err)
        except Exception:
            pass
    await get_collection("idf_cycles").update_one(
        {"_id": cycle["_id"]}, {"$set": {"report_sent_at": datetime.now(timezone.utc), "report_recipients": sent}})
    return sent


async def md_download(user: dict, cycle_id: str, kind: str, company_id: Optional[str] = None) -> Tuple[str, bytes, str]:
    from app.services.idf_service import assert_md, _get_cycle
    cid = await assert_md(user, company_id)
    cycle = await _get_cycle(cid, cycle_id)
    if cycle.get("status") != "Completed":
        pairs = cycle.get("pairs") or []
        done = sum(1 for p in pairs if p.get("status") == "Completed")
        raise HTTPException(status_code=409, detail=(
            f"Feedback is still pending ({done} of {len(pairs)} submitted). The final report is generated "
            f"and sent to the MD once every form is in." if cycle.get("status") == "Open"
            else f"This cycle is {cycle.get('status')} — there is no final report."))
    files = await package(cycle)
    pick = {"compiled": "Compiled", "analysis": "Analysis", "pdf": "Report"}.get(kind)
    if not pick:
        raise HTTPException(status_code=422, detail="Choose compiled, analysis or pdf.")
    fname = next(f for f in files if f"_{pick}_" in f)
    media = "application/pdf" if fname.endswith(".pdf") else \
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    return fname, files[fname], media


# ─────────────────────────────────────────────────────────────
# Import — the same compiled format back in (MD)
# ─────────────────────────────────────────────────────────────
def _grid(data: bytes, filename: str) -> Dict[str, List[List]]:
    name = (filename or "").lower()
    out: Dict[str, List[List]] = {}
    if name.endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(file_contents=data)
        for sh in wb.sheets():
            out[sh.name] = [[sh.cell_value(r, c) for c in range(sh.ncols)] for r in range(sh.nrows)]
    elif name.endswith(".xlsx") or name.endswith(".xlsm"):
        from openpyxl import load_workbook
        wb = load_workbook(io.BytesIO(data), data_only=True, read_only=True)
        for ws in wb.worksheets:
            out[ws.title] = [list(r) for r in ws.iter_rows(values_only=True)]
    else:
        raise HTTPException(status_code=422, detail="Upload the feedback workbook as .xls or .xlsx.")
    return out


def _norm(name) -> str:
    s = " ".join(str(name or "").strip().lower().split())
    for suffix in (" department", " dept", " dep"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
    return s[:-1] if len(s) > 3 and s.endswith("s") else s


def _cell(rows, r, c):
    try:
        v = rows[r][c]
    except IndexError:
        return None
    return v.strip() if isinstance(v, str) else v


def parse_compiled(data: bytes, filename: str, parameters: List[dict]) -> dict:
    """Read the compiled workbook into rated departments, raters, ratings and texts."""
    grids = _grid(data, filename)
    pmap = {_norm(p["name"]): p["code"] for p in parameters}
    sheets = []
    for title, rows in grids.items():
        flat = [str(v or "").strip().lower() for r in rows[:6] for v in r]
        if title.strip().lower() == "company" or "feedback from:" in flat or "meaning" in flat:
            continue                                   # summary and legend sheets are computed, not read
        receiver, header_r = title, None
        for r in range(min(len(rows), 12)):
            a = str(_cell(rows, r, 0) or "").strip().lower()
            if a.startswith("feedback for"):
                receiver = str(_cell(rows, r, 1) or title).strip() or title
            if a == "topic":
                header_r = r
                break
        if header_r is None:
            continue
        header = [str(v or "").strip() for v in rows[header_r]]
        try:
            final_c = next(i for i, h in enumerate(header) if h.lower() == "final")
        except StopIteration:
            final_c = len(header)
        comment_c = next((i for i, h in enumerate(header) if h.lower() == "comments"), None)
        raters = [(i, header[i]) for i in range(2, final_c) if header[i]]
        ratings = {i: {} for i, _ in raters}
        strength, improvement, notes = {}, {}, []
        for r in range(header_r + 1, len(rows)):
            label = str(_cell(rows, r, 0) or "").strip()
            key = _norm(label)
            if key in pmap:
                for i, _ in raters:
                    v = _cell(rows, r, i)
                    try:
                        v = float(v)
                    except (TypeError, ValueError):
                        v = None
                    ratings[i][pmap[key]] = int(round(v)) if v is not None and 1 <= v <= 5 else None
                if comment_c is not None and _cell(rows, r, comment_c):
                    notes.append({"parameter": pmap[key], "text": str(_cell(rows, r, comment_c))})
            elif key in ("strength", "improvement"):
                texts = {i: str(_cell(rows, r, i) or "").strip() for i, _ in raters}
                if key == "strength":
                    strength = texts
                else:
                    improvement = texts
                # Text typed over the label in column B is feedback too — keep it as a note.
                b = str(_cell(rows, r, 1) or "").strip()
                if b and _norm(b) not in (_norm(STRENGTH_LABEL), _norm(IMPROVEMENT_LABEL),
                                          _norm("One thing what department should improve.")):
                    notes.append({"parameter": key, "text": b})
        sheets.append({"receiver": receiver, "raters": [
            {"name": n, "ratings": ratings[i], "strength": strength.get(i, ""), "improvement": improvement.get(i, "")}
            for i, n in raters], "notes": notes})
    if not sheets:
        raise HTTPException(status_code=422,
                            detail="No 'FEEDBACK FOR' department sheets found — use the compiled feedback format.")
    return {"sheets": sheets}


async def import_compiled(user: dict, data: bytes, filename: str, period: str, apply: bool,
                          create_missing: bool) -> dict:
    """Preview (apply=False) or load the workbook as `period`'s feedback, REPLACING that
    month's ratings. Unknown department names are listed; create_missing adds them to the
    master department list."""
    from app.services import idf_service as S
    from app.services.idf_analysis import generate_actions
    cid = await S.assert_md(user)
    period = str(period or "")[:7]
    if len(period) != 7 or period[4] != "-":
        raise HTTPException(status_code=422, detail="Choose the month to import into (YYYY-MM).")
    st = await S.settings(cid)
    parsed = parse_compiled(data, filename, st["parameters"])
    depts = {_norm(d["name"]): d for d in await S.departments(cid)}
    names = set()
    for sh in parsed["sheets"]:
        names.add(sh["receiver"])
        names.update(r["name"] for r in sh["raters"])
    unknown = sorted(n for n in names if _norm(n) not in depts)
    existing = await get_collection(S.COLL_CYCLES).find_one(
        {"company_id": cid, "period": period, "status": {"$ne": S.CYCLE_CANCELLED}})
    if existing and existing["status"] == S.CYCLE_OPEN:
        raise HTTPException(status_code=409,
                            detail=f"The {period} cycle is still open for online feedback — complete or cancel it first.")
    rated = sum(1 for sh in parsed["sheets"] for r in sh["raters"] if any(v for v in r["ratings"].values()))
    preview = {"period": period, "departments_rated": len(parsed["sheets"]), "ratings_found": rated,
               "unknown_departments": unknown, "replaces_existing": bool(existing),
               "sheets": [{"department": sh["receiver"], "raters": [r["name"] for r in sh["raters"]]}
                          for sh in parsed["sheets"]]}
    if not apply:
        return preview
    if unknown and not create_missing:
        raise HTTPException(status_code=422,
                            detail="These departments are not in the department list: " + ", ".join(unknown)
                            + ". Tick 'add missing departments' or rename them in the file.")
    if unknown:
        from app.services.hrms_masters_service import create_master
        for n in unknown:
            await create_master("department", cid, {"name": n, "active": True}, user)
        depts = {_norm(d["name"]): d for d in await S.departments(cid)}

    now = datetime.now(timezone.utc)
    pairs, subs, notes = [], [], []
    for sh in parsed["sheets"]:
        r_d = depts[_norm(sh["receiver"])]
        for n in sh["notes"]:
            notes.append({"receiver_dept_id": r_d["id"], "parameter": n["parameter"], "text": n["text"]})
        for rater in sh["raters"]:
            g_d = depts[_norm(rater["name"])]
            if g_d["id"] == r_d["id"]:
                continue
            has = any(v is not None for v in rater["ratings"].values())
            pairs.append({"giver_dept_id": g_d["id"], "giver_name": g_d["name"], "receiver_dept_id": r_d["id"],
                          "receiver_name": r_d["name"], "rater_user_id": None, "rater_name": None,
                          "rater_email": None, "status": "Completed" if has else "Not rated",
                          "submitted_at": now if has else None, "event_id": None, "event_coll": None})
            if has:
                subs.append({"company_id": cid, "period": period, "giver_dept_id": g_d["id"],
                             "giver_name": g_d["name"], "receiver_dept_id": r_d["id"], "receiver_name": r_d["name"],
                             "rater_user_id": None, "ratings": rater["ratings"], "comments": {},
                             "strength": rater["strength"], "improvement": rater["improvement"],
                             "submitted_at": now, "source": "import"})
    cycles = get_collection(S.COLL_CYCLES)
    fields = {"pairs": pairs, "parameters": st["parameters"], "imported_notes": notes, "status": S.CYCLE_COMPLETED,
              "source": "import", "completed_at": now, "imported_by": str(user.get("_id") or ""),
              "imported_at": now, "imported_file": filename}
    if existing:
        await cycles.update_one({"_id": existing["_id"]}, {"$set": fields})
        cycle_id = existing["_id"]
        await get_collection(S.COLL_SUBMISSIONS).delete_many({"cycle_id": str(cycle_id)})
    else:
        res = await cycles.insert_one({"company_id": cid, "period": period,
                                       "name": f"Inter-Departmental Feedback {period} (imported)",
                                       "start_date": None, "deadline": None, "created_at": now,
                                       "report_sent_at": None, **fields})
        cycle_id = res.inserted_id
    for s in subs:
        s["cycle_id"] = str(cycle_id)
    if subs:
        await get_collection(S.COLL_SUBMISSIONS).insert_many(subs)
    cycle = await cycles.find_one({"_id": cycle_id})
    actions = await generate_actions(cycle)
    await S.audit(cid, user, "feedback imported", {"cycle_id": str(cycle_id), "period": period,
                                                  "ratings": len(subs), "file": filename})
    return {**preview, "imported": True, "cycle_id": str(cycle_id), "ratings_imported": len(subs),
            "actions_generated": actions}
