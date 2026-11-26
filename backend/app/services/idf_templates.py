"""Inter-Departmental Feedback — the BUILT-IN email templates.

These are only the defaults: every one of them is listed under Notification Templates ▸
Inter-Departmental Feedback, where an admin edits the subject and body (company-wide or for one
company) or switches an email off. The sending code holds no wording — it picks the template by
its slug and fills the {{placeholders}} (idf_process.idf_mail).

List-type values (form links, changes, relationships) arrive pre-rendered as HTML in a single
placeholder, because templates have no loops.
"""

# Trigger slug -> the placeholders its sending code fills (shown in the template editor).
IDF_TRIGGER_VARIABLES = {
    "idf_cycle_started": ["name", "cycle_month", "deadline", "form_links"],
    "idf_due_soon": ["name", "cycle_month", "deadline", "form_links"],
    "idf_overdue": ["name", "cycle_month", "deadline", "form_links"],
    "idf_link_resend": ["name", "cycle_month", "deadline", "form_links"],
    "idf_md_report": ["name", "cycle_month", "results_meeting_date"],
    "idf_you_said_request": ["name", "department", "score", "band", "cycle_month", "due_date"],
    "idf_you_said_shared": ["name", "department", "cycle_month", "changes", "note"],
    "idf_you_said_overdue": ["name", "department", "due_date"],
    "idf_issue_raised": ["name", "raised_by", "about_department", "description", "suggestion"],
    "idf_issue_resolved": ["name", "about_department", "note"],
    "idf_cycle_due": ["name", "cycle_month", "rule"],
    "idf_pulse_due": ["name", "cycle_month", "relationships"],
    "idf_action_overdue": ["name", "department", "action_type", "target_date", "status"],
    "idf_action_review_due": ["name", "department", "action_type", "review_cadence", "review_date"],
}

_SIGN = "<p>Regards,<br>Inter-Departmental Feedback</p>"

IDF_DEFAULT_TEMPLATES = {
    "idf_cycle_started_email": {
        "subject": "Inter-Departmental Feedback: your feedback is requested ({{cycle_month}})",
        "body": ("<p>Dear {{name}},</p>"
                 "<p>A new Inter-Departmental Feedback cycle has started. Deadline: <b>{{deadline}}</b>.</p>"
                 "<p>Please rate:</p>{{form_links}}"
                 "<p>Each link opens your form directly (log in if asked). You can also use "
                 "<b>Inter-Department Feedback ▸ My Feedback Forms</b>. The links are personal — please do not "
                 "forward them. Your individual feedback is confidential.</p>" + _SIGN),
    },
    "idf_due_soon_email": {
        "subject": "Reminder: Inter-Departmental Feedback due {{deadline}}",
        "body": ("<p>Dear {{name}},</p><p>Your Inter-Departmental Feedback is due soon — deadline "
                 "<b>{{deadline}}</b>.</p><p>Still to submit:</p>{{form_links}}" + _SIGN),
    },
    "idf_overdue_email": {
        "subject": "Overdue: Inter-Departmental Feedback not yet submitted",
        "body": ("<p>Dear {{name}},</p><p>Your Inter-Departmental Feedback is overdue (deadline "
                 "<b>{{deadline}}</b>) — please submit it today.</p>{{form_links}}"
                 "<p>You will get this reminder every day until it is submitted.</p>" + _SIGN),
    },
    "idf_link_resend_email": {
        "subject": "Inter-Departmental Feedback: your feedback form link",
        "body": ("<p>Dear {{name}},</p><p>Here is your Inter-Departmental Feedback form link again. "
                 "Deadline: <b>{{deadline}}</b>.</p>{{form_links}}" + _SIGN),
    },
    "idf_md_report_email": {
        "subject": "Confidential: Inter-Departmental Feedback report — {{cycle_month}}",
        "body": ("<p>Dear {{name}},</p><p>All feedback for the <b>{{cycle_month}}</b> Inter-Departmental Feedback "
                 "cycle has been submitted. The complete report package is attached: the compiled feedback "
                 "(Excel), the analysis (Excel) and the report (PDF). The action plan has been generated "
                 "automatically.</p>"
                 "<p>The results meeting with all HODs is in your calendar on <b>{{results_meeting_date}}</b>. "
                 "Please open it by stating: no retaliation — honest feedback is thanked, never held against "
                 "anyone.</p><p>This report is sent to you only. The full dashboard is in "
                 "<b>Inter-Department Feedback ▸ Dashboard</b>.</p>" + _SIGN),
    },
    "idf_you_said_request_email": {
        "subject": "You said, we did — tell the raters what will change ({{cycle_month}})",
        "body": ("<p>Dear {{name}},</p><p>The Inter-Departmental Feedback results for <b>{{department}}</b> are "
                 "out ({{score}}, {{band}}).</p><p>Within 15 days (by <b>{{due_date}}</b>) please tell the "
                 "departments that rated you what will change and by when: <b>Inter-Department Feedback ▸ "
                 "My Feedback Forms ▸ You said, we did</b>.</p>" + _SIGN),
    },
    "idf_you_said_shared_email": {
        "subject": "You said, we did — {{department}}",
        "body": ("<p>Dear {{name}},</p><p><b>{{department}}</b> has answered the feedback your department gave "
                 "in the {{cycle_month}} cycle. What will change:</p>{{changes}}<p>{{note}}</p>"
                 "<p>Thank you for the honest feedback.</p>" + _SIGN),
    },
    "idf_you_said_overdue_email": {
        "subject": "Overdue: you said, we did — {{department}}",
        "body": ("<p>Dear {{name}},</p><p>The raters of <b>{{department}}</b> are waiting to hear what will "
                 "change (due {{due_date}}). Please answer in <b>Inter-Department Feedback ▸ My Feedback "
                 "Forms ▸ You said, we did</b>.</p>" + _SIGN),
    },
    "idf_issue_raised_email": {
        "subject": "New inter-department issue about {{about_department}}",
        "body": ("<p>Dear {{name}},</p><p>{{raised_by}} raised an inter-department issue about "
                 "<b>{{about_department}}</b>:</p><blockquote>{{description}}</blockquote>"
                 "<p>Suggested change: {{suggestion}}</p><p>Please bring it to the weekly WRM: "
                 "<b>Inter-Department Feedback ▸ Raised Issues</b>.</p>" + _SIGN),
    },
    "idf_issue_resolved_email": {
        "subject": "Your inter-department issue about {{about_department}} is resolved",
        "body": ("<p>Dear {{name}},</p><p>The issue you raised about <b>{{about_department}}</b> has been "
                 "resolved.</p><p>{{note}}</p><p>Thank you for raising it.</p>" + _SIGN),
    },
    "idf_cycle_due_email": {
        "subject": "Inter-Departmental Feedback: the {{cycle_month}} cycle is due",
        "body": ("<p>Dear {{name}},</p><p>The next feedback cycle is due ({{rule}}).</p><p>Start it in "
                 "<b>Inter-Department Feedback ▸ Feedback Cycles</b>.</p>" + _SIGN),
    },
    "idf_pulse_due_email": {
        "subject": "Inter-Departmental Feedback: pulse re-score due",
        "body": ("<p>Dear {{name}},</p><p>30 days have passed since the {{cycle_month}} results. Re-score these "
                 "relationships (same questions, affected departments only):</p>{{relationships}}"
                 "<p><b>Feedback Cycles ▸ Start pulse re-score</b>.</p>" + _SIGN),
    },
    "idf_action_overdue_email": {
        "subject": "Overdue: Inter-Departmental Feedback action — {{department}}",
        "body": ("<p>Dear {{name}},</p><p>The improvement action for <b>{{department}}</b> ({{action_type}}) "
                 "was due on {{target_date}} and is still {{status}}.</p><p>Please update its progress in "
                 "<b>Inter-Department Feedback ▸ My Actions</b>.</p>" + _SIGN),
    },
    "idf_action_review_due_email": {
        "subject": "Review due: Inter-Departmental Feedback action — {{department}}",
        "body": ("<p>Dear {{name}},</p><p>The {{review_cadence}} review of the improvement action for "
                 "<b>{{department}}</b> ({{action_type}}) is due ({{review_date}}).</p><p>Please add a "
                 "progress update in <b>Inter-Department Feedback ▸ My Actions</b>.</p>" + _SIGN),
    },
}
