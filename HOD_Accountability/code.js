const SS_ID = '1HiRCcWd8vLLMAb8cJ1pQ3WKbXR-TUNsuxfIt3h6fXrg';
const SHEET_EMPLOYEES = 'Company_Employees';
const SHEET_QUESTIONS = 'HOD_Accountability_Question';
const SHEET_RESPONSES = 'HOD_Accountability_Responses';

// ---------------- Notification config ----------------
const FORM_TYPE       = 'Accountability';
const SHEET_STAFF     = 'Staff';
const SHEET_COMPANIES = 'Companies';
const SHEET_TEMPLATES = 'HOD_Form_mail_templates';
const ADMIN_ROLE      = 'Admin';

// HOD-summary template column (to Admin/SMOps) and per-employee template column.
// Your sheet has spelling quirks, so each clone sets these explicitly:
const TPL_HOD_COL      = 'Accountability_Response_mail_template';
const TPL_EMP_COL      = 'Employee_Accontability_response_mail_template'; // note: "Accontability" as in your sheet

const MAIL = { FROM_NAME: 'HOD Checklist Automation', REPLY_TO: 'automation@sparshmagic.com' };
const SHEET_MAIL_LOG = 'HOD_Form_mail_logs';
const MAIL_LOG_HEADERS = ['Log_ID','Timestamp','Form_Type','Month','Company_ID','Company_Name',
  'HOD_ID','HOD_Name','Side','Recipient_Name','Recipient_Email','Subject','Status','Error'];

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
    .setTitle(FORM_TYPE + ' Checklist')
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
    if (!cid || !eid) return { ok: false, error: 'Missing CID or EID in URL.' };
    if (!mid) return { ok: false, error: 'Missing MID (month) in URL, e.g. &MID=jan26.' };

    const ss = getSS_();
    const empSheet = ss.getSheetByName(SHEET_EMPLOYEES);
    if (!empSheet) return { ok: false, error: 'Sheet not found: ' + SHEET_EMPLOYEES };

    const all = readSheetObjects_(empSheet).rows
      .filter(r => String(r.Company_ID).trim() === cid);

    const hod = all.find(r => String(r.Employee_ID).trim() === eid);
    if (!hod) return { ok: false, error: 'HOD not found for EID: ' + eid };

    const team = all.filter(r => {
      if (String(r.Employee_ID).trim() === eid) return false;
      const ids = String(r.HOD_IDs || '').split(/[,;|]+/).map(s => s.trim());
      return ids.indexOf(eid) !== -1;
    }).map(r => ({
      id: String(r.Employee_ID).trim(),
      name: String(r.Employee_Name).trim(),
      designation: String(r.Designation || '').trim(),
      level: String(r.Level || '').trim()
    }));

    const qSheet = ss.getSheetByName(SHEET_QUESTIONS);
    if (!qSheet) return { ok: false, error: 'Sheet not found: ' + SHEET_QUESTIONS };

    // Check for an existing submission (same CID + HOD + Month) → prefill
    const existing = getExistingResponses_(ss, cid, eid, mid);

    return {
      ok: true,
      company: cid,
      month: mid,
      hod: { id: eid, name: String(hod.Employee_Name).trim() },
      team: team,
      questions: mapQuestions_(readSheetObjects_(qSheet)),
      submitted: existing.submitted,
      ratings: existing.ratings,
      ratingsByText: existing.ratingsByText,
      submittedOn: existing.submittedOn
    };
  } catch (err) {
    return { ok: false, error: err.message };
  }
}

function getExistingResponses_(ss, cid, eid, mid) {
  Logger.log('=== getExistingResponses_ START ===');
  Logger.log('Looking for → CID="%s" EID="%s" MID="%s"', cid, eid, mid);

  const sheet = ss.getSheetByName(SHEET_RESPONSES);
  if (!sheet) { Logger.log('ABORT: sheet "%s" not found', SHEET_RESPONSES); return { submitted:false, ratings:{}, ratingsByText:{}, submittedOn:'', count:0 }; }
  if (sheet.getLastRow() < 2) { Logger.log('ABORT: sheet has no data rows (lastRow=%s)', sheet.getLastRow()); return { submitted:false, ratings:{}, ratingsByText:{}, submittedOn:'', count:0 }; }

  const data = readSheetObjects_(sheet);
  const H = data.headers;
  Logger.log('Headers found: %s', JSON.stringify(H));

  const compH  = H.find(h => h.toLowerCase() === 'company_id');
  const hodH   = H.find(h => h.toLowerCase() === 'hod_id');
  const monthH = H.find(h => h.toLowerCase() === 'month');
  const qH     = H.find(h => h.toLowerCase() === 'question_id');
  const qtH    = H.find(h => h.toLowerCase() === 'question');
  const eH     = H.find(h => h.toLowerCase() === 'employee_id');
  const rH     = H.find(h => h.toLowerCase() === 'rating');
  const tH     = H.find(h => h.toLowerCase() === 'timestamp');

  Logger.log('Resolved cols → company_id="%s" hod_id="%s" month="%s" question_id="%s" employee_id="%s" rating="%s"',
    compH, hodH, monthH, qH, eH, rH);
  if (!compH || !hodH || !monthH) Logger.log('WARNING: a key column is MISSING (company/hod/month). Check exact header spelling.');

  const want = String(mid).trim().toLowerCase();
  const ratings = {}, ratingsByText = {};
  let submitted = false, submittedOn = '', count = 0, scanned = 0;

  data.rows.forEach((r, i) => {
    scanned++;
    const rowCid   = String(r[compH]  || '').trim();
    const rowHod   = String(r[hodH]   || '').trim();
    const rowMonth = monthH ? monthKey_(r[monthH]) : '(no month col)';

    const cidOK   = rowCid === cid;
    const hodOK   = rowHod === eid;
    const monthOK = monthH ? (rowMonth === want) : false;

    // Log only the first few rows and any near-misses, to avoid spamming
    if (i < 5 || (cidOK && hodOK)) {
      Logger.log('Row %s: cid="%s"(%s) hod="%s"(%s) month="%s"(%s)',
        i, rowCid, cidOK, rowHod, hodOK, rowMonth, monthOK);
    }

    if (!cidOK || !hodOK || !monthOK) return;

    submitted = true; count++;
    if (!submittedOn && tH) submittedOn = String(r[tH] || '');
    const qid   = String(r[qH]  || '').trim();
    const qtext = qtH ? String(r[qtH] || '').trim() : '';
    const empId = String(r[eH]  || '').trim();
    const val   = Number(r[rH]);
    (ratings[qid] = ratings[qid] || {})[empId] = val;
    if (qtext) (ratingsByText[qtext] = ratingsByText[qtext] || {})[empId] = val;
  });

  Logger.log('Scanned %s rows. MATCHED %s. submitted=%s', scanned, count, submitted);
  Logger.log('ratings keys (by Question_ID): %s', JSON.stringify(Object.keys(ratings)));
  Logger.log('ratingsByText keys (by Question text): %s', JSON.stringify(Object.keys(ratingsByText)));
  Logger.log('=== getExistingResponses_ END ===');

  return { submitted, ratings, ratingsByText, submittedOn, count };
}

// Turns a Month cell into a canonical token like "jun26", whether it's text or an auto-converted Date.
function monthKey_(v) {
  if (v instanceof Date) {
    const mon = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][v.getMonth()];
    return mon + String(v.getFullYear()).slice(-2);
  }
  return String(v == null ? '' : v).trim().toLowerCase();
}


function TEST_existing() {
  const ss = getSS_();
  const res = getExistingResponses_(ss, 'PTOP001', 'EMP_223', 'jun26');
  Logger.log('RESULT submitted=%s count=%s', res.submitted, res.count);
  Logger.log('RESULT ratings=%s', JSON.stringify(res.ratings));
  Logger.log('RESULT ratingsByText=%s', JSON.stringify(res.ratingsByText));
}

// Auto-detects column names so it works whatever your question sheet headers are.
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
    const hodId = String(payload.hodId || '').trim();
    const hodName = String(payload.hodName || '').trim();
    const mid = String(payload.month || '').trim();
    const ratings = payload.ratings || [];
    if (!cid || !hodId) return { ok: false, error: 'Missing company or HOD.' };
    if (!mid) return { ok: false, error: 'Missing month.' };
    if (!ratings.length) return { ok: false, error: 'No ratings to save.' };

   const ss = getSS_();

    // Load what's already saved for this CID+HOD+Month, so we only append NEW cells.
    const existing = getExistingResponses_(ss, cid, hodId, mid);
    const has = (qid, qtext, empId) => {
      const byId = existing.ratings[String(qid)];
      if (byId && byId[empId] != null) return true;
      const byTx = existing.ratingsByText[String(qtext)];
      return !!(byTx && byTx[empId] != null);
    };

    // Keep only ratings that aren't already on file (prevents duplicates).
    const newRatings = ratings.filter(r => !has(r.questionId, r.question, r.employeeId));
    if (!newRatings.length)
      return { ok: false, error: 'Nothing new to save — all selected cells were already submitted for ' + mid + '.' };

    const headers = ['Timestamp', 'Month', 'Company_ID', 'HOD_ID', 'HOD_Name',
      'Question_ID', 'Question', 'Employee_ID', 'Employee_Name', 'Rating'];
    let sheet = ss.getSheetByName(SHEET_RESPONSES);
    if (!sheet) {
      sheet = ss.insertSheet(SHEET_RESPONSES);
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sheet.setFrozenRows(1);
    } else if (sheet.getLastRow() === 0) {
      sheet.getRange(1, 1, 1, headers.length).setValues([headers]).setFontWeight('bold');
      sheet.setFrozenRows(1);
    } else {
      ensureMonthColumn_(sheet); // back-compat if sheet predates the Month column
    }

    // Map by header so it works whether or not Month column is first
    const map = getHeaderIndex_(sheet);
    const ts = new Date();
    const rows = newRatings.map(r => {
      const row = new Array(sheet.getLastColumn()).fill('');
      const put = (h, v) => { if (map[h]) row[map[h] - 1] = v; };
      put('Timestamp', ts); put('Month', "'" + mid); put('Company_ID', cid);
      put('HOD_ID', hodId); put('HOD_Name', hodName);
      put('Question_ID', String(r.questionId)); put('Question', String(r.question));
      put('Employee_ID', String(r.employeeId)); put('Employee_Name', String(r.employeeName));
      put('Rating', Number(r.rating));
      return row;
    });
    sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, sheet.getLastColumn()).setValues(rows);

    let mail = null;
    try { mail = sendNotification_(ss, cid, hodId, hodName, mid, newRatings); }
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

function ensureMonthColumn_(sheet) {
  const map = getHeaderIndex_(sheet);
  if (!map['Month']) {
    sheet.insertColumnAfter(1);
    sheet.getRange(1, 2).setValue('Month').setFontWeight('bold');
  }
}

// ---------------- Mail notification ----------------

function sendNotification_(ss, cid, hodId, hodName, mid, ratings) {
  let companyName = cid, compRow = null;
  const compSheet = ss.getSheetByName(SHEET_COMPANIES);
  if (compSheet) {
    compRow = readSheetObjects_(compSheet).rows.find(r => String(r.Company_ID).trim() === cid);
    if (compRow) companyName = String(compRow.Company_Name || compRow.Company_Short_Name || cid).trim();
  }

  const tz = Session.getScriptTimeZone();
  const now = new Date();
  const baseMap = {
    Company_ID: cid,
    Company_Name: companyName,
    Month: mid,
    HOD_ID: hodId,
    HOD_Name: hodName,
    Form_Type: FORM_TYPE,
    Submitted_On: Utilities.formatDate(now, tz, 'dd MMM yyyy, hh:mm a'),
    Total_Ratings: String(ratings.length)
  };

  // ----- 1) HOD summary mail to Admin + SMOps -----
  const hodResult = sendHodSummary_(ss, compRow, baseMap, ratings);

  // ----- 2) Per-employee scorecard mails -----
  const empResult = sendEmployeeMails_(ss, cid, baseMap, ratings);

  return { hod: hodResult, employees: empResult };
}

function sendHodSummary_(ss, compRow, baseMap, ratings) {
  const map = Object.assign({ Response_Table: buildResponseTable_(ratings) }, baseMap);

  let subject = '[' + FORM_TYPE + ' Checklist] ' + map.HOD_Name + ' \u2013 ' + map.Company_Name + ' (' + map.Month + ')';
  let body = getTemplateByCol_(ss, TPL_HOD_COL);
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
      const html = body ? fill_(body, m) : defaultHodBody_(m);
      sendMail_(rc.email, subject, html);
      logMail_(ss, map, rc.side, rc.name, subject, 'Sent', '', rc.email);
      sent++;
    } catch (e) {
      logMail_(ss, map, rc.side, rc.name, subject, 'Failed', e.message, rc.email);
    }
  });
  return { mailed: sent, recipients: recipients.length };
}

function sendEmployeeMails_(ss, cid, baseMap, ratings) {
  const tpl = getTemplateByCol_(ss, TPL_EMP_COL);

  // employee email lookup
  const empSheet = ss.getSheetByName(SHEET_EMPLOYEES);
  const empRows = empSheet ? readSheetObjects_(empSheet).rows.filter(r => String(r.Company_ID).trim() === cid) : [];
  const emailById = {};
  empRows.forEach(r => { emailById[String(r.Employee_ID).trim()] = String(r.Employee_Email || '').trim(); });

  // group ratings by employee
  const byEmp = {}; // empId -> { name, items:[{question,rating}] }
  ratings.forEach(r => {
    const id = String(r.employeeId).trim();
    const e = byEmp[id] || (byEmp[id] = { name: String(r.employeeName).trim(), items: [] });
    e.items.push({ question: String(r.question), rating: Number(r.rating) });
  });

  let sent = 0, skipped = 0;
  Object.keys(byEmp).forEach(empId => {
    const emp = byEmp[empId];
    const email = emailById[empId];
    const avg = emp.items.reduce((s, x) => s + x.rating, 0) / emp.items.length;

    const map = Object.assign({}, baseMap, {
      Recipient_Name: emp.name,
      Employee_ID: empId,
      Employee_Name: emp.name,
      Average_Rating: (Math.round(avg * 10) / 10).toFixed(1),
      Total_Questions: String(emp.items.length),
      Score_Table: buildEmployeeTable_(emp.items)
    });

    let subject = 'Your ' + FORM_TYPE + ' rating for ' + map.Month + ' \u2013 ' + map.Company_Name;
    let body = tpl;
    if (body) {
      const m = body.match(/^\s*Subject\s*:\s*(.+?)(\r?\n)/i);
      if (m) { subject = m[1].trim(); body = body.slice(m[0].length); }
    }
    subject = fill_(subject, map);

    if (!isEmail_(email)) {
      logMail_(ss, map, 'Employee', emp.name, subject, 'Skipped', 'No email', email);
      skipped++; return;
    }
    try {
      const html = body ? fill_(body, map) : defaultEmployeeBody_(map);
      sendMail_(email, subject, html);
      logMail_(ss, map, 'Employee', emp.name, subject, 'Sent', '', email);
      sent++;
    } catch (e) {
      logMail_(ss, map, 'Employee', emp.name, subject, 'Failed', e.message, email);
    }
  });
  return { mailed: sent, skipped: skipped };
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
      map.Month || '', map.Company_ID, map.Company_Name, map.HOD_ID, map.HOD_Name,
      side, name, email || '', subject, status, error || '']);
  } catch (e) { Logger.log('logMail_: ' + e.message); }
}

// ---------------- Mail helpers ----------------

function fill_(tpl, map) {
  return String(tpl || '').replace(/\{\{\s*(\w+)\s*\}\}/g, (m, k) => (map[k] !== undefined ? map[k] : m));
}

function sendMail_(to, subject, html) {
  MailApp.sendEmail({
    to: to,
    subject: subject,
    htmlBody: html.indexOf('<') !== -1 ? html : html.replace(/\n/g, '<br>'),
    name: MAIL.FROM_NAME,
    replyTo: MAIL.REPLY_TO
  });
}

function isEmail_(s) { return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(s || '').trim()); }

// HOD summary: grouped by question
function buildResponseTable_(ratings) {
  const byQ = {}, order = [];
  ratings.forEach(r => { if (!byQ[r.question]) { byQ[r.question] = []; order.push(r.question); } byQ[r.question].push(r); });
  let html = '';
  order.forEach((q, i) => {
    html += '<div style="margin:16px 0 6px;font-weight:600;color:#202124;font-family:Arial,sans-serif;">' + (i + 1) + '. ' + escHtml_(q) + '</div>';
    html += '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px;">';
    html += '<tr><th align="left" style="border:1px solid #e0e0e0;padding:6px 10px;background:#f5f5f5;">Employee</th>'
         +  '<th style="border:1px solid #e0e0e0;padding:6px 10px;background:#f5f5f5;width:90px;">Rating</th></tr>';
    byQ[q].forEach(r => {
      html += '<tr><td style="border:1px solid #e0e0e0;padding:6px 10px;">' + escHtml_(r.employeeName) + '</td>'
           +  '<td align="center" style="border:1px solid #e0e0e0;padding:6px 10px;"><b>' + r.rating + '</b> / 5</td></tr>';
    });
    html += '</table>';
  });
  return html;
}

// Per-employee: their own questions & scores
function buildEmployeeTable_(items) {
  let html = '<table style="border-collapse:collapse;width:100%;font-family:Arial,sans-serif;font-size:13px;margin-top:8px">';
  html += '<tr><th align="left" style="border:1px solid #e0e0e0;padding:8px 10px;background:#f5f5f5;">Criteria</th>'
       +  '<th style="border:1px solid #e0e0e0;padding:8px 10px;background:#f5f5f5;width:90px;">Score</th></tr>';
  items.forEach(it => {
    html += '<tr><td style="border:1px solid #e0e0e0;padding:8px 10px;">' + escHtml_(it.question) + '</td>'
         +  '<td align="center" style="border:1px solid #e0e0e0;padding:8px 10px;"><b>' + it.rating + '</b> / 5</td></tr>';
  });
  html += '</table>';
  return html;
}

function defaultHodBody_(map) {
  return '<div style="font-family:Arial,sans-serif;font-size:14px;color:#202124;">'
    + '<p>Hi ' + escHtml_(map.Recipient_Name || 'Team') + ',</p>'
    + '<p>A new <b>' + escHtml_(map.Form_Type) + '</b> checklist has been submitted for <b>' + escHtml_(map.Month) + '</b>.</p>'
    + '<table style="font-size:14px;border-collapse:collapse;">'
    + row_('Company', '<b>' + escHtml_(map.Company_Name) + '</b> (' + escHtml_(map.Company_ID) + ')')
    + row_('Month', escHtml_(map.Month))
    + row_('HOD', '<b>' + escHtml_(map.HOD_Name) + '</b> (' + escHtml_(map.HOD_ID) + ')')
    + row_('Submitted', escHtml_(map.Submitted_On))
    + row_('Ratings', map.Total_Ratings)
    + '</table>' + map.Response_Table + '</div>';
}

function defaultEmployeeBody_(map) {
  return '<div style="font-family:Arial,sans-serif;font-size:14px;color:#202124;">'
    + '<p>Hi ' + escHtml_(map.Employee_Name || 'there') + ',</p>'
    + '<p>Here is your <b>' + escHtml_(map.Form_Type) + '</b> rating for <b>' + escHtml_(map.Month) + '</b> at ' + escHtml_(map.Company_Name) + '.</p>'
    + '<p>Average score: <b>' + escHtml_(map.Average_Rating) + ' / 5</b></p>'
    + map.Score_Table + '</div>';
}

function row_(k, v) {
  return '<tr><td style="padding:2px 14px 2px 0;color:#5f6368;">' + k + '</td><td>' + v + '</td></tr>';
}

function escHtml_(s) {
  return String(s == null ? '' : s).replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
}