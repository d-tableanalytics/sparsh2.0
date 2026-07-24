const SS_ID = '1HiRCcWd8vLLMAb8cJ1pQ3WKbXR-TUNsuxfIt3h6fXrg';
const SHEET_EMPLOYEES = 'Company_Employees';
const SHEET_QUESTIONS = 'Implementation_update_feedback_question';
const SHEET_RESPONSES = 'Implementation_update_feedback_Responses';

// ---------------- Notification config ----------------
const FORM_TYPE       = 'Implementation Update Feedback';
const SHEET_STAFF     = 'Staff';
const SHEET_COMPANIES = 'Companies';
const SHEET_TEMPLATES = 'HOD_Form_mail_templates';
const ADMIN_ROLE      = 'Admin';

// Template column in HOD_Form_mail_templates (add this header). Falls back to default body if missing.
const TPL_FEEDBACK_COL = 'Implementation_feedback_mail_template';

const MAIL = { FROM_NAME: 'Implementation Feedback Automation', REPLY_TO: 'automation@sparshmagic.com' };
const SHEET_MAIL_LOG = 'HOD_Form_mail_logs';
const MAIL_LOG_HEADERS = ['Log_ID','Timestamp','Form_Type','Month','Company_ID','Company_Name',
  'MD_ID','MD_Name','Side','Recipient_Name','Recipient_Email','Subject','Status','Error'];

function getSS_() {
  return SS_ID ? SpreadsheetApp.openById(SS_ID) : SpreadsheetApp.getActiveSpreadsheet();
}

function doGet(e) {
  const p = (e && e.parameter) || {};
  const t = HtmlService.createTemplateFromFile('Index');
  t.CID = (p.CID || '').trim();
  t.EID = (p.EID || '').trim();
  t.MID = (p.MID || '').trim();
  return t.evaluate()
    .setTitle('Implementation Update Feedback')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function readSheetObjects_(sheet) {
  const values = sheet.getDataRange().getValues();
  if (values.length < 2) return { headers: (values[0] || []).map(h => String(h).trim()), rows: [] };
  const headers = values[0].map(h => String(h).trim());
  const rows = [];
  for (let i = 1; i < values.length; i++) {
    const obj = {};
    headers.forEach((h, j) => obj[h] = values[i][j]);
    rows.push(obj);
  }
  return { headers, rows };
}

function getFormData(cid, eid, mid) {
  try {
    cid = String(cid || '').trim();
    eid = String(eid || '').trim();
    mid = String(mid || '').trim();
    if (!eid) return { ok: false, error: 'Missing EID (MD Employee ID) in URL.' };
    if (!mid) return { ok: false, error: 'Missing MID (month) in URL, e.g. &MID=jan26.' };

    const ss = getSS_();
    const empSheet = ss.getSheetByName(SHEET_EMPLOYEES);
    if (!empSheet) return { ok: false, error: 'Sheet not found: ' + SHEET_EMPLOYEES };

    const allEmp = readSheetObjects_(empSheet).rows;
    // Find the MD by Employee_ID (optionally scoped by CID if provided)
    const md = allEmp.find(r => String(r.Employee_ID).trim() === eid &&
                                (!cid || String(r.Company_ID).trim() === cid));
    if (!md) return { ok: false, error: 'MD not found for EID: ' + eid };

    // If CID wasn't passed, derive it from the MD's row
    if (!cid) cid = String(md.Company_ID).trim();

    const qSheet = ss.getSheetByName(SHEET_QUESTIONS);
    if (!qSheet) return { ok: false, error: 'Sheet not found: ' + SHEET_QUESTIONS };

    const existing = getExistingResponses_(ss, cid, eid, mid);

    return {
      ok: true,
      company: cid,
      month: mid,
      md: { id: eid, name: String(md.Employee_Name).trim() },
      questions: mapQuestions_(readSheetObjects_(qSheet)),
      submitted: existing.submitted,
      answers: existing.answers,            // { questionId: {checked, remark} }
      answersByText: existing.answersByText,// { questionText: {checked, remark} }
      submittedOn: existing.submittedOn
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

function getExistingResponses_(ss, cid, eid, mid) {
  const sheet = ss.getSheetByName(SHEET_RESPONSES);
  if (!sheet || sheet.getLastRow() < 2) return { submitted: false, answers: {}, answersByText: {}, submittedOn: '', count: 0 };

  const data = readSheetObjects_(sheet);
  const H = data.headers;
  const compH  = H.find(h => h.toLowerCase() === 'company_id');
  const mdH    = H.find(h => h.toLowerCase() === 'md_id');
  const monthH = H.find(h => h.toLowerCase() === 'month');
  const qH     = H.find(h => h.toLowerCase() === 'question_id');
  const qtH    = H.find(h => h.toLowerCase() === 'question');
  const aH     = H.find(h => h.toLowerCase() === 'answer');
  const rmH    = H.find(h => h.toLowerCase() === 'remark');
  const tH     = H.find(h => h.toLowerCase() === 'timestamp');

  const want = monthKey_(mid);
  const answers = {}, answersByText = {};
  let submitted = false, submittedOn = '', count = 0;

  data.rows.forEach(r => {
    if (String(r[compH] || '').trim() !== cid) return;
    if (String(r[mdH]   || '').trim() !== eid) return;
    if (!monthH || monthKey_(r[monthH]) !== want) return;

    submitted = true; count++;
    if (!submittedOn && tH) submittedOn = String(r[tH] || '');
    const qid   = String(r[qH]  || '').trim();
    const qtext = qtH ? String(r[qtH] || '').trim() : '';
    const ans   = String(r[aH]  || '').trim().toLowerCase() === 'yes';
    const rmk   = rmH ? String(r[rmH] || '') : '';
    const obj = { checked: ans, remark: rmk };
    if (qid)   answers[qid] = obj;
    if (qtext) answersByText[qtext] = obj;
  });

  return { submitted, answers, answersByText, submittedOn, count };
}

function monthKey_(v) {
  if (v instanceof Date) {
    const mon = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][v.getMonth()];
    return mon + String(v.getFullYear()).slice(-2);
  }
  return String(v == null ? '' : v).trim().toLowerCase();
}

function mapQuestions_(qData) {
  const headers = qData.headers;
  const find = cands => headers.find(h => cands.indexOf(h.toLowerCase()) !== -1);
  const idH = find(['question_id', 'id', 'q_id', 'qid']) || headers[0];
  const titleH = find(['question', 'title', 'question_title']) || headers[1] || headers[0];
  const descH = find(['description', 'subtitle', 'detail', 'details', 'sub_title', 'help']);
  const activeH = find(['active', 'status', 'is_active', 'enabled']);

  const out = [];
  qData.rows.forEach((r, i) => {
    if (activeH) {
      const v = String(r[activeH]).trim().toLowerCase();
      if (['false', 'no', '0', 'inactive', 'disabled'].indexOf(v) !== -1) return;
    }
    const title = String(r[titleH] || '').trim();
    if (!title) return;
    out.push({
      id: String(r[idH] || ('Q' + (i + 1))).trim(),
      title: title,
      desc: descH ? String(r[descH] || '').trim() : ''
    });
  });
  return out;
}

function submitResponses(payload) {
  try {
    const cid = String(payload.company || '').trim();
    const mdId = String(payload.mdId || '').trim();
    const mdName = String(payload.mdName || '').trim();
    const mid = String(payload.month || '').trim();
    const answers = payload.answers || [];   // [{questionId, question, checked, remark}]
    if (!cid || !mdId) return { ok: false, error: 'Missing company or MD.' };
    if (!mid) return { ok: false, error: 'Missing month.' };
    if (!answers.length) return { ok: false, error: 'Nothing to submit.' };

    const ss = getSS_();
    const existing = getExistingResponses_(ss, cid, mdId, mid);
    const has = (qid, qtext) => (existing.answers[String(qid)] != null) ||
                                (existing.answersByText[String(qtext)] != null);

    // Only append questions not already saved (slot-by-slot)
    const newAnswers = answers.filter(a => !has(a.questionId, a.question));
    if (!newAnswers.length)
      return { ok: false, error: 'Nothing new to save — all answered questions were already submitted for ' + mid + '.' };

    const headers = ['Timestamp', 'Month', 'Company_ID', 'MD_ID', 'MD_Name',
      'Question_ID', 'Question', 'Answer', 'Remark'];
    let sheet = ss.getSheetByName(SHEET_RESPONSES);
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_RESPONSES);
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sheet.setFrozenRows(1);
    } else if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sheet.setFrozenRows(1);
    }

    const map = getHeaderIndex_(sheet);
    const ts = new Date();
    const rows = newAnswers.map(a => {
      const row = new Array(sheet.getLastColumn()).fill('');
      const put = (h, v) => { if (map[h]) row[map[h] - 1] = v; };
      put('Timestamp', ts); put('Month', "'" + mid); put('Company_ID', cid);
      put('MD_ID', mdId); put('MD_Name', mdName);
      put('Question_ID', String(a.questionId)); put('Question', String(a.question));
      put('Answer', a.checked ? 'Yes' : 'No'); put('Remark', String(a.remark || ''));
      return row;
    });
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, sheet.getLastColumn()).setValues(rows);

    let mail = null;
    try { mail = sendNotification_(ss, cid, mdId, mdName, mid, newAnswers); }
    catch (mErr) { mail = { error: mErr.message }; }

    return { ok: true, count: rows.length, mail: mail };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

function getHeaderIndex_(sheet) {
  const headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0].map(h => String(h).trim());
  const map = {}; headers.forEach((h, i) => { if (h) map[h] = i + 1; });
  return map;
}

// ---------------- Mail notification ----------------

function sendNotification_(ss, cid, mdId, mdName, mid, answers) {
  let companyName = cid, compRow = null;
  const compSheet = ss.getSheetByName(SHEET_COMPANIES);
  if (compSheet) {
    compRow = readSheetObjects_(compSheet).rows.find(r => String(r.Company_ID).trim() === cid);
    if (compRow) companyName = String(compRow.Company_Name || compRow.Company_Short_Name || cid).trim();
  }

  const tz = Session.getScriptTimeZone();
  const map = {
    Company_ID: cid,
    Company_Name: companyName,
    Month: mid,
    MD_ID: mdId,
    MD_Name: mdName,
    Form_Type: FORM_TYPE,
    Submitted_On: Utilities.formatDate(new Date(), tz, 'dd MMM yyyy, hh:mm a'),
    Total_Answered: String(answers.length),
    Response_Table: buildResponseTable_(answers)
  };

  let subject = '[Implementation Feedback] ' + mdName + ' \u2013 ' + companyName + ' (' + mid + ')';
  let body = getTemplateByCol_(ss, TPL_FEEDBACK_COL);
  if (body) {
    const m = body.match(/^\s*Subject\s*:\s*(.+?)(\r?\n)/i);
    if (m) { subject = m[1].trim(); body = body.slice(m[0].length); }
  }
  subject = fill_(subject, map);

  const recipients = getRecipients_(ss, compRow);
  if (!recipients.length) {
    logMail_(ss, map, '-', '-', subject, 'Skipped', 'No recipients', '');
    return { mailed: 0, note: 'No recipients' };
  }

  let sent = 0;
  recipients.forEach(rc => {
    try {
      const m = Object.assign({ Recipient_Name: rc.name }, map);
      const html = body ? fill_(body, m) : defaultBody_(m);
      sendMail_(rc.email, subject, html);
      logMail_(ss, map, rc.side, rc.name, subject, 'Sent', '', rc.email);
      sent++;
    } catch (e) {
      logMail_(ss, map, rc.side, rc.name, subject, 'Failed', e.message, rc.email);
    }
  });
  return { mailed: sent, recipients: recipients.length };
}

function getRecipients_(ss, compRow) {
  const out = [], seen = {};
  const push = (name, email, side) => {
    email = String(email || '').trim();
    if (!isEmail_(email) || seen[email.toLowerCase()]) return;
    seen[email.toLowerCase()] = true;
    out.push({ name: String(name || '').trim() || email, email: email, side: side });
  };

  const staffSheet = ss.getSheetByName(SHEET_STAFF);
  const staffRows = staffSheet ? readSheetObjects_(staffSheet).rows : [];

  staffRows.forEach(r => {
    if (String(r.Staff_Role || '').trim().toLowerCase() === ADMIN_ROLE.toLowerCase())
      push(r.Staff_name, r.Staff_Email, 'Admin');
  });

  if (compRow) {
    const smopsKey = Object.keys(compRow).find(k => /smops/i.test(k)) || 'Staff_ID(SMOps)';
    String(compRow[smopsKey] || '').split(/[,;|]+/).map(s => s.trim()).filter(Boolean).forEach(id => {
      const s = staffRows.find(r => String(r.Staff_ID).trim() === id);
      if (s) push(s.Staff_name, s.Staff_Email, 'SMOps');
    });
  }
  return out;
}

function getTemplateByCol_(ss, colName) {
  const sh = ss.getSheetByName(SHEET_TEMPLATES);
  if (!sh) return '';
  const data = readSheetObjects_(sh);
  const header = data.headers.find(h => h.toLowerCase() === String(colName).toLowerCase());
  if (!header) return '';
  for (const r of data.rows) { const v = String(r[header] || '').trim(); if (v) return v; }
  return '';
}

function logMail_(ss, map, side, name, subject, status, error, email) {
  try {
    let sh = ss.getSheetByName(SHEET_MAIL_LOG);
    if (!sh) {
      sh = ss.insertSheet(SHEET_MAIL_LOG);
      sh.getRange(1, 1, 1, MAIL_LOG_HEADERS.length).setValues([MAIL_LOG_HEADERS]).setFontWeight('bold');
      sh.setFrozenRows(1);
    } else if (sh.getLastRow() === 0) {
      sh.getRange(1, 1, 1, MAIL_LOG_HEADERS.length).setValues([MAIL_LOG_HEADERS]).setFontWeight('bold');
      sh.setFrozenRows(1);
    }
    const ts = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    sh.appendRow(['LOG-' + Date.now() + '-' + Math.floor(Math.random() * 1000), ts, map.Form_Type,
      map.Month || '', map.Company_ID, map.Company_Name, map.MD_ID, map.MD_Name,
      side, name, email || '', subject, status, error || '']);
  } catch (e) { Logger.log('logMail_: ' + e.message); }
}

// ---------------- Mail helpers ----------------

function fill_(tpl, map) {
  return String(tpl || '').replace(/\{\{\s*(\w+)\s*\}\}/g, (m, k) => (map[k] !== undefined ? map[k] : m));
}

function sendMail_(to, subject, html) {
  MailApp.sendEmail({
    to: to, subject: subject,
    htmlBody: html.indexOf('<') !== -1 ? html : html.replace(/\n/g, '<br>'),
    name: MAIL.FROM_NAME, replyTo: MAIL.REPLY_TO
  });
}

function isEmail_(s) { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(s || '').trim()); }

function buildResponseTable_(answers) {
  let html = '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px;margin-top:8px">';
  html += '<tr>'
       +  '<th align="left" style="border:1px solid #e0e0e0;padding:8px 10px;background:#f5f5f5;">Question</th>'
       +  '<th style="border:1px solid #e0e0e0;padding:8px 10px;background:#f5f5f5;width:70px;">Answer</th>'
       +  '<th align="left" style="border:1px solid #e0e0e0;padding:8px 10px;background:#f5f5f5;">Remark</th></tr>';
  answers.forEach((a, i) => {
    const yes = !!a.checked;
    const badge = yes
      ? '<span style="color:#15803d;font-weight:700">✓ Yes</span>'
      : '<span style="color:#b91c1c;font-weight:700">✕ No</span>';
    html += '<tr>'
      + '<td style="border:1px solid #e0e0e0;padding:8px 10px;">' + (i + 1) + '. ' + escHtml_(a.question) + '</td>'
      + '<td align="center" style="border:1px solid #e0e0e0;padding:8px 10px;">' + badge + '</td>'
      + '<td style="border:1px solid #e0e0e0;padding:8px 10px;color:#475569;">' + escHtml_(a.remark || '') + '</td></tr>';
  });
  html += '</table>';
  return html;
}

function defaultBody_(map) {
  return '<div style="font-family:Arial,sans-serif;font-size:14px;color:#202124;">'
    + '<p>Hi ' + escHtml_(map.Recipient_Name || 'Team') + ',</p>'
    + '<p>The MD has submitted <b>Implementation Update Feedback</b> for <b>' + escHtml_(map.Month) + '</b>.</p>'
    + '<table style="font-size:14px;border-collapse:collapse;">'
    + row_('Company', '<b>' + escHtml_(map.Company_Name) + '</b> (' + escHtml_(map.Company_ID) + ')')
    + row_('Month', escHtml_(map.Month))
    + row_('MD', '<b>' + escHtml_(map.MD_Name) + '</b> (' + escHtml_(map.MD_ID) + ')')
    + row_('Submitted', escHtml_(map.Submitted_On))
    + row_('Answered', map.Total_Answered)
    + '</table>' + map.Response_Table + '</div>';
}

function row_(k, v) {
  return '<tr><td style="padding:2px 14px 2px 0;color:#5f6368;">' + k + '</td><td>' + v + '</td></tr>';
}

function escHtml_(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}