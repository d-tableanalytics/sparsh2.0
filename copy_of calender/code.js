// Ek baar editor se RUN karo → Drive permission consent aayega → Allow.
function authorizeDrive(){
  const folder = getUploadFolder_();                 // upload folder resolve/test
  const name = folder.getName();
  DriveApp.getRootFolder();                           // ensures full Drive scope prompt
  Logger.log('Drive authorized ✔ — upload folder: ' + name);
  return 'Drive authorized ✔ — upload folder: ' + name;
}

/*****************  CONFIG  *****************/
const CFG = {
  SHEETS: {
    STAFF:      'Staff',
    COMPANIES:  'Companies',
    EMPLOYEES:  'Company_Employees',
    ACTIVITY:   'Activity',
    DEPARTMENT: 'Department',
    TEMPLATES:  'Templates',
    SCHEDULE:   'Calendar_Schedule',
    REMINDERS:  'Reminders'
  },
  HDR: {
    // Staff
    STAFF_ID:'Staff_ID', STAFF_NAME:'Staff_name', STAFF_EMAIL:'Staff_Email',
    STAFF_PASS:'Staff_Password', STAFF_DEPT:'Staff_department', STAFF_ROLE:'Staff_Role', STAFF_MOBILE:'Staff_Mobile',
    // Companies
    COMPANY_ID:'Company_ID', COMPANY_NAME:'Company_Name', COMPANY_SMOPS:'Staff_ID(SMOps)',
    // Company_Employees
    EMP_COMPANY_ID:'Company_ID', EMP_NAME:'Employee_Name', EMP_EMAIL:'Employee_Email',
    EMP_PASS:'Employee_Password', EMP_DEPT:'Department', EMP_ROLE:'Role',
    // Activity / Department
    ACTIVITIES:'Activities', ACTIVITIES_SHORTCUT:'Activity_Shortcut', DEPARTMENT:'Department'
  },
  MAIL: { FROM_NAME:'Sparsh Magic Automation', REPLY_TO:'automation@sparshmagic.com' },
  DEFAULT_REMIND_TIME: '09:00',
  SESSION_TTL: 21600   // 6h
};

const ROLES = { ADMIN:'Admin', STAFF:'Staff', LEARNER:'Learner' };

const SCHEDULE_HEADERS = [
  'Schedule_ID','Batch_ID','Title','Activity',
  'Event_Date','Event_Time','Company_ID','Company_Name',
  'Status','Departments','Company_Assigners','Staff_Assigner','Recurrence',
  'Plan_Start','Plan_End','Created_At','Created_By','Reschedule_Count','Completed_At','Comment','Completed_by',
  'Esc_Stage','Learner_Done','Learner_Done_By','Learner_Done_At'
];
const REMINDER_HEADERS = [
  'Reminder_ID','Schedule_ID','Batch_ID','Title','Activity',
  'Company_ID','Company_Name','Channel','Reminder_Type','Offset_Value',
  'Offset_Unit','Offset_Dir','Event_Date','Event_Time','Remind_At','Status',
  'Recipients_Company','Recipients_staff','Sent_At','Error','Created_At'
];
const SCHED_LOG_HEADERS = [
  'Log_ID','Batch_ID','Schedule_ID','Timestamp','Title','Activity',
  'Company_ID','Company_Name','Side','Recipient_Name','Recipient_Email',
  'Subject','Status','Error','Form_Link'
];

const HOD_FORMS = {
  'culture rating': [
    { label: 'Open Culture Rating Form', url: 'https://script.google.com/a/macros/sparshmagic.com/s/AKfycbzKX9r7Eohc7Ukf-bA-bY9Z44KKneqlS3JzpzVxI9m_/dev' }
  ],
  'accountability & ownership rating': [
    { label: 'Open Accountability Form', url: 'https://script.google.com/macros/s/AKfycbwvwWbBMnIHgQW6zL7JNVHM8YIF5o04vxj5n-_3xqXJ/dev' },
    { label: 'Open Ownership Form',      url: 'https://script.google.com/macros/s/AKfycbzuwT1F5Lo2Ked-8r7MqJ6as10GA6Bp-8OjNuOos5k/dev' }
  ],
  'implementation update feedback': [
    { label: 'Open Implementation Feedback Form', url: 'https://script.google.com/a/macros/sparshmagic.com/s/AKfycbwGD5es1K4c42bYnrmsfSrskdmQ0RTiaRSNVspR6Cwt/dev', noCid: true }
  ]
};


const WA = {
  PHONE_NUMBER_ID:      '1183237731536235',         
  BUSINESS_ACCOUNT_ID:  '901226946338803',              
  ACCESS_TOKEN:        'EAANeouiqG3oBRm3MUy82dsibWaq7vKGCIb9rEZAex76A5BtuofQ9MmP3bH2dNqEXnvfoMhdYd8ZAaBbZCRV05RqGN0D7L65scpMgd1wMO6uMZCZBlabgJIrZC8hay8UP0k5SKoE3hAC4rtAHBkVl4sO62fLNaeNTfZBA4UmU8CEig8eYOZAtaswS2dKjJZAcXBZCV1oQZDZD',  
  API_VERSION:          'v21.0',
  DEFAULT_COUNTRY_CODE: '91',
  ENABLED:              true,                        
  SHEET_TEMPLATES:      'Whatsapp_templates',
  SHEET_VARIABLES:      'WhatsappVariables'
};


const WA_TEMPLATE_HEADERS  = ['Action','Side','Meta_Template','Language','Variables','Active'];
const WA_VARIABLE_HEADERS  = ['Action','Side','Position','Variable','Source_Field'];
const WA_LOG_HEADERS       = ['Timestamp','Action','Side','Recipient','Phone','Schedule_ID','Form_URL','Status','Error'];



function ensureSchedLogSheet_(){ return ensureSheet_('Scheduled_logs', SCHED_LOG_HEADERS); }

/*****************  ENTRY / PAGES  *****************/
function doGet() {
  return HtmlService.createTemplateFromFile('Index')
    .evaluate()
    .setTitle('Schedule Dashboard')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}
function getPageContent(page) { return HtmlService.createTemplateFromFile(page).evaluate().getContent(); }
function include(filename)    { return HtmlService.createHtmlOutputFromFile(filename).getContent(); }

/*****************  AUTH (Staff sheet + Company_Employees sheet)  *****************/
function authenticateUser(username, password) {
  try {
    const u = String(username||'').trim().toLowerCase();
    const p = String(password||'');

    // 1) Staff sheet -> Admin or Staff
    const st = readObjects_(CFG.SHEETS.STAFF);
    for (const o of st.rows) {
      if (String(o[CFG.HDR.STAFF_EMAIL]||'').trim().toLowerCase() === u &&
          String(o[CFG.HDR.STAFF_PASS]||'') === p) {
        const rawRole = String(o[CFG.HDR.STAFF_ROLE]||'').trim();
        const role = (rawRole.toLowerCase() === 'admin') ? ROLES.ADMIN : ROLES.STAFF;
        const userData = {
          username: o[CFG.HDR.STAFF_NAME] || username,
          email:    o[CFG.HDR.STAFF_EMAIL],
          role:     role,
          rawRole:  rawRole,
          staffId:  o[CFG.HDR.STAFF_ID] || '',
          companyId:'',
          side:     'staff'
        };
        return finishLogin_(userData);
      }
    }

    // 2) Company_Employees sheet -> Learner
    const em = readObjects_(CFG.SHEETS.EMPLOYEES);
    for (const o of em.rows) {
      if (String(o[CFG.HDR.EMP_EMAIL]||'').trim().toLowerCase() === u &&
          String(o[CFG.HDR.EMP_PASS]||'') === p) {
        const userData = {
          username: o[CFG.HDR.EMP_NAME] || username,
          email:    o[CFG.HDR.EMP_EMAIL],
          role:     ROLES.LEARNER,
          rawRole:  String(o[CFG.HDR.EMP_ROLE]||'').trim(),
          staffId:  '',
          companyId:String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim(),
          side:     'employee'
        };
        return finishLogin_(userData);
      }
    }

    return { success:false, error:'Invalid credentials' };
  } catch (e) {
    return { success:false, error:'Auth error: ' + e.message };
  }
}
function finishLogin_(userData) {
  const token = Utilities.getUuid();
  CacheService.getScriptCache().put(token, JSON.stringify(userData), CFG.SESSION_TTL);
  return { success:true, token:token, userData:userData };
}
function validateSession(token) {
  const raw = CacheService.getScriptCache().get(token);
  if (!raw) return { valid:false };
  return { valid:true, userData: JSON.parse(raw) };
}
function invalidateSession(token) { CacheService.getScriptCache().remove(token); }
function requireRole_(token, allowed) {
  const raw = CacheService.getScriptCache().get(token);
  if (!raw) throw new Error('Session expired. Please log in again.');
  const u = JSON.parse(raw);
  if (allowed && allowed.indexOf(u.role) === -1) throw new Error('You do not have permission for this action.');
  return u;
}

/*****************  HELPERS  *****************/
function ss_() { return SpreadsheetApp.getActiveSpreadsheet(); }
function readObjects_(sheetName) {
  const sh = ss_().getSheetByName(sheetName);
  if (!sh) return { headers: [], rows: [] };
  const values = sh.getDataRange().getValues();
  if (values.length < 2) return { headers:(values[0]||[]).map(String), rows: [] };
  const headers = values[0].map(h => String(h).trim()); const rows=[];
  for (let i=1;i<values.length;i++){ const r=values[i]; if (r.every(c=>c===''||c===null)) continue;
    const o={}; headers.forEach((h,c)=>o[h]=r[c]); rows.push(o); }
  return { headers, rows };
}
function getHeaderMap_(sh) {
  const last=sh.getLastColumn(); if (!last) return {};
  const headers=sh.getRange(1,1,1,last).getValues()[0].map(h=>String(h).trim());
  const map={}; headers.forEach((h,i)=>{ if (h) map[h]=i+1; }); return map;
}
function distinctColumn_(sheetName, candidates) {
  const { headers, rows } = readObjects_(sheetName); const out=[], seen={};
  rows.forEach(o => { let v='';
    for (const c of candidates){ if (headers.indexOf(c)!==-1){ v=o[c]; break; } }
    if (v==='' && headers.length) v=o[headers[0]];
    v=String(v||'').trim(); if (v && !seen[v]){ seen[v]=true; out.push(v); } });
  return out;
}
function toYMD_(v){ if (v instanceof Date) return Utilities.formatDate(v,ss_().getSpreadsheetTimeZone(),'yyyy-MM-dd'); return String(v||'').trim().substring(0,10); }
function toHM_(v){ if (v===''||v==null) return ''; if (v instanceof Date) return Utilities.formatDate(v,ss_().getSpreadsheetTimeZone(),'HH:mm');
  const s=String(v).trim(), m=s.match(/(\d{1,2}):(\d{2})/); if (m){ let h=Number(m[1]); if (/pm/i.test(s)&&h<12)h+=12; if (/am/i.test(s)&&h===12)h=0; return ('0'+h).slice(-2)+':'+m[2]; } return s; }
function esc_(s){ return String(s==null?'':s).replace(/[&<>]/g,m=>({'&':'&amp;','<':'&lt;','>':'&gt;'}[m])); }
function splitCsv_(s){ return String(s||'').split(',').map(x=>x.trim()).filter(Boolean); }
function isEmail_(s){ return /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(String(s||'').trim()); }
function normRemindAt_(v,tz){ tz=tz||ss_().getSpreadsheetTimeZone();
  if (v instanceof Date) return Utilities.formatDate(v,tz,'yyyy-MM-dd HH:mm:ss');
  const s=String(v||'').trim(); if (!s) return '';
  if (/^\d{4}-\d{2}-\d{2} \d{2}:\d{2}/.test(s)) return s.substring(0,19).padEnd(19,':00').substring(0,19);
  const d=new Date(s); if (!isNaN(d.getTime())) return Utilities.formatDate(d,tz,'yyyy-MM-dd HH:mm:ss'); return ''; }





  /*****************  WHATSAPP (Meta Cloud API)  *****************/


// "+91 98765-43210" | "09876543210" | "9876543210" -> "919876543210"
function waNormalizePhone_(raw){
  let s = String(raw||'').replace(/[^\d]/g,'').replace(/^0+/,'');
  if (!s) return '';
  if (s.length === 10) s = String(WA.DEFAULT_COUNTRY_CODE) + s;   // bare 10-digit -> add CC
  return s;
}

// Whatsapp_templates -> { 'action||side': {metaTemplate, language, variables[]} }
function waTemplatesMap_(){
  if (!ss_().getSheetByName(WA.SHEET_TEMPLATES)) return {};
  const map = {};
  readObjects_(WA.SHEET_TEMPLATES).rows.forEach(o => {
    const action = String(o['Action']||'').trim().toLowerCase(); if (!action) return;
    const side   = String(o['Side']||'').trim().toLowerCase();
    const active = String(o['Active']||'').trim().toLowerCase();
    if (active==='no' || active==='false' || active==='0') return;
    map[action+'||'+side] = {
      metaTemplate: String(o['Meta_Template']||'').trim(),
      language:     String(o['Language']||'en').trim() || 'en',
      variables:    splitCsv_(String(o['Variables']||''))
    };
  });
  return map;
}

// WhatsappVariables -> { 'action||side||variable': sourceField }
function waVariableMap_(){
  if (!ss_().getSheetByName(WA.SHEET_VARIABLES)) return {};
  const map = {};
  readObjects_(WA.SHEET_VARIABLES).rows.forEach(o => {
    const action = String(o['Action']||'').trim().toLowerCase();
    const side   = String(o['Side']||'').trim().toLowerCase();
    const variable = String(o['Variable']||'').trim();
    if (!action || !variable) return;
    map[action+'||'+side+'||'+variable.toLowerCase()] = String(o['Source_Field']||'').trim();
  });
  return map;
}

// guess a data-field from a variable name (used as default mapping)
function waGuessField_(v){
  const k = String(v||'').trim().toLowerCase().replace(/[\s_\-]+/g,'');
  const known = {
    title:'Title', activity:'Activity', company:'Company_Name', companyname:'Company_Name',
    date:'Event_Date', eventdate:'Event_Date', time:'Event_Time', eventtime:'Event_Time',
    status:'Status',
    departments:'Departments', dept:'Departments',
    staff:'Staff_Assigner', staffassigner:'Staff_Assigner',
    doers:'Company_Assigners', companyassigners:'Company_Assigners',
    comment:'Comment',
    link:'Form_URL', form:'Form_URL', formlink:'Form_URL', formurl:'Form_URL',
    name:'Recipient_Name', recipient:'Recipient_Name'
  };
  return known[k] || '';
}

// build ordered body params for an (action, side); null if no template
function waBuildParams_(action, side, dataMap){
  const tmap = waTemplatesMap_();
  const tpl = tmap[action+'||'+side] || tmap[action+'||'];   // side-less fallback
  if (!tpl || !tpl.metaTemplate) return null;
  const vmap = waVariableMap_();
  const params = tpl.variables.map(v => {
    let src = vmap[action+'||'+side+'||'+v.toLowerCase()];
    if (!src) src = waGuessField_(v);
    let val = src ? dataMap[src] : dataMap[v];
    val = String(val==null ? '' : val)
            .replace(/\s*[\r\n]+\s*/g,' ').replace(/\t/g,' ').replace(/ {4,}/g,'   ').trim();
    if (val === '') val = '-';        // Meta empty param reject karta hai
    return { type:'text', text: val };
  });
  return { metaTemplate: tpl.metaTemplate, language: tpl.language, params: params };
}

// low-level send
function waSendTemplate_(toPhone, metaTemplate, language, params){
  const phone = waNormalizePhone_(toPhone);
  if (!phone) return { ok:false, error:'No phone' };
  if (!WA.ACCESS_TOKEN || !WA.PHONE_NUMBER_ID) return { ok:false, error:'WA not configured' };
  const url = 'https://graph.facebook.com/'+WA.API_VERSION+'/'+WA.PHONE_NUMBER_ID+'/messages';
  const components = (params && params.length) ? [{ type:'body', parameters: params }] : [];
  const payload = { messaging_product:'whatsapp', to:phone, type:'template',
    template:{ name:metaTemplate, language:{ code:language||'en' }, components:components } };
  try {
    const res = UrlFetchApp.fetch(url, { method:'post', contentType:'application/json',
      headers:{ Authorization:'Bearer '+WA.ACCESS_TOKEN },
      payload: JSON.stringify(payload), muteHttpExceptions:true });
    const code = res.getResponseCode(), body = res.getContentText();
    return (code>=200 && code<300) ? { ok:true, response:body } : { ok:false, error:'HTTP '+code+': '+body };
  } catch(e){ return { ok:false, error:e.message }; }
}

// high-level: send if template exists + log. Call this from mail loops.
function waNotify_(action, side, dataMap, phone, recipientName){
  if (!WA.ENABLED) return;
  const sid = (dataMap && (dataMap.Schedule_ID || dataMap._scheduleId)) || '';
  const fUrl = (dataMap && dataMap.Form_URL) || '';
  try {
    const dm = Object.assign({}, dataMap, { Recipient_Name: recipientName||'' });
    const built = waBuildParams_(action, side, dm);
    if (!built) return;                                  // koi template nahi -> silent skip
    const ph = waNormalizePhone_(phone);
    if (!ph){ waLog_(action, side, recipientName, '', 'Skipped', 'No phone', sid, fUrl); return; }
    const res = waSendTemplate_(ph, built.metaTemplate, built.language, built.params);
    waLog_(action, side, recipientName, ph, res.ok?'Sent':'Failed', res.ok?'':res.error, sid, fUrl);
  } catch(e){ waLog_(action, side, recipientName, phone, 'Failed', e.message, sid, fUrl); }
}

function waLog_(action, side, recipient, phone, status, error, scheduleId, formUrl){
  try {
    const sh = ensureSheet_('Whatsapp_logs', WA_LOG_HEADERS);
    const map = getHeaderMap_(sh);
    const tz = ss_().getSpreadsheetTimeZone();
    const row = new Array(sh.getLastColumn()).fill(''); const put=(h,v)=>{ if (map[h]) row[map[h]-1]=v; };
    put('Timestamp', Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss'));
    put('Action', action); put('Side', side); put('Recipient', recipient||''); put('Phone', phone||'');
    put('Schedule_ID', scheduleId||''); put('Form_URL', formUrl||''); put('Status', status); put('Error', error||'');
    sh.appendRow(row);   // header-driven: column order in sheet doesn't matter
  } catch(e){ Logger.log('waLog: '+e.message); }
}

// raw form URL (for WhatsApp; buildFormLinks_ returns HTML which WA can't use)
function buildFormUrl_(activity, companyId, employeeId, monthId){
  const forms = HOD_FORMS[String(activity||'').trim().toLowerCase()];
  if (!forms || !forms.length || !String(employeeId||'').trim()) return '';
  const cid = encodeURIComponent(String(companyId||'').trim());
  const eid = encodeURIComponent(String(employeeId||'').trim());
  const mid = encodeURIComponent(String(monthId||'').trim());
  const f = forms[0];
  let href = f.url + '?';
  if (!f.noCid) href += 'CID=' + cid + '&';
  href += 'EID=' + eid;
  if (mid) href += '&MID=' + mid;
  return href;
}

// Run ONCE (and after editing Whatsapp_templates) — auto-fills WhatsappVariables
function syncWhatsappVariables(){
  ensureSheet_(WA.SHEET_TEMPLATES, WA_TEMPLATE_HEADERS);
  const vSh = ensureSheet_(WA.SHEET_VARIABLES, WA_VARIABLE_HEADERS);
  const vMap = getHeaderMap_(vSh);
  const existing = {};
  if (vSh.getLastRow() > 1){
    const vals = vSh.getRange(2,1,vSh.getLastRow()-1,vSh.getLastColumn()).getValues();
    const cA=vMap['Action'], cS=vMap['Side'], cV=vMap['Variable'];
    vals.forEach(r => existing[
      String(r[cA-1]||'').trim().toLowerCase()+'||'+String(r[cS-1]||'').trim().toLowerCase()+'||'+String(r[cV-1]||'').trim().toLowerCase()
    ]=true);
  }
  const append=[]; let created=0;
  readObjects_(WA.SHEET_TEMPLATES).rows.forEach(o => {
    const action=String(o['Action']||'').trim(), side=String(o['Side']||'').trim();
    if (!action) return;
    splitCsv_(String(o['Variables']||'')).forEach((v,i)=>{
      const k=action.toLowerCase()+'||'+side.toLowerCase()+'||'+v.toLowerCase();
      if (existing[k]) return; existing[k]=true;
      const row=new Array(vSh.getLastColumn()).fill(''); const put=(h,val)=>{ if(vMap[h]) row[vMap[h]-1]=val; };
      put('Action',action); put('Side',side); put('Position',i+1);
      put('Variable',v); put('Source_Field', waGuessField_(v));   // auto-guess; user can change
      append.push(row); created++;
    });
  });
  if (append.length) vSh.getRange(vSh.getLastRow()+1,1,append.length,vSh.getLastColumn()).setValues(append);
  return 'WhatsappVariables sync: '+created+' new row(s).';
}

// quick test from editor: waTest_('9876543210')
function waTest_(phone){
  const m = waTemplatesMap_();
  const k = Object.keys(m)[0];
  if (!k) return 'No templates in Whatsapp_templates.';
  const dm = { Title:'Test', Activity:'Demo', Company_Name:'ACME', Event_Date:'2026-06-30',
    Event_Time:'10:00', Status:'Scheduled', Recipient_Name:'You', Form_URL:'https://example.com' };
  const [action,side] = k.split('||');
  const built = waBuildParams_(action, side, dm);
  const res = waSendTemplate_(phone, built.metaTemplate, built.language, built.params);
  return JSON.stringify(res);
}

/*****************  STAFF / SMOPS LOOKUP  *****************/
function getStaffList_() {
  const { rows } = readObjects_(CFG.SHEETS.STAFF);
  return rows.map(o => ({
    id:     String(o[CFG.HDR.STAFF_ID]||'').trim(),
    name:   String(o[CFG.HDR.STAFF_NAME]||'').trim(),
    email:  String(o[CFG.HDR.STAFF_EMAIL]||'').trim(),
    mobile: String(o[CFG.HDR.STAFF_MOBILE]||'').trim()
  })).filter(s => s.name);
}
function staffMobileByName_(name){
  name=String(name||'').trim(); if (!name) return '';
  for (const s of getStaffList_()) if (s.name.toLowerCase()===name.toLowerCase()) return s.mobile;
  return '';
}


function staffById_(id) {
  id = String(id||'').trim(); if (!id) return null;
  for (const s of getStaffList_()) if (s.id === id) return s;
  return null;
}
function staffEmailByName_(name) {
  name=String(name||'').trim(); if (!name) return '';
  if (isEmail_(name)) return name;
  for (const s of getStaffList_()) if (s.name.toLowerCase()===name.toLowerCase() && s.email) return s.email;
  return '';
}

/*****************  FORM DATA  *****************/


function getInitialData(token) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);

  // role-scoped cache key so each role gets its own company list
  const cacheKey = 'initData_' + u.role + '_' + (u.staffId||'') + '_' + (u.companyId||'');
  const cache = CacheService.getScriptCache();
  const hit = cache.get(cacheKey);
  if (hit) return JSON.parse(hit);

  const comp = readObjects_(CFG.SHEETS.COMPANIES);
  let companies = comp.rows.map(o => {
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    const smops = staffById_(smId);
    return {
      id:     String(o[CFG.HDR.COMPANY_ID]||'').trim(),
      name:   String(o[CFG.HDR.COMPANY_NAME]||'').trim(),
      smopsId:smId,
      smName: smops ? smops.name : '',
      smEmail:smops ? smops.email : ''
    };
  }).filter(c => c.name);

  // Staff (SMOps) see only their own companies; Learner only theirs; Admin all
  if (u.role === ROLES.STAFF && u.staffId)
    companies = companies.filter(c => c.smopsId === u.staffId);
  else if (u.role === ROLES.LEARNER && u.companyId)
    companies = companies.filter(c => c.id === u.companyId);

  const result = {
    companies: companies,
    activities: distinctColumn_(CFG.SHEETS.ACTIVITY, [CFG.HDR.ACTIVITIES,'Activity']),
    departments: distinctColumn_(CFG.SHEETS.DEPARTMENT, [CFG.HDR.DEPARTMENT,'Departments','Dept']),
    staff: getStaffList_().map(s => ({ name:s.name, email:s.email }))
  };

  cache.put(cacheKey, JSON.stringify(result), 300);
  return result;
}


function getDoers(token, companyId, departments) {
  requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  const { rows } = readObjects_(CFG.SHEETS.EMPLOYEES);
  const cid=String(companyId||'').trim(); const depSet={};
  (departments||[]).forEach(d=>depSet[String(d).trim().toLowerCase()]=true);
  const allDeps=!departments||!departments.length; const out=[];
  rows.forEach(o => {
    if (cid && String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim()!==cid) return;
    const dep=String(o[CFG.HDR.EMP_DEPT]||'').trim();
    if (!allDeps && !depSet[dep.toLowerCase()]) return;
    const name=String(o[CFG.HDR.EMP_NAME]||'').trim(); if (!name) return;
    out.push({ name:name, email:String(o[CFG.HDR.EMP_EMAIL]||'').trim(), dept:dep });
  });
  return out;
}

/*****************  CALENDAR DATA  *****************/
function getEvents(token, year, month0) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  const { rows } = readObjects_(CFG.SHEETS.SCHEDULE);
  const remCount={};
  if (ss_().getSheetByName(CFG.SHEETS.REMINDERS))
    readObjects_(CFG.SHEETS.REMINDERS).rows.forEach(o=>{ const sid=String(o['Schedule_ID']||''); if (sid) remCount[sid]=(remCount[sid]||0)+1; });
  const actMeta = activityUploadMap_();
  const prefix = year+'-'+('0'+(month0+1)).slice(-2);

  // --- scoping setup ---
  // Staff (SMOps): apni companies
  let staffCompanies = null;
  if (u.role === ROLES.STAFF && u.staffId){
    staffCompanies = {};
    readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
      if (String(o[CFG.HDR.COMPANY_SMOPS]||'').trim() === u.staffId)
        staffCompanies[String(o[CFG.HDR.COMPANY_ID]||'').trim()] = true;
    });
  }

  // Learner: MD → poori company; HOD/other → sirf apne related (doer/assigner)
  let learnerIsMD = false, learnerName = '';
  if (u.role === ROLES.LEARNER){
    const me = readObjects_(CFG.SHEETS.EMPLOYEES).rows.find(o =>
      String(o[CFG.HDR.EMP_EMAIL]||'').trim().toLowerCase() === String(u.email).trim().toLowerCase());
    if (me){
      learnerName = String(me[CFG.HDR.EMP_NAME]||'').trim().toLowerCase();
      const role = String(me[CFG.HDR.EMP_ROLE]||'').toLowerCase();
      learnerIsMD = /\bmd\b|managing director|client|owner|founder|ceo/.test(role);
    } else {
      learnerName = String(u.username||'').trim().toLowerCase();
    }
  }

  let evs = rows.map(o => {
    const id=String(o['Schedule_ID']||'');
    const am = actMeta[String(o['Activity']||'').trim().toLowerCase()] || {};
    return { id:id, title:String(o['Title']||''),
      activity:String(o['Activity']||''), date:toYMD_(o['Event_Date']), time:toHM_(o['Event_Time']),
      companyId:String(o['Company_ID']||''),
      company:String(o['Company_Name']||''), status:String(o['Status']||'Scheduled'),
      departments:String(o['Departments']||''), companyAssigners:String(o['Company_Assigners']||''),
      staffAssigner:String(o['Staff_Assigner']||''), recurrence:String(o['Recurrence']||''),
      learnerDone:String(o['Learner_Done']||''), escStage:Number(o['Esc_Stage']||0),
      rescheduleCount:Number(o['Reschedule_Count']||0), completedAt:String(o['Completed_At']||''),
       comment:String(o['Comment']||''),
      uploadRequired: !!am.upload, responsive: am.responsive || '',
      createdBy:String(o['Created_By']||''),
      mine: !!(o['Created_By'] && String(o['Created_By']).trim().toLowerCase() === String(u.email||'').trim().toLowerCase()),
      reminderCount:remCount[id]||0 };
  }).filter(e => e.date.indexOf(prefix)===0);

  // --- apply scope ---
  if (u.role === ROLES.STAFF && staffCompanies){
    evs = evs.filter(e => staffCompanies[String(e.companyId).trim()]);
  } else if (u.role === ROLES.LEARNER){
    // pehle apni company
    if (u.companyId) evs = evs.filter(e => String(e.companyId) === String(u.companyId));
    // HOD/other → sirf jinme wo doer/assigner hain; MD → sab
    if (!learnerIsMD && learnerName){
      evs = evs.filter(e => {
        const doers = String(e.companyAssigners||'').toLowerCase();
        const isDoer = doers.split(',').map(s=>s.trim()).indexOf(learnerName) !== -1;
        return isDoer || e.mine;   // doer OR events I scheduled (creator)
      });
    }
  }

  return evs.sort((a,b)=>(a.date+' '+(a.time||'99:99')).localeCompare(b.date+' '+(b.time||'99:99')));
}
function getScheduleById_(id) {
  const { rows } = readObjects_(CFG.SHEETS.SCHEDULE);
  for (const o of rows) if (String(o['Schedule_ID'])===String(id)) return o; return null;
}

/*****************  TASK UPLOADS (upload-required activities)  *****************/
const UPLOAD_HEADERS = ['Upload_ID','Schedule_ID','Company_ID','Company_Name','Activity','Responsive','Month','Employee_ID','Employee_Name','Uploaded_By','File_Name','File_URL','File_ID','Uploaded_At'];
function ensureUploadSheet_(){ return ensureSheet_('Task_Uploads', UPLOAD_HEADERS); }



const UPLOAD_FOLDER_ID = '1jDxZhrjdIv51jcV-wKDTpuKUbnSVwsxm';



function getUploadFolder_(){
  try { return DriveApp.getFolderById(UPLOAD_FOLDER_ID); }
  catch(e){ throw new Error('Upload folder not found. Check UPLOAD_FOLDER_ID. ('+e.message+')'); }
}

// activityLOWER -> { upload:true/false, responsive:'HOD wise'|'Company vise' }
function activityUploadMap_(){
  const obj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>obj.headers.indexOf(h)!==-1)||obj.headers[0];
  const hUp   = ['Upload Required','Upload_Required','UploadRequired','Upload'].find(h=>obj.headers.indexOf(h)!==-1);
  const hResp = ['Responsive','Responsible','Response'].find(h=>obj.headers.indexOf(h)!==-1);
  const map = {};
  obj.rows.forEach(o=>{
    const a = String(o[hFull]||'').trim().toLowerCase(); if(!a) return;
    const up = hUp ? /^(yes|y|true|1|required)$/i.test(String(o[hUp]||'').trim()) : false;
    map[a] = { upload: up, responsive: hResp ? String(o[hResp]||'').trim() : '' };
  });
  return map;
}

// existing uploads for a schedule
function getTaskUploads(token, scheduleId){
  requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  if (!ss_().getSheetByName('Task_Uploads')) return [];
  const out = [];
  readObjects_('Task_Uploads').rows.forEach(o=>{
    if (String(o['Schedule_ID']||'').trim() !== String(scheduleId).trim()) return;
    out.push({ name:String(o['File_Name']||''), url:String(o['File_URL']||''),
      by:String(o['Uploaded_By']||''), at:String(o['Uploaded_At']||''),
      empName:String(o['Employee_Name']||'') });
  });
  return out;
}

// fileObj: { name, mimeType, data(base64) }
function uploadTaskFile(token, scheduleId, fileObj){
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  if (!fileObj || !fileObj.data) throw new Error('No file data.');
  const sched = getScheduleById_(scheduleId);
  if (!sched) throw new Error('Schedule not found.');
  const cid = String(sched['Company_ID']||'').trim();

  // Learner apni company ke bahar upload na kar sake
  if (u.role === ROLES.LEARNER && u.companyId && cid !== String(u.companyId).trim())
    throw new Error('Not allowed for this company.');

  const activity = String(sched['Activity']||'').trim();
  const am = activityUploadMap_()[activity.toLowerCase()] || {};
  if (!am.upload) throw new Error('This activity does not require an upload.');

  const date  = toYMD_(sched['Event_Date']);
  const month = midFromDate_(date);
  const responsive = am.responsive || '';

  // uploader employee resolve (HOD-wise tracking)
  let empId = '', empName = '';
  if (u.side === 'employee'){
    const me = readObjects_(CFG.SHEETS.EMPLOYEES).rows.find(o =>
      String(o[CFG.HDR.EMP_EMAIL]||'').trim().toLowerCase() === String(u.email).trim().toLowerCase());
    if (me){ empId = String(me['Employee_ID']||'').trim(); empName = String(me[CFG.HDR.EMP_NAME]||'').trim(); }
  }

  // Drive save
  const folder = getUploadFolder_();
  const bytes = Utilities.base64Decode(fileObj.data);
  const blob  = Utilities.newBlob(bytes, fileObj.mimeType || 'application/octet-stream',
                  (fileObj.name || 'upload') );
  const fname = (activity+'_'+cid+'_'+month+'_'+Date.now()+'_'+(fileObj.name||'file'))
                  .replace(/[\\\/:*?"<>|]+/g,'_');
  const file  = folder.createFile(blob).setName(fname);
  try { file.setSharing(DriveApp.Access.ANYONE_WITH_LINK, DriveApp.Permission.VIEW); } catch(e){}

  const sh = ensureUploadSheet_();
  const map = getHeaderMap_(sh);
  const tz = ss_().getSpreadsheetTimeZone();
  const row = new Array(sh.getLastColumn()).fill('');
  const put = (h,v)=>{ if(map[h]) row[map[h]-1]=v; };
  put('Upload_ID','UP-'+Date.now());
  put('Schedule_ID', scheduleId);
  put('Company_ID', cid);
  put('Company_Name', String(sched['Company_Name']||''));
  put('Activity', activity);
  put('Responsive', responsive);
  put('Month', "'" + month);
  put('Employee_ID', empId);
  put('Employee_Name', empName);
  put('Uploaded_By', u.username || u.email || '');
  put('File_Name', fileObj.name || file.getName());
  put('File_URL', file.getUrl());
  put('File_ID', file.getId());
  put('Uploaded_At', Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss'));
  sh.appendRow(row);

  return { ok:true, name: fileObj.name || file.getName(), url: file.getUrl() };
}

function findScheduleRow_(sh, map, id) {
  const ids=sh.getRange(1,map['Schedule_ID'],sh.getLastRow(),1).getValues();
  for (let i=1;i<ids.length;i++) if (String(ids[i][0])===String(id)) return i+1; return -1;
}
function deleteSchedule(token, id) {
  requireRole_(token, [ROLES.ADMIN]);
  const sh=ensureScheduleSheet_(); const map=getHeaderMap_(sh);
  const row=findScheduleRow_(sh,map,id); if (row===-1) throw new Error('Entry not found.');
  sh.deleteRow(row); deleteRemindersForSchedule_(id);
  try { deleteTrackerRowsForSchedule_(id); } catch(e){ Logger.log('tracker del: '+e.message); }
  return { ok:true };
}
function updateSchedule(token, id, payload) {
  const actor = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  const sh = ensureScheduleSheet_(); const map = getHeaderMap_(sh);
  const row = findScheduleRow_(sh, map, id); if (row === -1) throw new Error('Entry not found.');
  if (actor.role === ROLES.LEARNER){
    const createdBy = String(map['Created_By'] ? sh.getRange(row, map['Created_By']).getValue() : '').trim().toLowerCase();
    if (createdBy !== String(actor.email||'').trim().toLowerCase())
      throw new Error('You can only edit activities you scheduled.');
  }
  const tz = ss_().getSpreadsheetTimeZone();
  const lastCol = sh.getLastColumn();

  // read row once, mutate array, write once (1 round-trip instead of ~18)
  const rowVals = sh.getRange(row, 1, 1, lastCol).getValues()[0];
  const set = (h, v) => { if (map[h]) rowVals[map[h]-1] = v; };

  let count = Number(map['Reschedule_Count'] ? rowVals[map['Reschedule_Count']-1] : 0) || 0;
  if (payload.status === 'Rescheduled') count += 1;

  set('Title', payload.title||'');
  set('Activity', payload.activity||''); set('Event_Date', payload.planStart||'');
  set('Event_Time', payload.eventTime ? "'"+payload.eventTime : '');
  set('Company_ID', payload.companyId||''); set('Company_Name', payload.companyName||'');
  set('Status', payload.status||'Scheduled');
  set('Departments', (payload.departments||[]).join(', '));
  set('Company_Assigners', (payload.companyAssigners||[]).join(', '));
  set('Staff_Assigner', (payload.staffAssigners||[]).join(', '));
  set('Reschedule_Count', count);
  if (payload.status==='Rescheduled' || payload.status==='Scheduled' || payload.status==='Completed') set('Esc_Stage', 0);
  if (payload.status==='Completed'){
    const completedAtStr2 = Utilities.formatDate(new Date(), ss_().getSpreadsheetTimeZone(), 'yyyy-MM-dd HH:mm:ss');
    const ldAtCell = map['Learner_Done_At'] ? sh.getRange(row, map['Learner_Done_At']).getValue() : '';
    closeLinkedActionItems_(id, completedAtStr2, ldAtCell);
  }
  set('Completed_At', payload.status==='Completed' ? Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss') : '');
  set('Completed_by', payload.status==='Completed' ? (actor.username || actor.email || '') : '');
  set('Comment', payload.comment||'');

  sh.getRange(row, 1, 1, lastCol).setValues([rowVals]);   // single write

  if (payload.status==='Cancelled') cancelRemindersForSchedule_(id);
  try { updateTrackerStatus_(id, payload.status||'Scheduled'); } catch(e){ Logger.log('tracker sync: '+e.message); }

  // queue mail/WhatsApp in background — return to UI immediately
  let kind = '';
  if (payload.status==='Rescheduled') kind='reschedule';
  else if (payload.status==='Cancelled') kind='cancel';
  else if (payload.status==='Completed') kind='completed';
  if (kind){ payload._scheduleId = id; try { enqueueStatusMail_(payload, kind); } catch(e){ Logger.log('enqueue: '+e.message); } }

  return { ok:true, count:1, rescheduleCount:count };
}


/*****************  DUPLICATE / FREQUENCY CHECK  *****************/

function checkScheduleConflict(token, payload) {
  requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  const activity = String(payload.activity||'').trim();
  const companyId = String(payload.companyId||'').trim();
  const planStart = String(payload.planStart||'').trim();
  if (!activity || !companyId || !planStart) return { conflict:false };

  // --- read Activity sheet meta (Frequency + Responsive) ---
  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull  = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>actObj.headers.indexOf(h)!==-1)||actObj.headers[0];
  const hFreq  = ['Frequency','frequency'].find(h=>actObj.headers.indexOf(h)!==-1);
  const hResp  = ['Responsive','Responsible','Response'].find(h=>actObj.headers.indexOf(h)!==-1);

  let frequency = '', responsive = '';
  for (const o of actObj.rows) {
    if (String(o[hFull]||'').trim().toLowerCase() === activity.toLowerCase()) {
      frequency  = hFreq ? String(o[hFreq]||'').trim().toLowerCase() : '';
      responsive = hResp ? String(o[hResp]||'').trim().toLowerCase() : '';
      break;
    }
  }

  // Only enforce for "once"-type activities. Recurring (WRM "3-4 in month", "multiple times") skip.
  const isOnce = frequency.indexOf('once') !== -1 || frequency.indexOf('1 ') === 0 || frequency === '1';
  const isMulti = frequency.indexOf('multiple') !== -1 || /\d\s*-\s*\d/.test(frequency); // "3-4 in month"
  if (!isOnce || isMulti) return { conflict:false, frequency:frequency, responsive:responsive };

  // HOD-wise → scope to the doer(s); Company-wise → scope to company only
  const hodWise = responsive.indexOf('hod') !== -1;
  const wantMonth = midFromDate_(planStart);   // e.g. jun26
  const newDoers = (payload.companyAssigners||[]).map(s=>String(s).trim().toLowerCase());

  // --- scan existing schedule for same activity + company + month ---
  const matches = [];
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    if (String(o['Company_ID']||'').trim() !== companyId) return;
    if (String(o['Activity']||'').trim().toLowerCase() !== activity.toLowerCase()) return;
    const st = String(o['Status']||'').trim().toLowerCase();
    if (st === 'cancelled') return;                       // cancelled doesn't block
    const date = toYMD_(o['Event_Date']);
    if (midFromDate_(date) !== wantMonth) return;         // same month only

    if (hodWise && newDoers.length) {
      // only a conflict if the same doer overlaps
      const existDoers = splitCsv_(String(o['Company_Assigners']||'')).map(s=>s.toLowerCase());
      const overlap = existDoers.some(d => newDoers.indexOf(d) !== -1);
      if (!overlap) return;
    }
    matches.push({
      scheduleId: String(o['Schedule_ID']||''),
      title:      String(o['Title']||''),
      date:       date,
      time:       toHM_(o['Event_Time']),
      status:     String(o['Status']||'Scheduled'),
      doers:      String(o['Company_Assigners']||''),
      staff:      String(o['Staff_Assigner']||''),
      company:    String(o['Company_Name']||'')
    });
  });

  return {
    conflict: matches.length > 0,
    scope: hodWise ? 'HOD' : 'Company',
    month: wantMonth,
    frequency: frequency,
    responsive: responsive,
    existing: matches.sort((a,b)=>(a.date||'').localeCompare(b.date||''))
  };
}


/*****************  SAVE  *****************/
function saveSchedule(token, payload) {
 const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  if (u.role === ROLES.STAFF && u.staffId){
    const owns = readObjects_(CFG.SHEETS.COMPANIES).rows.some(o =>
      String(o[CFG.HDR.COMPANY_ID]||'').trim() === String(payload.companyId||'').trim() &&
      String(o[CFG.HDR.COMPANY_SMOPS]||'').trim() === u.staffId);
    if (!owns) throw new Error('You can only schedule for your own companies.');
  }
  if (u.role === ROLES.LEARNER){
    if (String(payload.companyId||'').trim() !== String(u.companyId||'').trim())
      throw new Error('You can only schedule for your own company.');
  }

  const occ=buildOccurrences_(payload);
  if (!occ.length) throw new Error('No dates generated. Check dates / recurrence / weekdays.');
  const sh=ensureScheduleSheet_(); const map=getHeaderMap_(sh); const lastCol=sh.getLastColumn();
  const tz=ss_().getSpreadsheetTimeZone(); const now=new Date(); const batchId='BATCH-'+now.getTime();
  const user=(validateSession(token).userData||{}).email||''; const timeCell=payload.eventTime?"'"+payload.eventTime:'';
  const occMeta=[];
  const rows=occ.map((dt,i)=>{
    const id='SCH-'+now.getTime()+'-'+(i+1); const dateStr=Utilities.formatDate(dt,tz,'yyyy-MM-dd');
    occMeta.push({ id:id, date:dateStr });
    const row=new Array(lastCol).fill(''); const put=(h,v)=>{ if (map[h]) row[map[h]-1]=v; };
    put('Schedule_ID',id); put('Batch_ID',batchId);
    put('Title',payload.title||''); put('Activity',payload.activity||''); put('Event_Date',dateStr);
    put('Event_Time',timeCell); put('Company_ID',payload.companyId||'');
    put('Company_Name',payload.companyName||''); put('Status',payload.status||'Scheduled');
    put('Departments',(payload.departments||[]).join(', '));
    put('Company_Assigners',(payload.companyAssigners||[]).join(', '));
    put('Staff_Assigner',(payload.staffAssigners||[]).join(', '));
    put('Recurrence',payload.recurrence||'One-time'); put('Plan_Start',payload.planStart||''); put('Plan_End',payload.planEnd||'');
    put('Created_At',Utilities.formatDate(now,tz,'yyyy-MM-dd HH:mm:ss')); put('Created_By',user);
    put('Reschedule_Count',0); put('Completed_At','');
    put('Comment',payload.comment||'');
    return row;
  });
 sh.getRange(sh.getLastRow()+1,1,rows.length,lastCol).setValues(rows);
  payload._batchId = batchId;   // set before mail+reminders so both log the batch
  let scheduleMails=0; try { scheduleMails=sendScheduleEmails_(payload, occMeta[0]); } catch(e){ Logger.log('sched mail: '+e.message); }
  let remCount=0;
  if (payload.reminders && payload.reminders.length){ remCount=writeReminders_(payload,occMeta,payload.reminders); }
  try { remCount += autoRemindersFromRules_(payload, occMeta); } catch(e){ Logger.log('autoRem: '+e.message); }
  let trackerCount=0; try { trackerCount=writeTrackerRows_(payload, occMeta); } catch(e){ Logger.log('tracker: '+e.message); }
  return { ok:true, count:rows.length, batchId:batchId, reminders:remCount, scheduleMails:scheduleMails, tracker:trackerCount };
}

function ensureScheduleSheet_(){ return ensureSheet_(CFG.SHEETS.SCHEDULE, SCHEDULE_HEADERS); }
function ensureRemindersSheet_(){ return ensureSheet_(CFG.SHEETS.REMINDERS, REMINDER_HEADERS); }


function ensureSheet_(name, headers) {
  let sh=ss_().getSheetByName(name); if (!sh) sh=ss_().insertSheet(name);
  if (sh.getLastRow()===0){ sh.getRange(1,1,1,headers.length).setValues([headers]).setFontWeight('bold'); sh.setFrozenRows(1); return sh; }
  const existing=sh.getRange(1,1,1,sh.getLastColumn()).getValues()[0].map(h=>String(h).trim());
  headers.forEach(h=>{ if (existing.indexOf(h)===-1){ sh.getRange(1,existing.length+1).setValue(h).setFontWeight('bold'); existing.push(h);} });
  return sh;
}





/*****************  ACTIVITY TRACKER  *****************/
const TRACKER_HEADERS = [
  'Company_ID','Employee_ID','Employee_Name','Month','Date','Activity','Status','Schedule_ID','Updated_At'
];
function ensureTrackerSheet_(){ return ensureSheet_('Activity_Tracker', TRACKER_HEADERS); }

// yyyy-MM-dd or Date -> "jun26"
function trackerMonthKey_(v){
  let d = (v instanceof Date) ? v : parseYMD_(String(v||'').trim().substring(0,10));
  if (!d || isNaN(d.getTime())) return '';
  const mon = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][d.getMonth()];
  return mon + String(d.getFullYear()).slice(-2);
}

// Called from saveSchedule: writes one tracker row per occurrence × company-assigner.
function writeTrackerRows_(payload, occMeta) {
  const sh = ensureTrackerSheet_();
  const map = getHeaderMap_(sh);
  const lastCol = sh.getLastColumn();
  const tz = ss_().getSpreadsheetTimeZone();
  const nowStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');

  const eInfo = doerInfoMap_(payload.companyId);     // name(lower) -> {email,id}
  const assigners = payload.companyAssigners || [];

  // If no company-assigners, fall back to one company-level row per occurrence (blank employee).
  const targets = assigners.length ? assigners : [''];

  const out = [];
  occMeta.forEach(meta => {
    targets.forEach(name => {
      const info = name ? (eInfo[name.toLowerCase()] || {}) : {};
      const row = new Array(lastCol).fill('');
      const put = (h,v) => { if (map[h]) row[map[h]-1] = v; };
      put('Company_ID', payload.companyId || '');
      put('Employee_ID', info.id || '');
      put('Employee_Name', name || '');
      put('Month', "'" + trackerMonthKey_(meta.date));   // forced text
      put('Date', meta.date);
      put('Activity', payload.activity || '');
      put('Status', payload.status || 'Scheduled');
      put('Schedule_ID', meta.id || '');
      put('Updated_At', nowStr);
      out.push(row);
    });
  });
  if (out.length) sh.getRange(sh.getLastRow()+1, 1, out.length, lastCol).setValues(out);
  return out.length;
}

// Called from updateSchedule: keep tracker Status in sync with the schedule.
function updateTrackerStatus_(scheduleId, newStatus) {
  const sh = ss_().getSheetByName('Activity_Tracker');
  if (!sh || sh.getLastRow() < 2) return;
  const map = getHeaderMap_(sh);
  const sidCol = map['Schedule_ID'], stCol = map['Status'], upCol = map['Updated_At'];
  if (!sidCol || !stCol) return;
  const last = sh.getLastRow();
  const sids = sh.getRange(2, sidCol, last-1, 1).getValues();
  const tz = ss_().getSpreadsheetTimeZone();
  const nowStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');
  for (let i = 0; i < sids.length; i++) {
    if (String(sids[i][0]) === String(scheduleId)) {
      sh.getRange(i+2, stCol).setValue(newStatus);
      if (upCol) sh.getRange(i+2, upCol).setValue(nowStr);
    }
  }
}

// Called from deleteSchedule.
function deleteTrackerRowsForSchedule_(scheduleId) {
  const sh = ss_().getSheetByName('Activity_Tracker');
  if (!sh || sh.getLastRow() < 2) return;
  const map = getHeaderMap_(sh);
  const sidCol = map['Schedule_ID']; if (!sidCol) return;
  const vals = sh.getRange(1, sidCol, sh.getLastRow(), 1).getValues();
  for (let i = vals.length - 1; i >= 1; i--)
    if (String(vals[i][0]) === String(scheduleId)) sh.deleteRow(i+1);
}






/*****************  TEMPLATES (4 cols)  *****************/
function getTemplate_(activity, kind, side) {
  const a=String(activity||'').trim().toLowerCase();
  const { headers, rows } = readObjects_(CFG.SHEETS.TEMPLATES);
  const hAct=['Activity','Activities'].find(h=>headers.indexOf(h)!==-1)||headers[0];
  let colName;
  if (kind==='schedule') colName = side==='staff'?'Staff_schedules_mail_Template':'Company_schedules_mail_Template';
  else if (kind==='reminder') colName = side==='staff'?'Staff_mail_Reminder_Template':'Company_mail_Reminder_Template';
  else if (kind==='reschedule') colName = side==='staff'?'Staff_mail_Status_reschedule':'Company_mail_Status_reschedule';
  else if (kind==='cancel') colName = side==='staff'?'Staff_mail_Status_cancel':'Company_mail_Status_cancel';
  else if (kind==='completed') colName = side==='staff'?'Staff_mail_Status_Completed':'Company_mail_Status_Completed';
  else colName = side==='staff'?'Staff_schedules_mail_Template':'Company_schedules_mail_Template';
  for (const o of rows) if (String(o[hAct]||'').trim().toLowerCase()===a) return String(o[colName]||'');
  return '';
}

function sendStatusEmails_(payload, kind) {
  const map={ Title:payload.title||'', Activity:payload.activity||'', Company_Name:payload.companyName||'',
    Event_Date:payload.planStart||'', Event_Time:payload.eventTime||'',
    Status:payload.status||'', Departments:(payload.departments||[]).join(', '),
    Staff_Assigner:(payload.staffAssigners||[]).join(', '), Company_Assigners:(payload.companyAssigners||[]).join(', '),
    Comment:payload.comment||'', Form_Link:'',
    Schedule_ID:payload._scheduleId||'' };
  const label = kind==='reschedule'?'Rescheduled':kind==='cancel'?'Cancelled':'Completed';
  const subject='['+label+'] '+(map.Title||'')+' – '+(map.Activity||'')+(map.Event_Date?' on '+map.Event_Date:'');

  const tz = ss_().getSpreadsheetTimeZone();
  const now = new Date();
  const ts = Utilities.formatDate(now, tz, 'yyyy-MM-dd HH:mm:ss');
  const logSh = ensureSchedLogSheet_();
  const logMap = getHeaderMap_(logSh);
  const logCols = logSh.getLastColumn();
  const logRows = [];
  let seq = 0;
  const pushLog = (side, name, email, status, error, formUrl) => {
    seq++;
    const r = new Array(logCols).fill('');
    const put = (h,v) => { if (logMap[h]) r[logMap[h]-1] = v; };
    put('Log_ID','SLOG-'+now.getTime()+'-'+seq);
    put('Batch_ID', payload._batchId || '');
    put('Schedule_ID', payload._scheduleId || '');
    put('Timestamp', ts);
    put('Title', map.Title); put('Activity', map.Activity);
    put('Company_ID', payload.companyId||''); put('Company_Name', map.Company_Name);
    put('Side', side); put('Recipient_Name', name); put('Recipient_Email', email||'');
    put('Subject', subject); put('Status', status); put('Error', error||'');
    put('Form_Link', formUrl||'');
    logRows.push(r);
  };

  let sent=0;
  (payload.staffAssigners||[]).forEach(n=>{
    waNotify_(kind,'staff', map, staffMobileByName_(n), n);
    const em=staffEmailByName_(n);
    if (!isEmail_(em)){ pushLog('Staff', n, em, label+': Failed', 'No email resolved'); return; }
    try {
      const tpl=getTemplate_(map.Activity,kind,'staff');
      sendMail_(em,subject,tpl?fill_(tpl,map):defaultBody_(map,label));
      pushLog('Staff', n, em, label+': Sent', ''); sent++;
    } catch(e){ pushLog('Staff', n, em, label+': Failed', e.message); }
  });
  const eInfo=doerInfoMap_(payload.companyId);
  (payload.companyAssigners||[]).forEach(n=>{
    const info=eInfo[n.toLowerCase()]||{}; const em=info.email;
    const link = (kind==='cancel') ? '' : buildFormLinks_(map.Activity, payload.companyId, info.id, '#db2777', midFromDate_(map.Event_Date));
    const url  = (kind==='cancel') ? '' : buildFormUrl_(map.Activity, payload.companyId, info.id, midFromDate_(map.Event_Date));
    const rmap=Object.assign({}, map, { Form_Link: link, Form_URL: url });
    waNotify_(kind,'company', rmap, info.mobile, n);
    if (!isEmail_(em)){ pushLog('Company', n, em, label+': Failed', 'No email resolved', url); return; }
    try {
      const tpl=getTemplate_(map.Activity,kind,'company');
      sendMail_(em,subject,tpl?fill_(tpl,rmap):defaultBody_(rmap,label));
      pushLog('Company', n, em, label+': Sent', '', url); sent++;
    } catch(e){ pushLog('Company', n, em, label+': Failed', e.message, url); }
  });

  if (logRows.length) logSh.getRange(logSh.getLastRow()+1, 1, logRows.length, logCols).setValues(logRows);
  return sent;
}


/*****************  ASYNC STATUS-MAIL QUEUE  *****************/
// Stores the mail job + schedules a one-off trigger (~3s) so updateSchedule returns instantly.
function enqueueStatusMail_(payload, kind){
  const cache = CacheService.getScriptCache();
  const jobId = 'mailjob_'+Date.now()+'_'+Math.floor(Math.random()*1e6);
  cache.put(jobId, JSON.stringify({ payload:payload, kind:kind }), 1800);   // 30 min
  const props = PropertiesService.getScriptProperties();
  const lock  = LockService.getScriptLock();
  let queued = false;
  try {
    lock.waitLock(5000);
    const pending = JSON.parse(props.getProperty('MAIL_QUEUE')||'[]');
    pending.push(jobId);
    props.setProperty('MAIL_QUEUE', JSON.stringify(pending));
    const has = ScriptApp.getProjectTriggers().some(t => t.getHandlerFunction()==='drainMailQueue');
    if (!has) ScriptApp.newTrigger('drainMailQueue').timeBased().after(3000).create();
    queued = true;
  } catch(e){ Logger.log('enqueue err: '+e.message); }
  finally { try{ lock.releaseLock(); }catch(e){} }

  if (!queued){ // trigger/quota failed → send now so mail isn't lost
    cache.remove(jobId);
    try { sendStatusEmails_(payload, kind); } catch(e){ Logger.log('fallback mail: '+e.message); }
  }
}

// Trigger handler: drains all pending jobs, then deletes the firing trigger.
function drainMailQueue(e){
  try { if (e && e.triggerUid) ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getUniqueId()===e.triggerUid) ScriptApp.deleteTrigger(t); }); } catch(err){}
  const props = PropertiesService.getScriptProperties();
  const cache = CacheService.getScriptCache();
  const lock  = LockService.getScriptLock();
  for (let pass=0; pass<5; pass++){
    let jobs = [];
    try { lock.waitLock(5000); jobs = JSON.parse(props.getProperty('MAIL_QUEUE')||'[]'); props.setProperty('MAIL_QUEUE','[]'); }
    catch(err){ Logger.log('drain lock: '+err.message); }
    finally { try{ lock.releaseLock(); }catch(_){} }
    if (!jobs.length) break;
    jobs.forEach(jobId=>{
      const raw = cache.get(jobId); if (!raw) return; cache.remove(jobId);
      try { const j = JSON.parse(raw); sendStatusEmails_(j.payload, j.kind); }
      catch(err){ Logger.log('drain send: '+err.message); }
    });
  }
}


function fill_(tpl, map){ return String(tpl||'').replace(/\{\{\s*(\w+)\s*\}\}/g,(m,k)=>(map[k]!==undefined?map[k]:m)); }

function buildMap_(s){ return { Title:s['Title']||'', Activity:s['Activity']||'', Company_Name:s['Company_Name']||'',
  Event_Date:toYMD_(s['Event_Date'])||'', Event_Time:toHM_(s['Event_Time'])||'',
  Status:s['Status']||'', Departments:s['Departments']||'', Staff_Assigner:s['Staff_Assigner']||'',
  Company_Assigners:s['Company_Assigners']||'', Comment:s['Comment']||'' }; }


function defaultBody_(map,label){ return '<div style="font-family:Arial,sans-serif;color:#1e293b">'
  +'<h3 style="color:#7c3aed">'+esc_(label)+': '+esc_(map.Title)+'</h3><p><b>Activity:</b> '+esc_(map.Activity)
  +'<br><b>Company:</b> '+esc_(map.Company_Name)+'<br><b>Date:</b> '+esc_(map.Event_Date)
  +(map.Event_Time?' '+esc_(map.Event_Time):'')+'</p></div>'; }
function sendMail_(to,subject,html){ MailApp.sendEmail({ to:to, subject:subject,
  htmlBody: html.indexOf('<')!==-1?html:html.replace(/\n/g,'<br>'), name:CFG.MAIL.FROM_NAME, replyTo:CFG.MAIL.REPLY_TO }); }


function doerInfoMap_(companyId){
  const map = {};
  readObjects_(CFG.SHEETS.EMPLOYEES).rows.forEach(o => {
    if (companyId && String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim() !== String(companyId).trim()) return;
    const n = String(o[CFG.HDR.EMP_NAME]||'').trim(); if (!n) return;
    map[n.toLowerCase()] = {
      email:  String(o[CFG.HDR.EMP_EMAIL]||'').trim(),
      id:     String(o['Employee_ID']||'').trim(),
      mobile: String(o['Employee_Mobile']||'').trim()
    };
  });
  return map;
}

function buildFormLinks_(activity, companyId, employeeId, color, monthId){
  const forms = HOD_FORMS[String(activity||'').trim().toLowerCase()];
  if (!forms || !forms.length || !String(employeeId||'').trim()) return '';
  color = color || '#7c3aed';
  const cid = encodeURIComponent(String(companyId||'').trim());
  const eid = encodeURIComponent(String(employeeId||'').trim());
  const mid = encodeURIComponent(String(monthId||'').trim());
  const btns = forms.map(f => {
    let href = f.url + '?';
    if (!f.noCid) href += 'CID=' + cid + '&';
    href += 'EID=' + eid;
    if (mid) href += '&MID=' + mid;
    return '<td style="padding:6px"><a href="'+href+'" target="_blank" '
      + 'style="display:block;text-align:center;padding:14px 22px;background:'+color+';color:#fff;'
      + 'text-decoration:none;border-radius:10px;font-weight:700;font-size:14px;'
      + 'box-shadow:0 2px 6px rgba(219,39,119,.25)">'+esc_(f.label)+' &rarr;</a></td>';
  }).join('');
  return '<table style="margin:18px auto 8px;border-collapse:separate"><tr>'+btns+'</tr></table>';
}

// Event date (yyyy-MM-dd or Date) → "jun26"
function midFromDate_(v){
  let d = (v instanceof Date) ? v : parseYMD_(String(v||'').trim().substring(0,10));
  if (!d || isNaN(d.getTime())) return '';
  const mon = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][d.getMonth()];
  return mon + String(d.getFullYear()).slice(-2);
}


function sendScheduleEmails_(payload, firstMeta) {
  const map={ Title:payload.title||'', Activity:payload.activity||'', Company_Name:payload.companyName||'',
    Event_Date:(firstMeta&&firstMeta.date)||payload.planStart||'', Event_Time:payload.eventTime||'',
    Status:payload.status||'Scheduled',
    Departments:(payload.departments||[]).join(', '), Staff_Assigner:(payload.staffAssigners||[]).join(', '),
    Company_Assigners:(payload.companyAssigners||[]).join(', '),
    Comment:payload.comment||'', Form_Link:'',
    Schedule_ID:(firstMeta&&firstMeta.id)||'' };
  const subject='[Scheduled] '+(map.Title||'')+' – '+(map.Activity||'')+(map.Event_Date?' on '+map.Event_Date:'');

  const tz = ss_().getSpreadsheetTimeZone();
  const now = new Date();
  const ts = Utilities.formatDate(now, tz, 'yyyy-MM-dd HH:mm:ss');
  const logSh = ensureSchedLogSheet_();
  const logMap = getHeaderMap_(logSh);
  const logCols = logSh.getLastColumn();
  const logRows = [];
  let seq = 0;
  const pushLog = (side, name, email, status, error, formUrl) => {
    seq++;
    const r = new Array(logCols).fill('');
    const put = (h,v) => { if (logMap[h]) r[logMap[h]-1] = v; };
    put('Log_ID','SLOG-'+now.getTime()+'-'+seq);
    put('Batch_ID', payload._batchId || '');
    put('Schedule_ID', (firstMeta&&firstMeta.id) || '');
    put('Timestamp', ts);
    put('Title', map.Title); put('Activity', map.Activity);
    put('Company_ID', payload.companyId||''); put('Company_Name', map.Company_Name);
    put('Side', side); put('Recipient_Name', name); put('Recipient_Email', email||'');
    put('Subject', subject); put('Status', status); put('Error', error||'');
    put('Form_Link', formUrl||'');
    logRows.push(r);
  };

  let sent=0;
  (payload.staffAssigners||[]).forEach(n=>{
    waNotify_('schedule','staff', map, staffMobileByName_(n), n);
    const em=staffEmailByName_(n);
    if (!isEmail_(em)){ pushLog('Staff', n, em, 'Failed', 'No email resolved'); return; }
    try {
      const tpl=getTemplate_(map.Activity,'schedule','staff');
      sendMail_(em,subject,tpl?fill_(tpl,map):defaultBody_(map,'Scheduled'));
      pushLog('Staff', n, em, 'Sent', ''); sent++;
    } catch(e){ pushLog('Staff', n, em, 'Failed', e.message); }
  });
  const eInfo=doerInfoMap_(payload.companyId);
  (payload.companyAssigners||[]).forEach(n=>{
    const info=eInfo[n.toLowerCase()]||{}; const em=info.email;
    const formLink = buildFormLinks_(map.Activity, payload.companyId, info.id, '#db2777', midFromDate_(map.Event_Date));
    const formUrl  = buildFormUrl_(map.Activity, payload.companyId, info.id, midFromDate_(map.Event_Date));
    const rmap=Object.assign({}, map, { Form_Link: formLink, Form_URL: formUrl });
    waNotify_('schedule','company', rmap, info.mobile, n);
    if (!isEmail_(em)){ pushLog('Company', n, em, 'Failed', 'No email resolved', formUrl); return; }
    try {
      const tpl=getTemplate_(map.Activity,'schedule','company');
      sendMail_(em,subject,tpl?fill_(tpl,rmap):defaultBody_(rmap,'Scheduled'));
      pushLog('Company', n, em, 'Sent', '', formUrl); sent++;
    } catch(e){ pushLog('Company', n, em, 'Failed', e.message, formUrl); }
  });

  if (logRows.length) logSh.getRange(logSh.getLastRow()+1, 1, logRows.length, logCols).setValues(logRows);
  return sent;
}

/*****************  REMINDERS  *****************/
function writeReminders_(payload, occMeta, reminders) {
  const sh=ensureRemindersSheet_(); const map=getHeaderMap_(sh); const lastCol=sh.getLastColumn();
  const tz=ss_().getSpreadsheetTimeZone(); const now=new Date(); const baseTime=payload.eventTime||CFG.DEFAULT_REMIND_TIME;
  const UNIT={MINS:60000,HRS:3600000,DAYS:86400000}; const out=[]; let seq=0;
  reminders.forEach(r=>{ const targets=(r.type==='exact')?[occMeta[0]]:occMeta; if (!targets[0]) return;
    targets.forEach(meta=>{
      let remindAt='';
      if (r.type==='exact'){ if (!r.date||!r.time) return; const d=parseYMD_(r.date), t=String(r.time).split(':').map(Number);
        remindAt=Utilities.formatDate(new Date(d.getFullYear(),d.getMonth(),d.getDate(),t[0]||0,t[1]||0,0),tz,'yyyy-MM-dd HH:mm:ss');
      } else { const d=parseYMD_(meta.date), t=String(baseTime).split(':').map(Number);
        const base=new Date(d.getFullYear(),d.getMonth(),d.getDate(),t[0]||0,t[1]||0,0);
        const ms=(Number(r.value)||0)*(UNIT[r.unit]||60000);
        remindAt=Utilities.formatDate(new Date(base.getTime()+(r.dir==='after'?ms:-ms)),tz,'yyyy-MM-dd HH:mm:ss'); }
      const rowArr=new Array(lastCol).fill(''); const put=(h,v)=>{ if (map[h]) rowArr[map[h]-1]=v; }; seq++;
      put('Reminder_ID','REM-'+now.getTime()+'-'+seq); put('Schedule_ID',meta.id); put('Batch_ID',payload._batchId||'');
      put('Title',payload.title||''); put('Activity',payload.activity||'');
      put('Company_ID',payload.companyId||''); put('Company_Name',payload.companyName||''); put('Channel',r.channel||'Email');
      put('Reminder_Type',r.type==='exact'?'Exact':'Offset'); put('Offset_Value',r.type==='exact'?'':(r.value||''));
      put('Offset_Unit',r.type==='exact'?'':(r.unit||'')); put('Offset_Dir',r.type==='exact'?'':(r.dir||''));
      put('Event_Date',meta.date); put('Event_Time',baseTime?"'"+baseTime:''); put('Remind_At',"'"+remindAt);
      put('Status','Pending'); put('Recipients_Company',''); put('Recipients_staff',''); put('Sent_At',''); put('Error','');
      put('Created_At',Utilities.formatDate(now,tz,'yyyy-MM-dd HH:mm:ss')); out.push(rowArr);
    });
  });
  if (out.length) sh.getRange(sh.getLastRow()+1,1,out.length,lastCol).setValues(out);
  return out.length;
}
function deleteRemindersForSchedule_(id){ const sh=ss_().getSheetByName(CFG.SHEETS.REMINDERS); if (!sh||sh.getLastRow()<2) return;
  const map=getHeaderMap_(sh); const col=map['Schedule_ID']; if (!col) return;
  const vals=sh.getRange(1,col,sh.getLastRow(),1).getValues();
  for (let i=vals.length-1;i>=1;i--) if (String(vals[i][0])===String(id)) sh.deleteRow(i+1); }


function cancelRemindersForSchedule_(id){ const sh=ss_().getSheetByName(CFG.SHEETS.REMINDERS); if (!sh||sh.getLastRow()<2) return;
  const map=getHeaderMap_(sh); const sidCol=map['Schedule_ID'], stCol=map['Status']; if (!sidCol||!stCol) return;
  const last=sh.getLastRow(); const sids=sh.getRange(1,sidCol,last,1).getValues(), sts=sh.getRange(1,stCol,last,1).getValues();
  for (let i=1;i<last;i++) if (String(sids[i][0])===String(id)&&String(sts[i][0])==='Pending') sh.getRange(i+1,stCol).setValue('Cancelled'); 
  }

  

function setupReminderTrigger(){ ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getHandlerFunction()==='runReminders') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('runReminders').timeBased().everyMinutes(5).create(); return 'Trigger installed.'; }
function testSendMail(){ const to=Session.getActiveUser().getEmail()||Session.getEffectiveUser().getEmail();
  MailApp.sendEmail({ to:to, subject:'Test mail', htmlBody:'<p>Works. Quota: '+MailApp.getRemainingDailyQuota()+'</p>', name:CFG.MAIL.FROM_NAME, replyTo:CFG.MAIL.REPLY_TO }); return 'Sent to '+to; }


function runReminders(){ const sh=ss_().getSheetByName(CFG.SHEETS.REMINDERS); if (!sh||sh.getLastRow()<2) return;
  const map=getHeaderMap_(sh); const values=sh.getDataRange().getValues(); const headers=values[0].map(h=>String(h).trim());
  const idx={}; headers.forEach((h,i)=>idx[h]=i); const tz=ss_().getSpreadsheetTimeZone(); const nowStr=Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss');
  for (let i=1;i<values.length;i++){ const row=values[i]; if (String(row[idx['Status']]||'')!=='Pending') continue;
    const remindAt=normRemindAt_(row[idx['Remind_At']],tz); if (!remindAt||remindAt>nowStr) continue;
    const rObj={}; headers.forEach((h,c)=>rObj[h]=row[c]); let res; try { res=sendReminderForRow_(rObj); } catch(e){ res={status:'Failed',recipientsStaff:'',recipientsCompany:'',error:e.message}; }
    const r1=i+1; if (map['Status']) sh.getRange(r1,map['Status']).setValue(res.status);
    if (map['Recipients_staff'])   sh.getRange(r1,map['Recipients_staff']).setValue(res.recipientsStaff||'');
    if (map['Recipients_Company']) sh.getRange(r1,map['Recipients_Company']).setValue(res.recipientsCompany||'');
    if (map['Sent_At']&&res.status==='Sent') sh.getRange(r1,map['Sent_At']).setValue(nowStr);
    if (map['Error']) sh.getRange(r1,map['Error']).setValue(res.error||''); } }


function sendReminderForRow_(r){
  const ch = String(r['Channel']||'Email');
  const doEmail = (ch==='Email' || ch==='Both' || ch==='');   // WhatsApp auto-fires regardless (template-gated)
  const sched=getScheduleById_(r['Schedule_ID'])||r; const companyId=r['Company_ID']||sched['Company_ID']||'';
  const map=buildMap_(sched); map.Form_Link=''; map.Schedule_ID=String(r['Schedule_ID']||sched['Schedule_ID']||'');
  const subject='[Reminder] '+(map.Title||'')+' – '+(map.Activity||'')+(map.Event_Date?' on '+map.Event_Date:'');
  const sentStaff=[], sentCompany=[];

  splitCsv_(map.Staff_Assigner).forEach(n=>{
    waNotify_('reminder','staff', map, staffMobileByName_(n), n);
    if (!doEmail) return;
    const em=staffEmailByName_(n); if (!isEmail_(em)) return;
    const tpl=getTemplate_(map.Activity,'reminder','staff');
    sendMail_(em,subject,tpl?fill_(tpl,map):defaultBody_(map,'Reminder')); sentStaff.push(em);
  });

  const eInfo=doerInfoMap_(companyId);
  splitCsv_(map.Company_Assigners).forEach(n=>{
    const info=eInfo[n.toLowerCase()]||{}; const em=info.email;
    const formLink = buildFormLinks_(map.Activity, companyId, info.id, '#db2777', midFromDate_(map.Event_Date));
    const formUrl  = buildFormUrl_(map.Activity, companyId, info.id, midFromDate_(map.Event_Date));
    const rmap=Object.assign({}, map, { Form_Link: formLink, Form_URL: formUrl });
    waNotify_('reminder','company', rmap, info.mobile, n);
    if (!doEmail) return;
    if (!isEmail_(em)) return;
    const tpl=getTemplate_(map.Activity,'reminder','company');
    sendMail_(em,subject,tpl?fill_(tpl,rmap):defaultBody_(rmap,'Reminder')); sentCompany.push(em);
  });

  if (doEmail && !sentStaff.length && !sentCompany.length)
    return { status:'Failed', recipientsStaff:'', recipientsCompany:'', error:'No emails resolved. Staff="'+map.Staff_Assigner+'" Doers="'+map.Company_Assigners+'" Company="'+companyId+'"' };
  return { status:'Sent', recipientsStaff:sentStaff.join(', '), recipientsCompany:sentCompany.join(', ') };
}



/*****************  RECURRENCE  *****************/
function parseYMD_(s){ if (!s) return null; const p=String(s).split('-'); if (p.length!==3) return null; return new Date(Number(p[0]),Number(p[1])-1,Number(p[2])); }
function buildOccurrences_(p){ const rec=p.recurrence||'One-time'; const start=parseYMD_(p.planStart); const end=parseYMD_(p.planEnd)||start;
  if (!start) return []; if (rec==='One-time'||!rec) return [start]; if (!end||end<start) return []; const out=[];
  if (rec==='Monthly'){ const day=start.getDate(); let y=start.getFullYear(), m=start.getMonth();
    while(true){ const dim=new Date(y,m+1,0).getDate(); const d=new Date(y,m,Math.min(day,dim)); if (d>end) break; if (d>=start) out.push(d); m++; if (m>11){m=0;y++;} } }
  else if (rec==='Weekly'){ let d=new Date(start); while(d<=end){ out.push(new Date(d)); d.setDate(d.getDate()+7); } }
  else if (rec==='Periodically'){ const wd={}; (p.weekdays||[]).forEach(n=>wd[Number(n)]=true); let d=new Date(start); while(d<=end){ if (wd[d.getDay()]) out.push(new Date(d)); d.setDate(d.getDate()+1); } }
  return out; }









  /*=================================================================Admin dashboard===============================================================================*/

function getAnalytics(token, scope) {
 const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  scope = scope || {};
  try { syncAutoFeed(); } catch(e){ Logger.log('autofeed: '+e.message); }
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // month picker (default = current month) — period usi month ka
  const filterMonth = scope.month ? succMonthNorm_(scope.month) : succMonthNorm_(new Date());
  let from = scope.from, to = scope.to;
  if (!from || !to) {
    const mm = filterMonth.match(/^([a-z]{3})(\d{2})$/);
    let py, pm;
    if (mm){
      pm = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(mm[1]);
      py = 2000 + Number(mm[2]);
    }
    if (pm == null || pm < 0){ const now = new Date(); py = now.getFullYear(); pm = now.getMonth(); }
    from = Utilities.formatDate(new Date(py, pm, 1), tz, 'yyyy-MM-dd');
    to   = Utilities.formatDate(new Date(py, pm+1, 0), tz, 'yyyy-MM-dd');
  }
  // previous equal-length period (for trend)
  const fD = parseYMD_(from), tD = parseYMD_(to);
  const spanDays = Math.round((tD - fD) / 86400000) + 1;
  const prevTo   = new Date(fD.getTime() - 86400000);
  const prevFrom = new Date(prevTo.getTime() - (spanDays - 1) * 86400000);
  const prevFromS = Utilities.formatDate(prevFrom, tz, 'yyyy-MM-dd');
  const prevToS   = Utilities.formatDate(prevTo,   tz, 'yyyy-MM-dd');

  // company -> SMOps map (read Staff once)
  const staffList = getStaffList_();
  const staffMap = {}; staffList.forEach(s => staffMap[s.id] = s);
  const comp = readObjects_(CFG.SHEETS.COMPANIES);
  const companyInfo = {};    // id -> { name, smopsId, smopsName }
  const smopsCompanies = {}; // smopsId -> [companyId]
  comp.rows.forEach(o => {
    const id = String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    companyInfo[id] = { name:String(o[CFG.HDR.COMPANY_NAME]||'').trim(), smopsId:smId, smopsName:(staffMap[smId]||{}).name||'' };
    if (smId) (smopsCompanies[smId] = smopsCompanies[smId] || []).push(id);
  });

  // role scoping
  let allowCompany = null;
  if (u.role === ROLES.LEARNER && u.companyId) allowCompany = { [u.companyId]: true };
  if (u.role === ROLES.STAFF && u.staffId) { allowCompany = {}; (smopsCompanies[u.staffId]||[]).forEach(c => allowCompany[c] = true); }
  if (scope.companyId) allowCompany = { [scope.companyId]: true };
  const filterSmops = scope.smopsId || '';

  const inRange = (d,a,b) => d && d >= a && d <= b;

  // ---- Action Closure % per company (from Action_Items) ----
  const actClose = {}; // companyId -> { closed, total }
  if (ss_().getSheetByName('Action_Items')) {
    readObjects_('Action_Items').rows.forEach(o => {
      const cid = String(o['Company_ID']||'').trim(); if (!cid) return;
      const a = actClose[cid] || (actClose[cid] = { closed:0, total:0 });
      a.total++;
      if (String(o['Status']||'').trim() === 'Closed') a.closed++;
    });
  }

  // ---- Active escalation counts per company (from Escalations) ----
  const escCount = {}; // companyId -> active count
  if (ss_().getSheetByName('Escalations')) {
    readObjects_('Escalations').rows.forEach(o => {
      const cid = String(o['Company_ID']||'').trim(); if (!cid) return;
      if (String(o['Status']||'').trim() === 'Resolved') return;
      escCount[cid] = (escCount[cid]||0) + 1;
    });
  }


// ---- Success-measure rollups per activity (from Success_Measures) ----
  // achievement = actual/target*100, averaged across in-scope clients per activity
  const succ = {};  // activityLower -> { sum, n }
  let succAllSum = 0, succAllN = 0;
  if (ss_().getSheetByName('Success_Measures')) {
    readObjects_('Success_Measures').rows.forEach(o => {
      const cid = String(o['Company_ID']||'').trim();
      if (allowCompany && !allowCompany[cid]) return;
      if (filterSmops && (companyInfo[cid]||{}).smopsId !== filterSmops) return;
      const t = pctNum_(o['Activity_Score_Target_%']), a = pctNum_(o['Actual_Activity_Score_%']);
      if (t == null && a == null) return;
      const ach = (t && t > 0) ? Math.round((a/t)*100) : (a||0);
      const key = String(o['Activity']||'').trim().toLowerCase();
      const s = succ[key] || (succ[key] = { sum:0, n:0 });
      s.sum += ach; s.n++;
      succAllSum += ach; succAllN++;
    });
  }
  // match an activity by fuzzy contains (handles "Accountability & Ownership Rating" vs "O&A")
  const succAvg = (needles) => {
    let sum = 0, n = 0;
    Object.keys(succ).forEach(k => {
      if (needles.some(nd => k.indexOf(nd) !== -1)) { sum += succ[k].sum; n += succ[k].n; }
    });
    return n > 0 ? Math.round(sum/n) : 0;
  };
  const oaRating     = succAvg(['accountability','o&a','ownership']);
  const cultureScore = succAvg(['culture']);
  const drmCompletion= succAvg(['drm','kpi']);
  const successScore = succAllN > 0 ? Math.round(succAllSum/succAllN) : 0;


  // accumulators
  const blank = () => ({ planned:0, done:0, pending:0, overdue:0, cancelled:0,
    delaySum:0, delayN:0, prevP:0, prevD:0 });
  const totals = blank();
  const byCompany = {}, bySmops = {};

  const { rows } = readObjects_(CFG.SHEETS.SCHEDULE);

  // month options (in-scope companies ke events ke months)
  const monthSet = {};
  rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    if (allowCompany && !allowCompany[cid]) return;
    if (filterSmops && (companyInfo[cid]||{}).smopsId !== filterSmops) return;
    const m = succMonthNorm_(o['Event_Date']); if (m) monthSet[m] = true;
  });
  monthSet[filterMonth] = true;
  const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  const monthOptions = Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }))
    .sort((a,b)=>{
      const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
      if(!ma||!mb) return 0;
      return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
    });

  rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    const info = companyInfo[cid] || { name:String(o['Company_Name']||''), smopsId:'', smopsName:'' };
    const smId = info.smopsId;
    if (allowCompany && !allowCompany[cid]) return;
    if (filterSmops && smId !== filterSmops) return;

    const date = toYMD_(o['Event_Date']);
    const status = String(o['Status']||'Scheduled');
    const inCur = inRange(date, from, to), inPrev = inRange(date, prevFromS, prevToS);
    if (!inCur && !inPrev) return;

    const C = byCompany[cid] || (byCompany[cid] = blank());
    const S = smId ? (bySmops[smId] || (bySmops[smId] = blank())) : null;
    const bump = (acc,f,n) => { if (acc) acc[f] += (n===undefined?1:n); };

    if (inPrev) {
      [totals,C,S].forEach(a=>bump(a,'prevP'));
      if (status==='Completed') [totals,C,S].forEach(a=>bump(a,'prevD'));
      if (!inCur) return;
    }
    [totals,C,S].forEach(a=>bump(a,'planned'));

    if (status==='Completed') {
      [totals,C,S].forEach(a=>bump(a,'done'));
      const c2 = toYMD_(o['Completed_At']);
      if (c2 && date) { const diff = Math.round((parseYMD_(c2)-parseYMD_(date))/86400000);
        if (!isNaN(diff) && diff>0) [totals,C,S].forEach(a=>{ if(a){a.delaySum+=diff;a.delayN++;} }); }
    } else if (status==='Cancelled') {
      [totals,C,S].forEach(a=>bump(a,'cancelled'));
    } else {
      if (date < todayStr) [totals,C,S].forEach(a=>bump(a,'overdue'));
      else [totals,C,S].forEach(a=>bump(a,'pending'));
    }
  });

  const pct = (d,p) => p>0 ? Math.round((d/p)*100) : 0;
  const avgDelay = a => a.delayN>0 ? Math.round((a.delaySum/a.delayN)*10)/10 : 0;
  const statusBand = c => c>=95?'STRONG':c>=85?'GOOD':c>=70?'WATCH':'AT-RISK';
  const trend = a => { const cur=pct(a.done,a.planned), prev=pct(a.prevD,a.prevP); return cur>prev?'Up':cur<prev?'Down':'Flat'; };
  const closurePct = cid => { const a=actClose[cid]; return a&&a.total>0 ? pct(a.closed,a.total) : ''; };

  // client matrix
  const clients = Object.keys(byCompany).map(cid => {
    const a = byCompany[cid]; const info = companyInfo[cid] || {};
    return { companyId:cid, company:info.name||cid, smops:info.smopsName||'',
      done:a.done, pending:a.pending, overdue:a.overdue, planned:a.planned,
      completion:pct(a.done,a.planned),
      avgDelay:avgDelay(a), trend:trend(a), status:statusBand(pct(a.done,a.planned)),
      escalations:(escCount[cid]||0), actionClosure:closurePct(cid) };
  }).sort((x,y)=>x.company.localeCompare(y.company));

  // OM performance — Action Closure & Esc aggregated across the OM's companies
  const oms = Object.keys(bySmops).map(smId => {
    const a = bySmops[smId]; const cos = smopsCompanies[smId]||[];
    let clClosed=0, clTotal=0, esc=0;
    cos.forEach(cid => { const ac=actClose[cid]; if(ac){clClosed+=ac.closed; clTotal+=ac.total;} esc += (escCount[cid]||0); });
    return { smopsId:smId, om:(staffMap[smId]||{}).name||smId, clients:cos.length,
      planned:a.planned, done:a.done, completion:pct(a.done,a.planned),
      avgDelay:avgDelay(a), trend:trend(a),
      escalations:esc, actionClosure: clTotal>0 ? pct(clClosed,clTotal) : '' };
  }).sort((x,y)=>y.completion - x.completion);   // ranked by completion desc

  // Top Delayed Clients (highest avg delay, then overdue count)
  const topDelayed = clients.filter(c=>c.avgDelay>0 || c.overdue>0)
    .sort((x,y)=> (y.avgDelay - x.avgDelay) || (y.overdue - x.overdue)).slice(0,5);

  // KPI cards
  let totClosed=0, totActions=0;
  Object.keys(actClose).forEach(cid => { if (!allowCompany || allowCompany[cid]) { totClosed+=actClose[cid].closed; totActions+=actClose[cid].total; } });
  let totEsc=0; Object.keys(escCount).forEach(cid => { if (!allowCompany || allowCompany[cid]) totEsc+=escCount[cid]; });

 const plannedClientCount = clients.filter(c => c.planned > 0).length;
  const totalClientCount = Object.keys(allowCompany || companyInfo).length;

 const cards = {
    totalClients: totalClientCount,
    totalOMs: Object.keys(bySmops).length,
    planned: totals.planned, completed: totals.done,
    completion: pct(totals.done, totals.planned),
    avgDelay: avgDelay(totals),
    actionClosure: totActions>0 ? pct(totClosed,totActions) : 0,
    escalations: totEsc,
    oaRating: oaRating,
    cultureScore: cultureScore,
    drmCompletion: drmCompletion,
    successScore: successScore,
    plannedClients: plannedClientCount,
    unplannedClients: totalClientCount - plannedClientCount
  };

  // filter dropdowns
  const smopsOptions = {};
  Object.keys(companyInfo).forEach(cid => { if (allowCompany && !allowCompany[cid]) return;
    const i=companyInfo[cid]; if (i.smopsId) smopsOptions[i.smopsId]=i.smopsName||i.smopsId; });
  const companyOptions = Object.keys(companyInfo).filter(cid=>!allowCompany||allowCompany[cid])
    .map(cid=>({id:cid,name:companyInfo[cid].name||cid})).sort((a,b)=>a.name.localeCompare(b.name));

  return {
    role:u.role, period:{from:from,to:to},
    selectedMonth: filterMonth,
    cards:cards, clients:clients, oms:oms, topDelayed:topDelayed,
    filters:{ smops:Object.keys(smopsOptions).map(id=>({id:id,name:smopsOptions[id]})), companies:companyOptions, months:monthOptions }
  };
}

/*=================================================== CLIENT-WISE CALENDAR (Admin/Staff) ===================================================*/
function getClientCalendarData(token, scope) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF]);
  scope = scope || {};
  const filterMonth = scope.month ? succMonthNorm_(scope.month) : succMonthNorm_(new Date());

  const staffList = getStaffList_();
  const staffMap = {}; staffList.forEach(s => staffMap[s.id] = s);
  const comp = readObjects_(CFG.SHEETS.COMPANIES);
  const allowedCompanies = {}; const companyInfo = {};
  comp.rows.forEach(o => {
    const cid = String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    companyInfo[cid] = { name:String(o[CFG.HDR.COMPANY_NAME]||'').trim()||cid, smopsId:smId };
    if (u.role === ROLES.STAFF && u.staffId){ if (smId === u.staffId) allowedCompanies[cid] = true; }
    else allowedCompanies[cid] = true;
  });

  const filterSmops   = (u.role === ROLES.ADMIN) ? String(scope.smopsId||'').trim() : '';
  const filterCompany = String(scope.companyId||'').trim();
  const filterHod     = String(scope.hodId||'').trim().toLowerCase();
  const filterSide    = String(scope.side||'').trim();   // 'OM' | 'Client' | ''
  const creatorMap    = filterSide ? getCreatorRoleMap_() : null;

  // HOD options (scoped to allowed companies / selected company)
  const hodSet = {};
  readObjects_(CFG.SHEETS.EMPLOYEES).rows.forEach(o => {
    const cid = String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim();
    if (!allowedCompanies[cid]) return;
    if (filterCompany && cid !== filterCompany) return;
    const role = String(o[CFG.HDR.EMP_ROLE]||'').toLowerCase();
    if (!/hod/.test(role)) return;
    const nm = String(o[CFG.HDR.EMP_NAME]||'').trim(); if (!nm) return;
    hodSet[nm.toLowerCase()] = nm;
  });

  const events = [];
  let planned = 0, completed = 0, pending = 0, delayed = 0, lapsed = 0;
  const tz2 = ss_().getSpreadsheetTimeZone();
  const todayStr2 = Utilities.formatDate(new Date(), tz2, 'yyyy-MM-dd');
  const byDate = {};
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    if (!allowedCompanies[cid]) return;
    if (filterCompany && cid !== filterCompany) return;
    if (filterSmops && (companyInfo[cid]||{}).smopsId !== filterSmops) return;
    const date = toYMD_(o['Event_Date']);
    if (!date || succMonthNorm_(date) !== filterMonth) return;
    const doers = splitCsv_(String(o['Company_Assigners']||'')).map(s=>s.toLowerCase());
    if (filterHod && doers.indexOf(filterHod)===-1) return;
    if (filterSide && scheduledBySide_(o['Created_By'], creatorMap) !== filterSide) return;
    const status = String(o['Status']||'Scheduled');
    if (status !== 'Cancelled') planned++;
    if (status === 'Completed') completed++;
    else if (status === 'Lapsed') lapsed++;
    else if (status !== 'Cancelled'){
      if (date < todayStr2) delayed++;
      else pending++;
    }
    const ev = {
      id:String(o['Schedule_ID']||''), title:String(o['Title']||''), activity:String(o['Activity']||''),
      date:date, time:toHM_(o['Event_Time']),
      company:companyInfo[cid]?companyInfo[cid].name:String(o['Company_Name']||''),
      status:status, doers:String(o['Company_Assigners']||''),
      side: scheduledBySide_(o['Created_By'], creatorMap || getCreatorRoleMap_())
    };
    events.push(ev);
    (byDate[date] = byDate[date] || []).push(ev);
  });

  const monthOpts = [];
  const monIdxArr = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  const seenM = {};
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    if (!allowedCompanies[cid]) return;
    const m = succMonthNorm_(o['Event_Date']); if (m && !seenM[m]){ seenM[m]=true; monthOpts.push({id:m,name:succMonthDisplay_(m)}); }
  });
  if (!seenM[filterMonth]) monthOpts.push({ id:filterMonth, name:succMonthDisplay_(filterMonth) });
  monthOpts.sort((a,b)=>{
    const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
    if(!ma||!mb) return 0;
    return (Number(mb[2])*12+monIdxArr[mb[1]]) - (Number(ma[2])*12+monIdxArr[ma[1]]);
  });

  return {
    selectedMonth: filterMonth,
    planned: planned,
    completed: completed,
    pending: pending,
    delayed: delayed,
    lapsed: lapsed,
    events: events,
    isAdmin: (u.role === ROLES.ADMIN),
    filters: {
      companies: Object.keys(allowedCompanies).map(cid=>({id:cid,name:companyInfo[cid].name})).sort((a,b)=>a.name.localeCompare(b.name)),
      hods: Object.keys(hodSet).map(k=>({id:k,name:hodSet[k]})).sort((a,b)=>a.name.localeCompare(b.name)),
      smops: (u.role === ROLES.ADMIN) ? staffList.map(s=>({id:s.id,name:s.name})).sort((a,b)=>a.name.localeCompare(b.name)) : [],
      months: monthOpts
    }
  };
}





/*====================================SMOP dashboard============================================*/

const ACTION_HEADERS = [
  'Action_ID','Schedule_ID','Company_ID','Company_Name','Activity',
  'Action','Owner','Owner_Email','Employee_ID','Target_Date','Status','Delay_Days','Created_At',
  'Learner_Delay_Days','Staff_Delay_Days'
];
function ensureActionSheet_(){ return ensureSheet_('Action_Items', ACTION_HEADERS); }


function getScheduleLearnerDoneMap_() {
  const map = {};
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    const sid = String(o['Schedule_ID']||'').trim();
    if (!sid) return;
    map[sid] = {
      learnerDone: String(o['Learner_Done']||'').trim().toLowerCase() === 'yes',
      status: String(o['Status']||'').trim()
    };
  });
  return map;
}

function actionDelayLabel_(o, schedMap) {
  const st = String(o['Status']||'').trim();
  if (st === 'Closed') {
    return {
      learner: String(o['Learner_Delay_Days']||'0') + 'd',
      staff: String(o['Staff_Delay_Days']||'0') + 'd'
    };
  }
  const sid = String(o['Schedule_ID']||'').trim();
  const sched = schedMap[sid];
  const pendingSide = (sched && sched.learnerDone) ? 'Pending (Staff side)' : 'Pending (Client side)';
  return { learner: pendingSide, staff: pendingSide };
}


// scope: { from, to, smopsId } — Staff auto-scoped to own companies; Admin may pass smopsId
function getStaffDashboard(token, scope) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF]);
  scope = scope || {};
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  const filterMonth = scope.month ? succMonthNorm_(scope.month) : succMonthNorm_(new Date());
  let from = scope.from, to = scope.to;
  if (!from || !to) {
    const mm = filterMonth.match(/^([a-z]{3})(\d{2})$/);
    let py, pm;
    if (mm){
      pm = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(mm[1]);
      py = 2000 + Number(mm[2]);
    }
    if (pm == null || pm < 0){ const now = new Date(); py = now.getFullYear(); pm = now.getMonth(); }
    from = Utilities.formatDate(new Date(py, pm, 1), tz, 'yyyy-MM-dd');
    to   = Utilities.formatDate(new Date(py, pm+1, 0), tz, 'yyyy-MM-dd');
  }

  const staffList = getStaffList_();
  const staffMap = {}; staffList.forEach(s => staffMap[s.id] = s);

  const comp = readObjects_(CFG.SHEETS.COMPANIES);
  const targetSmops = (u.role === ROLES.STAFF) ? u.staffId : (scope.smopsId || '');
  const targetCompany = String(scope.companyId||'').trim();
  const myCompanies = {};
  const allSmops = {};
  comp.rows.forEach(o => {
    const cid = String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    if (smId) allSmops[smId] = (staffMap[smId]||{}).name || smId;
    if (targetSmops && smId !== targetSmops) return;
    if (targetCompany && cid !== targetCompany) return;
    myCompanies[cid] = String(o[CFG.HDR.COMPANY_NAME]||'').trim() || cid;
  });

  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull  = [CFG.HDR.ACTIVITIES,'Activity'].find(h => actObj.headers.indexOf(h)!==-1) || actObj.headers[0];
  const hShort = [CFG.HDR.ACTIVITIES_SHORTCUT,'Activity_Shortcut'].find(h => actObj.headers.indexOf(h)!==-1);
  const activities = []; const seenAct = {};
  actObj.rows.forEach(o => {
    const full = String(o[hFull]||'').trim(); if (!full || seenAct[full]) return; seenAct[full] = true;
    activities.push({ full: full, short: (hShort ? String(o[hShort]||'').trim() : '') || full });
  });

  const inRange = d => d && d >= from && d <= to;
  const filterSide = String(scope.side||'').trim();   // 'OM' | 'Client' | ''
  const creatorMap = filterSide ? getCreatorRoleMap_() : null;

  const grid = {}, tally = {};
  Object.keys(myCompanies).forEach(cid => { grid[cid] = {}; tally[cid] = { done:0, total:0 }; });

  let planned=0, done=0, pending=0, overdue=0, delaySum=0, delayN=0, lapsedCount=0, reschedCount=0;

  const alerts = [];
  const { rows } = readObjects_(CFG.SHEETS.SCHEDULE);
  rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    if (!myCompanies[cid]) return;
    const date = toYMD_(o['Event_Date']); if (!inRange(date)) return;
    if (filterSide && scheduledBySide_(o['Created_By'], creatorMap) !== filterSide) return;
    const act = String(o['Activity']||'').trim();
    const status = String(o['Status']||'Scheduled');
    const title = String(o['Title']||'');

    if (status !== 'Cancelled') planned++;
    if (status === 'Completed') {
      done++;
      const c2 = toYMD_(o['Completed_At']);
      if (c2 && date){ const diff = Math.round((parseYMD_(c2)-parseYMD_(date))/86400000); if (!isNaN(diff)&&diff>0){ delaySum+=diff; delayN++; } }
    } else if (status === 'Cancelled') {
      // ignore
    } else if (status === 'Lapsed') { lapsedCount++; }
    else if (date < todayStr) overdue++;
    else pending++;
    if (status === 'Rescheduled') reschedCount++;

    if (act){
      tally[cid].total++;
      let cell;
      if (status === 'Completed'){ cell = 'done'; tally[cid].done++; }
      else if (status === 'Cancelled'){ cell = 'cancelled'; }
      else if (date < todayStr){ cell = 'overdue'; }
      else { cell = 'pending'; }

      const g = grid[cid][act] || (grid[cid][act] = { done:0, total:0, status:'pending' });
      if (status !== 'Cancelled'){
        g.total++;
        if (cell === 'done') g.done++;
      }
      const rank = { done:3, pending:2, overdue:1, cancelled:0 };
      if (rank[cell] > rank[g.status]) g.status = cell;
    }

    if (status !== 'Completed' && status !== 'Cancelled'){
      const dDays = Math.round((parseYMD_(date) - parseYMD_(todayStr)) / 86400000);
      if (date < todayStr)
        alerts.push({ level:'overdue', text: myCompanies[cid]+' — '+(act||title)+' overdue by '+Math.abs(dDays)+' day'+(Math.abs(dDays)===1?'':'s')+'.' });
      else if (dDays <= 3)
        alerts.push({ level:'soon', text: myCompanies[cid]+' — '+(act||title)+' due '+(dDays===0?'today':'in '+dDays+' day'+(dDays===1?'':'s'))+' ('+date+').' });
    }
  });

  const clients = Object.keys(myCompanies).map(cid => {
    const t = tally[cid];
    return { companyId:cid, company:myCompanies[cid], cells:grid[cid],
      done:t.done, total:t.total, pct: t.total>0 ? Math.round((t.done/t.total)*100) : 0 };
  }).sort((a,b)=>a.company.localeCompare(b.company));

  ensureActionSheet_();
  const open = [];
  let acClosed=0, acTotal=0;
  const schedMapStaff = getScheduleLearnerDoneMap_();
  const filterActionSide = String(scope.actionSide||'').trim();   // 'Client' | 'OM' | ''
  readObjects_('Action_Items').rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    if (!myCompanies[cid]) return;
    acTotal++;
    const st = String(o['Status']||'');
    if (st === 'Closed'){ acClosed++; return; }
    const tgt = toYMD_(o['Target_Date']);
    const act2 = toYMD_(o['Actual_Date']);
    const followUp = (tgt && tgt < todayStr) ? 'Overdue — follow up' : (st || 'Pending');
    const sid = String(o['Schedule_ID']||'').trim();
    const sched = schedMapStaff[sid];
    const pendingSide = (sched && sched.learnerDone) ? 'OM' : 'Client';
    if (filterActionSide && pendingSide !== filterActionSide) return;
    const dl = actionDelayLabel_(o, schedMapStaff);
    open.push({ company:myCompanies[cid]||o['Company_Name'], activity:String(o['Activity']||''),
      action:String(o['Action']||''), owner:String(o['Owner']||''), employeeId:String(o['Employee_ID']||''),
      target:tgt, actual:act2, status:st||'Pending', delay:'', followUp:followUp,
      learnerDelay:dl.learner, staffDelay:dl.staff, pendingSide:pendingSide });
    if (tgt && tgt < todayStr)
      alerts.push({ level:'overdue', text:myCompanies[cid]+' — action "'+String(o['Action']||'')+'" overdue. Owner: '+String(o['Owner']||'HOD')+'.' });
  });

  let activeEsc = 0;
  if (ss_().getSheetByName('Escalations')) {
    readObjects_('Escalations').rows.forEach(o => {
      const cid = String(o['Company_ID']||'').trim();
      if (!myCompanies[cid]) return;
      if (String(o['Status']||'').trim() === 'Resolved') return;
      activeEsc++;
    });
  }

  const seen = {}; const uniqAlerts = [];
  alerts.sort((a,b)=> (a.level==='overdue'?0:1) - (b.level==='overdue'?0:1))
        .forEach(a => { if (!seen[a.text]){ seen[a.text]=1; uniqAlerts.push(a); } });

  const monthSet = {};
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    if (!myCompanies[String(o['Company_ID']||'').trim()]) return;
    const m = succMonthNorm_(o['Event_Date']); if (m) monthSet[m] = true;
  });
  monthSet[filterMonth] = true;
  const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  const monthOptions = Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }))
    .sort((a,b)=>{
      const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
      if(!ma||!mb) return 0;
      return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
    });

  return {
    period:{ from:from, to:to },
    smopsName: (staffMap[targetSmops]||{}).name || (u.role===ROLES.ADMIN ? 'All OMs' : u.username),
    isAdmin: (u.role === ROLES.ADMIN),
    smopsOptions: Object.keys(allSmops).map(id => ({ id:id, name:allSmops[id] })).sort((a,b)=>a.name.localeCompare(b.name)),
    selectedSmops: targetSmops || '',
    monthOptions: monthOptions,
    selectedMonth: filterMonth,
    cards: {
      clients: Object.keys(myCompanies).length,
      planned: planned, completed: done, pending: pending, overdue: overdue,
      completion: planned>0 ? Math.round((done/planned)*100) : 0,
      avgDelay: delayN>0 ? Math.round((delaySum/delayN)*10)/10 : 0,
      actionClosure: acTotal>0 ? Math.round((acClosed/acTotal)*100) : 0,
      escalations: activeEsc,
      lapsed: lapsedCount, rescheduled: reschedCount
    },
    activities: activities,
    clientsGrid: clients,
    alerts: uniqAlerts,
    openActions: open
  };
}




/*****************  LEARNER (clientAdmin) DASHBOARD  *****************/
const SUCCESS_HEADERS = ['Company_ID','Activity','Month','Activity_Implementation_Target_%','Actual_Implementation_%','Activity_Score_Target_%','Actual_Activity_Score_%','Achievement_%','Updated_At'];



/*****************  SUCCESS MEASURES AUTO-SYNC (from Activity_Tracker)  *****************/

function succMonthNorm_(v){
  if (v instanceof Date)
    return ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'][v.getMonth()] + String(v.getFullYear()).slice(-2);
  let s = String(v||'').trim(); if (!s) return '';
  if (/^\d{4}-\d{2}-\d{2}/.test(s)){ const d=parseYMD_(s.substring(0,10)); if (d) return succMonthNorm_(d); }
  s = s.toLowerCase().replace(/[^a-z0-9]/g,'');                 // "june26" / "jun26"
  const m = s.match(/^([a-z]+)(\d{2,4})$/); if (!m) return s;
  let yr = m[2]; if (yr.length===4) yr = yr.slice(-2);
  return m[1].substring(0,3) + yr;                              // "june"->"jun"
}
// canonical/Date -> display "June26"
function succMonthDisplay_(v){
  const c = (v instanceof Date) ? succMonthNorm_(v) : succMonthNorm_(v);
  const m = c.match(/^([a-z]{3})(\d{2})$/); if (!m) return String(v||'');
  const idx = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(m[1]);
  if (idx<0) return c;
  const full = ['January','February','March','April','May','June','July','August','September','October','November','December'][idx];
  return full + m[2];                                           // "June26"
}


const CAL_DISCIPLINE_ACTIVITY = 'Calendar Discipline';
const CAL_DISCIPLINE_EXCLUDE  = 'Action Closure Review';



/*****************  SUCCESS_MANUAL (per-HOD / company-wise manual scores)  *****************/
const MANUAL_HEADERS = ['Company_ID','Activity','Month','Scope','HOD_ID','HOD_Name','Score_Target_%','Actual_Score_%','Updated_By','Updated_At'];
function ensureManualSheet_(){ return ensureSheet_('Success_Manual', MANUAL_HEADERS); }

// activityLOWER -> 'hod' | 'company'  (Activity sheet ki Responsive column se)
function activityScopeMap_(){
  const obj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>obj.headers.indexOf(h)!==-1)||obj.headers[0];
  const hResp = ['Responsive','Responsible','Response'].find(h=>obj.headers.indexOf(h)!==-1);
  const map = {};
  obj.rows.forEach(o=>{
    const a=String(o[hFull]||'').trim().toLowerCase(); if(!a) return;
    const rv=hResp?String(o[hResp]||'').toLowerCase():'';
    map[a] = /hod/.test(rv) ? 'hod' : 'company';
  });
  return map;
}

// HODs of a company = employees with Role containing "hod"
function companyHods_(companyId){
  companyId = String(companyId||'').trim();
  const out = [];
  readObjects_(CFG.SHEETS.EMPLOYEES).rows.forEach(o=>{
    if (String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim() !== companyId) return;
    const role = String(o[CFG.HDR.EMP_ROLE]||'').toLowerCase();
    if (!/hod/.test(role)) return;
    const id = String(o['Employee_ID']||'').trim();
    const nm = String(o[CFG.HDR.EMP_NAME]||'').trim();
    if (id||nm) out.push({ id:id, name:nm||id });
  });
  out.sort((a,b)=>a.name.localeCompare(b.name));
  return out;
}

// read Success_Manual → { 'cid||actLOWER||month': { company:val, hods:{ hodId:{target,actual,name} } } }
function manualScoresMap_(){
  const map = {};
  if (!ss_().getSheetByName('Success_Manual')) return map;
  readObjects_('Success_Manual').rows.forEach(o=>{
    const cid=String(o['Company_ID']||'').trim();
    const act=String(o['Activity']||'').trim();
    const mon=succMonthNorm_(o['Month']);
    if (!cid||!act||!mon) return;
    const key = cid+'||'+act.toLowerCase()+'||'+mon;
    const rec = map[key] || (map[key]={ company:null, hods:{} });
    const scope = String(o['Scope']||'company').toLowerCase();
    const tgt = pctNum_(o['Score_Target_%']);
    const act2= pctNum_(o['Actual_Score_%']);
    if (scope==='hod'){
      const hid=String(o['HOD_ID']||'').trim() || String(o['HOD_Name']||'').trim();
      if (hid) rec.hods[hid] = { target:tgt, actual:act2, name:String(o['HOD_Name']||'').trim()||hid };
    } else {
      rec.company = { target:tgt, actual:act2 };
    }
  });
  return map;
}

// Activity sheet ki "Success_Measure_actual%" column = "Manual" → us activity ka Actual Score haath se bharega (sync overwrite nahi karega)
function manualActivitySet_(){
  const obj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>obj.headers.indexOf(h)!==-1)||obj.headers[0];
  const hMan  = ['Success_Measure_actual%','Success_Measure_actual','Success_Measure_Actual_%','Actual_Mode','Score_Mode'].find(h=>obj.headers.indexOf(h)!==-1);
  const set = {};
  if (!hMan) return set;
  obj.rows.forEach(o=>{
    const a = String(o[hFull]||'').trim().toLowerCase(); if(!a) return;
    if (/manual/i.test(String(o[hMan]||''))) set[a]=true;
  });
  return set;
}


/*****************  REVIEW-BASED SCORES (Accountability / Culture / Implementation)  *****************/
// Activity (lowercase) → kaunse review response sheet se score aata hai
const REVIEW_SCORE_ACTIVITIES = {
  'accountability & ownership rating': [
    { sheet:'HOD_Accountability_Responses', type:'rating' },
    { sheet:'HOD_Ownership_Responses',      type:'rating' }
  ],
  'culture rating': [
    { sheet:'HOD_Culture_Responses', type:'rating' }
  ],
  'implementation update feedback': [
    { sheet:'Implementation_update_feedback_Responses', type:'yesno' }
  ]
};
const REVIEW_MAX_RATING = 5;

// → { 'cid||actLower||month' : score% }  (company-level average)
function reviewScoreMap_(){
  const acc = {};   // key → { sum, cnt, yes, tot }
  Object.keys(REVIEW_SCORE_ACTIVITIES).forEach(actLower=>{
    REVIEW_SCORE_ACTIVITIES[actLower].forEach(src=>{
      if (!ss_().getSheetByName(src.sheet)) return;
      const obj = readObjects_(src.sheet);
      const H = obj.headers;
      const hMonth = findHeader_(H, ['Month']);
      const hCid   = findHeader_(H, ['Company_ID','CompanyID','CID']);
      const hRate  = findHeader_(H, ['Rating','Score','Value']);
      const hAns   = findHeader_(H, ['Answer','Response','Yes_No','YesNo']);
      obj.rows.forEach(r=>{
        const cid = hCid ? String(r[hCid]||'').trim() : '';
        const mon = hMonth ? succMonthNorm_(r[hMonth]) : '';
        if (!cid || !mon) return;
        const key = cid+'||'+actLower+'||'+mon;
        const g = acc[key] || (acc[key]={ sum:0, cnt:0, yes:0, tot:0 });
        if (src.type==='yesno'){
          if (hAns){ const a=String(r[hAns]||'').trim(); g.tot++; if(/^(yes|y|true|1)$/i.test(a)) g.yes++; }
        } else {
          if (hRate){ const v=Number(r[hRate]); if(!isNaN(v)){ g.sum+=v; g.cnt++; } }
        }
      });
    });
  });
  const out = {};
  Object.keys(acc).forEach(k=>{
    const g=acc[k]; let pct=null;
    if (g.tot>0) pct = Math.round((g.yes/g.tot)*100);
    else if (g.cnt>0) pct = Math.round((g.sum/(g.cnt*REVIEW_MAX_RATING))*100);
    if (pct!=null) out[k]=pct;
  });
  return out;
}

function syncSuccessMeasures(monthFilter) {
  if (monthFilter && typeof monthFilter === 'object' && !(monthFilter instanceof Date)) monthFilter = null;
  const tz = ss_().getSpreadsheetTimeZone();
  const nowStr   = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');
  const wantMonth = monthFilter ? succMonthNorm_(monthFilter) : '';

  ensureTrackerSheet_();
  const sSh = ensureSuccessSheet_();
  const manualSet = manualActivitySet_();

  const agg = {};
  const calAgg = {};
  const exclLower    = CAL_DISCIPLINE_EXCLUDE.toLowerCase();   // "action closure review"
  const calDiscLower = CAL_DISCIPLINE_ACTIVITY.toLowerCase();

  readObjects_('Activity_Tracker').rows.forEach(r => {
    const cid   = String(r['Company_ID']||'').trim();
    const act   = String(r['Activity']||'').trim();
    const month = succMonthNorm_(r['Month']) || succMonthNorm_(r['Date']);
    const st    = String(r['Status']||'').trim().toLowerCase();
    if (!cid || !act || !month) return;
    if (wantMonth && month !== wantMonth) return;
    if (st === 'cancelled') return;

    const key = cid + '||' + act.toLowerCase() + '||' + month;
    const g = agg[key] || (agg[key] = { companyId:cid, activity:act, month:month, total:0, completed:0 });
    g.total++;
    if (st === 'completed') g.completed++;

    // Calendar Discipline pool = saari activities EXCEPT Action Closure Review (aur khud Calendar Discipline)
    const al = act.toLowerCase();
    if (al !== exclLower && al !== calDiscLower){
      const ck = cid + '||' + month;
      const c = calAgg[ck] || (calAgg[ck] = { companyId:cid, month:month, total:0, completed:0 });
      c.total++;
      if (st === 'completed') c.completed++;
    }
  });

  // Calendar Discipline pseudo-activity (auto): completed÷total × 100
  Object.keys(calAgg).forEach(ck => {
    const c = calAgg[ck]; if (c.total <= 0) return;
    const key = c.companyId + '||' + calDiscLower + '||' + c.month;
    agg[key] = { companyId:c.companyId, activity:CAL_DISCIPLINE_ACTIVITY, month:c.month, total:c.total, completed:c.completed };
  });

  // existing rows index (current targets + manual actual capture)
  const manualMap = manualScoresMap_();     // Success_Manual se
  const scopeMap  = activityScopeMap_();    // hod/company per activity
  const reviewMap = reviewScoreMap_();      // Accountability/Culture/Implementation review sheets se

  // manual-only activities (jinki Activity_Tracker me occurrence nahi) ke keys bhi agg me daalo,
  // taaki unka score bhi Success_Measures me update ho (average reflect ho)
  Object.keys(manualMap).forEach(mk => {
    const parts = mk.split('||');   // cid || actLOWER || month
    if (parts.length !== 3) return;
    const mMon = parts[2];
    if (wantMonth && mMon !== wantMonth) return;
    if (!agg[mk]){
      agg[mk] = { companyId:parts[0], activity:parts[1], month:mMon, total:0, completed:0 };
    }
  });

  // review-based activities (Accountability/Culture/Implementation) ke keys bhi agg me daalo
  Object.keys(reviewMap).forEach(rk => {
    const parts = rk.split('||');   // cid || actLOWER || month
    if (parts.length !== 3) return;
    const rMon = parts[2];
    if (wantMonth && rMon !== wantMonth) return;
    if (!agg[rk]){
      agg[rk] = { companyId:parts[0], activity:parts[1], month:rMon, total:0, completed:0 };
    }
  });

  const map = getHeaderMap_(sSh);
  const cIT = map['Activity_Implementation_Target_%'];
  const cST = map['Activity_Score_Target_%'];
  const cSA = map['Actual_Activity_Score_%'];
  const lastRow = sSh.getLastRow();
  const existing = {};
  if (lastRow > 1) {
    const vals = sSh.getRange(2, 1, lastRow-1, sSh.getLastColumn()).getValues();
    const cC = map['Company_ID'], cA = map['Activity'], cM = map['Month'];
    vals.forEach((row, i) => {
      const cid = String(row[cC-1]||'').trim();
      const act = String(row[cA-1]||'').trim();
      const mon = succMonthNorm_(row[cM-1]);
      if (cid && act) existing[cid+'||'+act.toLowerCase()+'||'+mon] = {
        row: i+2,
        implTarget:  cIT ? row[cIT-1] : '',
        scoreTarget: cST ? row[cST-1] : '',
        scoreActual: cSA ? row[cSA-1] : ''
      };
    });
  }

  let updated = 0, skipped = 0;
  Object.keys(agg).forEach(key => {
    const g = agg[key];
    const ex = existing[key];
    if (!ex){ skipped++; return; }   // NO row create — seed hi rows banata hai; sync sirf update

    const actL       = g.activity.toLowerCase();
    const isReview   = !!REVIEW_SCORE_ACTIVITIES[actL];
    const isManual   = !!manualSet[actL];
    const isHod      = scopeMap[actL] === 'hod';
    const implActual = g.completed > 0 ? 100 : 0;                                    // koi occurrence complete? 100:0
    const autoScore  = g.total > 0 ? Math.round((g.completed / g.total) * 100) : 0;  // completed÷total

    // ---- Actual Score % resolve ----
    let scoreActual = autoScore;          // default: auto
    let scoreTarget = pctNum_(ex.scoreTarget);
    if (isReview){
      // review sheets se average (rating→% ya yes/no→%)
      const rs = reviewMap[key];
      scoreActual = (rs!=null) ? rs : '';
    } else if (isManual){
      const mrec = manualMap[key];
      if (isHod){
        // average of all HOD rows (jinke actual bhare hain)
        const hs = mrec ? Object.keys(mrec.hods).map(h=>mrec.hods[h]) : [];
        const acts = hs.map(h=>h.actual).filter(v=>v!=null && !isNaN(v));
        const tgts = hs.map(h=>h.target).filter(v=>v!=null && !isNaN(v));
        scoreActual = acts.length ? Math.round(acts.reduce((s,v)=>s+v,0)/acts.length) : '';
        if (tgts.length) scoreTarget = Math.round(tgts.reduce((s,v)=>s+v,0)/tgts.length);
      } else {
        const c = mrec && mrec.company;
        scoreActual = (c && c.actual!=null && !isNaN(c.actual)) ? c.actual : '';
        if (c && c.target!=null && !isNaN(c.target)) scoreTarget = c.target;
      }
    }

    const ach = (scoreTarget && scoreTarget>0 && scoreActual!=='') ? Math.round((Number(scoreActual)/scoreTarget)*100)
              : (scoreActual==='' ? '' : Number(scoreActual));

    if (map['Actual_Implementation_%']) sSh.getRange(ex.row, map['Actual_Implementation_%']).setValue(implActual + '%');
    if (cSA)  sSh.getRange(ex.row, cSA).setValue(scoreActual==='' ? '' : scoreActual + '%');
    if (map['Achievement_%']) sSh.getRange(ex.row, map['Achievement_%']).setValue(ach==='' ? '' : ach + '%');
    if (cIT && (ex.implTarget===''||ex.implTarget==null)) sSh.getRange(ex.row, cIT).setValue("'100%");
    if (cST){
      if (isManual && scoreTarget!=null && scoreTarget!=='') sSh.getRange(ex.row, cST).setValue("'"+scoreTarget+"%");
      else if (ex.scoreTarget===''||ex.scoreTarget==null) sSh.getRange(ex.row, cST).setValue("'100%");
    }
    if (map['Updated_At']) sSh.getRange(ex.row, map['Updated_At']).setValue(nowStr);
    updated++;
  });

  const summary = 'Success_Measures sync: '+updated+' updated, '+skipped+' skipped (no seeded row)'+(wantMonth?(' ['+wantMonth+']'):'');
  Logger.log(summary);
  return summary;
}


/*****************  SEED SUCCESS_MEASURES (Company × Activity × Month)  *****************/

function seedSuccessMeasures(monthArg){
  Logger.log(monthArg);
  if (monthArg && typeof monthArg === 'object' && !(monthArg instanceof Date)) monthArg = null;
  const tz = ss_().getSpreadsheetTimeZone();
  const now = new Date();
  const canonMonth = monthArg ? succMonthNorm_(monthArg) : succMonthNorm_(now);
  const dispMonth  = succMonthDisplay_(canonMonth);
  const nowStr = Utilities.formatDate(now, tz, 'yyyy-MM-dd HH:mm:ss');

  const sSh = ensureSuccessSheet_();
  const map = getHeaderMap_(sSh);

  const companies = readObjects_(CFG.SHEETS.COMPANIES).rows
    .map(o => String(o[CFG.HDR.COMPANY_ID]||'').trim()).filter(Boolean);

  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>actObj.headers.indexOf(h)!==-1)||actObj.headers[0];
  const activities = []; const seenAct={};
  actObj.rows.forEach(o=>{ const a=String(o[hFull]||'').trim(); const lk=a.toLowerCase();
    if(a && !seenAct[lk]){ seenAct[lk]=true; activities.push(a); } });

  const existKey = {};
  if (sSh.getLastRow()>1){
    const vals = sSh.getRange(2,1,sSh.getLastRow()-1,sSh.getLastColumn()).getValues();
    const cC=map['Company_ID'], cA=map['Activity'], cM=map['Month'];
    vals.forEach(r=>{
      const cid=String(r[cC-1]||'').trim(); const act=String(r[cA-1]||'').trim(); if(!cid||!act) return;
      existKey[cid+'||'+act.toLowerCase()+'||'+succMonthNorm_(r[cM-1])]=true;
    });
  }

  const append=[]; let created=0;
  companies.forEach(cid=>{
    activities.forEach(act=>{
      if (existKey[cid+'||'+act.toLowerCase()+'||'+canonMonth]) return;
      const row=new Array(sSh.getLastColumn()).fill(''); const put=(h,v)=>{ if(map[h]) row[map[h]-1]=v; };
      put('Company_ID', cid);
      put('Activity', act);
      put('Month', "'" + dispMonth);
      put('Activity_Implementation_Target_%', "'100%");
      put('Actual_Implementation_%', '');       // sync bharega
      put('Activity_Score_Target_%', "'100%");  // manual default
      put('Actual_Activity_Score_%', '');        // sync/manual
      put('Achievement_%', '');
      put('Updated_At', nowStr);
      append.push(row); created++;
    });
  });
  if (append.length) sSh.getRange(sSh.getLastRow()+1,1,append.length,sSh.getLastColumn()).setValues(append);

  try { syncSuccessMeasures(canonMonth); } catch(e){ Logger.log('seed->sync: '+e.message); }
  return 'Seeded '+created+' row(s) for '+dispMonth+' + Actual synced.';
}

// Monthly auto-run: 1st of every month ~6am (run once from editor to install)
function setupSuccessSeedTrigger(){
  ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getHandlerFunction()==='seedSuccessMeasures') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('seedSuccessMeasures').timeBased().onMonthDay(1).atHour(6).create();
  return 'Monthly seed trigger installed (1st ~6am).';
}


// Daily auto-run (install once from editor)
function setupSuccessSyncTrigger(){
  ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getHandlerFunction()==='syncSuccessMeasures') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('syncSuccessMeasures').timeBased().everyDays(1).atHour(6).create();
  return 'Success-measures sync trigger installed (daily ~6am).';
}








function ensureSuccessSheet_(){ return ensureSheet_('Success_Measures', SUCCESS_HEADERS); }

// normalize "95" | "95%" | 0.95 -> 95
function pctNum_(v){
  if (v === '' || v == null) return null;
  if (typeof v === 'number') return v <= 1 ? Math.round(v*100) : Math.round(v);
  const s = String(v).replace('%','').trim(); if (s === '') return null;
  const n = Number(s); if (isNaN(n)) return null;
  return n <= 1 ? Math.round(n*100) : Math.round(n);
}

/*=================================================== Client (Learner) Dashboard ===================================================*/
// scope: { companyId, from, to } — Learner auto-scoped to own company; Admin/Staff pass companyId
function getLearnerDashboard(token, scope) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  scope = scope || {};
  const companyId = (u.role === ROLES.LEARNER) ? u.companyId : String(scope.companyId||'').trim();
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // success-measure month filter (default = current month)
  const filterMonth = scope.month ? succMonthNorm_(scope.month) : succMonthNorm_(new Date());

  // period = selected month (operational KPIs bhi usi month ke)
  let from = scope.from, to = scope.to;
  if (!from || !to) {
    // filterMonth ("jul26") → us month ka pehla/aakhri din
    const mm = filterMonth.match(/^([a-z]{3})(\d{2})$/);
    let py, pm;
    if (mm){
      pm = ['jan','feb','mar','apr','may','jun','jul','aug','sep','oct','nov','dec'].indexOf(mm[1]);
      py = 2000 + Number(mm[2]);
    }
    if (pm == null || pm < 0){ const now = new Date(); py = now.getFullYear(); pm = now.getMonth(); }
    from = Utilities.formatDate(new Date(py, pm, 1), tz, 'yyyy-MM-dd');
    to   = Utilities.formatDate(new Date(py, pm+1, 0), tz, 'yyyy-MM-dd');
  }
  const inRange = d => d && d >= from && d <= to;

  // company name + OM
  let companyName = '', omName = '';
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
    if (String(o[CFG.HDR.COMPANY_ID]||'').trim() === companyId){
      companyName = String(o[CFG.HDR.COMPANY_NAME]||'').trim();
      const sm = staffById_(o[CFG.HDR.COMPANY_SMOPS]); omName = sm ? sm.name : '';
    }
  });

// operational metrics from schedule (this period)
  let planned=0, completed=0, pending=0, overdue=0, delaySum=0, delayN=0;
  const gridCells = {};   // activity -> { done, total, status }
  let gridDone=0, gridTotal=0;
  if (companyId) readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    if (String(o['Company_ID']||'').trim() !== companyId) return;
    const date = toYMD_(o['Event_Date']); if (!inRange(date)) return;
    const status = String(o['Status']||'Scheduled');
    if (status !== 'Cancelled') planned++;
    if (status==='Completed'){
      completed++;
      const c2=toYMD_(o['Completed_At']);
      if (c2&&date){ const diff=Math.round((parseYMD_(c2)-parseYMD_(date))/86400000); if(!isNaN(diff)&&diff>0){delaySum+=diff;delayN++;} }
    } else if (status==='Cancelled'){ /* skip */ }
    else if (date<todayStr) overdue++; else pending++;

    const act = String(o['Activity']||'').trim();
    if (act){
      let cell;
      if (status === 'Completed') cell = 'done';
      else if (status === 'Cancelled') cell = 'cancelled';
      else if (date < todayStr) cell = 'overdue';
      else cell = 'pending';
      const g = gridCells[act] || (gridCells[act] = { done:0, total:0, status:'pending' });
      if (status !== 'Cancelled'){
        g.total++; gridTotal++;
        if (cell === 'done'){ g.done++; gridDone++; }
      }
      const rank = { done:3, pending:2, overdue:1, cancelled:0 };
      if (rank[cell] > rank[g.status]) g.status = cell;
    }
  });

  // activity list (Activity sheet order) for grid header
  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull  = [CFG.HDR.ACTIVITIES,'Activity'].find(h => actObj.headers.indexOf(h)!==-1) || actObj.headers[0];
  const hShort = [CFG.HDR.ACTIVITIES_SHORTCUT,'Activity_Shortcut'].find(h => actObj.headers.indexOf(h)!==-1);
  const activities = []; const seenAct = {};
  actObj.rows.forEach(o => {
    const full = String(o[hFull]||'').trim(); if (!full || seenAct[full]) return; seenAct[full] = true;
    activities.push({ full: full, short: (hShort ? String(o[hShort]||'').trim() : '') || full });
  });

  // success-measure scorecard (snapshot, not period-bound)
  ensureSuccessSheet_();
  const rows = [];
  const monthSet = {};
  if (companyId) readObjects_('Success_Measures').rows.forEach(o => {
    if (String(o['Company_ID']||'').trim() !== companyId) return;
    const rowMon = succMonthNorm_(o['Month']); if (rowMon) monthSet[rowMon] = true;
    if (filterMonth && rowMon !== filterMonth) return;
    const implTarget = pctNum_(o['Activity_Implementation_Target_%']);
    const implActual = pctNum_(o['Actual_Implementation_%']);
    const target = pctNum_(o['Activity_Score_Target_%']), actual = pctNum_(o['Actual_Activity_Score_%']);
    if (target == null && actual == null && implActual == null) return;
    const ach = (target && target > 0) ? Math.round((actual/target)*100) : (actual||0);
    const st = ach >= 100 ? 'Met' : (ach >= 50 ? 'Partial' : 'Not Met');
    rows.push({ activity:String(o['Activity']||''),
      implTarget: implTarget==null?100:implTarget,
      implActual: implActual==null?'':implActual,
      target:target==null?'':target, actual:actual==null?'':actual,
      achievement:ach, status:st });
  });
  const total=rows.length;
  const met=rows.filter(r=>r.status==='Met').length;
  const partial=rows.filter(r=>r.status==='Partial').length;
  const notMet=rows.filter(r=>r.status==='Not Met').length;
  const avgScore=total?Math.round(rows.reduce((s,r)=>s+r.achievement,0)/total):0;
  const avgTarget=total?Math.round(rows.reduce((s,r)=>s+(Number(r.target)||0),0)/total):0;

  const completion = planned>0 ? Math.round((completed/planned)*100) : 0;
  const cStatus = completion>=95?'STRONG':completion>=85?'GOOD':completion>=70?'WATCH':'AT-RISK';

  // pending (non-closed) actions for this company
  ensureActionSheet_();
  const pendingActions=[];
  if (companyId) readObjects_('Action_Items').rows.forEach(o=>{
    if (String(o['Company_ID']||'').trim()!==companyId) return;
    if (String(o['Status']||'')==='Closed') return;
    const tgt=toYMD_(o['Target_Date']);
    const dl = actionDelayLabel_(o, getScheduleLearnerDoneMap_());
    pendingActions.push({ activity:String(o['Activity']||''), action:String(o['Action']||''),
      owner:String(o['Owner']||''), target:tgt, status:String(o['Status']||'Pending'), delay:'',
      learnerDelay:dl.learner, staffDelay:dl.staff });
  });

  return {
    company: companyName || companyId || '(no company)',
    om: omName,
    period:{from:from,to:to},
    opCards: { planned:planned, completed:completed, completion:completion, pending:pending, overdue:overdue,
      avgDelay: delayN>0?Math.round((delaySum/delayN)*10)/10:0 },
    cards: { total:total, met:met, partial:partial, notMet:notMet, avgScore:avgScore, target:avgTarget },
    completion: completion, status: cStatus,
    rows: rows,
    pendingActions: pendingActions,
    activities: activities,
    clientsGrid: [{ companyId: companyId, company: companyName || companyId,
      cells: gridCells, done: gridDone, total: gridTotal,
      pct: gridTotal>0 ? Math.round((gridDone/gridTotal)*100) : 0 }],
    selectedMonth: filterMonth,
    monthOptions: (function(){
      const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
      return Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }))
        .sort((a,b)=>{
          const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
          if(!ma||!mb) return 0;
          return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
        });
    })()
  };
}



/*****************  SUCCESS MEASURE DASHBOARD (Admin)  *****************/
function getSuccessDashboard(token, scope) {
  requireRole_(token, [ROLES.ADMIN]);
  scope = scope || {};
  ensureSuccessSheet_();

  const companyInfo = {};
  const smopsCompanies = {};
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
    const cid = String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    companyInfo[cid] = { name:String(o[CFG.HDR.COMPANY_NAME]||'').trim()||cid, smopsId:smId };
    if (smId) (smopsCompanies[smId]=smopsCompanies[smId]||[]).push(cid);
  });

  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull  = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>actObj.headers.indexOf(h)!==-1)||actObj.headers[0];
  const hShort = [CFG.HDR.ACTIVITIES_SHORTCUT,'Activity_Shortcut'].find(h=>actObj.headers.indexOf(h)!==-1);
  const activityOrder = []; const shortOf = {}; const seenA = {};
  actObj.rows.forEach(o => {
    const full = String(o[hFull]||'').trim(); if (!full || seenA[full.toLowerCase()]) return; seenA[full.toLowerCase()]=true;
    activityOrder.push(full);
    shortOf[full] = (hShort ? String(o[hShort]||'').trim() : '') || full;
  });
  if (!seenA[CAL_DISCIPLINE_ACTIVITY.toLowerCase()]){ activityOrder.push(CAL_DISCIPLINE_ACTIVITY); shortOf[CAL_DISCIPLINE_ACTIVITY]=CAL_DISCIPLINE_ACTIVITY; }

  const filterSmops   = scope.smopsId || '';
  const filterCompany = scope.companyId || '';
  const filterMonth   = scope.month ? succMonthNorm_(scope.month) : succMonthNorm_(new Date());

  const monthSet = {};
  readObjects_('Success_Measures').rows.forEach(o => { const m = succMonthNorm_(o['Month']); if (m) monthSet[m] = true; });
  const monthOptions = Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }));
  const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  monthOptions.sort((a,b)=>{
    const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
    if(!ma||!mb) return 0;
    return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
  });

  // lowercase → display (Activity-sheet order canonical)
  const displayByLower = {};
  activityOrder.forEach(f => displayByLower[f.toLowerCase()] = f);

  const perActivity = {};   // display -> { iSum,iN, tSum,tN, aSum,aN }
  const matrix = {};        // cid -> { display -> achievement }
  const clientSet = {};

  readObjects_('Success_Measures').rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    const info = companyInfo[cid]; if (!info) return;
    if (filterCompany && cid !== filterCompany) return;
    if (filterSmops && info.smopsId !== filterSmops) return;
    if (filterMonth && succMonthNorm_(o['Month']) !== filterMonth) return;

    const rawAct = String(o['Activity']||'').trim(); if (!rawAct) return;
    const full = displayByLower[rawAct.toLowerCase()] || rawAct;

    const impl   = pctNum_(o['Actual_Implementation_%']);   // Actual Implementation %
    const target = pctNum_(o['Activity_Score_Target_%']);   // Activity Score Target %
    const actual = pctNum_(o['Actual_Activity_Score_%']);   // Actual Activity Score %
    const ach = (target && target>0) ? Math.round((actual/target)*100) : (actual||0);

    clientSet[cid] = true;
    (matrix[cid] = matrix[cid] || {})[full] = ach;

    const pa = perActivity[full] || (perActivity[full] = { iSum:0,iN:0, tSum:0,tN:0, aSum:0,aN:0 });
    if (impl!=null){ pa.iSum+=impl; pa.iN++; }
    if (target!=null){ pa.tSum+=target; pa.tN++; }
    if (actual!=null){ pa.aSum+=actual; pa.aN++; }
  });

  const scorecard = activityOrder.filter(f => perActivity[f]).map(full => {
    const pa = perActivity[full];
    const implActual  = pa.iN ? Math.round(pa.iSum/pa.iN) : 0;
    const scoreTarget = pa.tN ? Math.round(pa.tSum/pa.tN) : 0;
    const scoreActual = pa.aN ? Math.round(pa.aSum/pa.aN) : 0;
    const achievement = (scoreTarget>0) ? Math.round((scoreActual/scoreTarget)*100) : scoreActual;
    const status = achievement>=100 ? 'Met' : (achievement>=50 ? 'Partial' : 'Not Met');
    return { activity:full, short:shortOf[full]||full,
      implTarget:100, implActual:implActual,
      scoreTarget:scoreTarget, scoreActual:scoreActual,
      achievement:achievement, status:status };
  });

  const scored = scorecard.length;
  const totalActivities = activityOrder.length;
  const met = scorecard.filter(r=>r.status==='Met').length;
  const partial = scorecard.filter(r=>r.status==='Partial').length;
  const notMet = scorecard.filter(r=>r.status==='Not Met').length;
  const avgScore = scored ? Math.round(scorecard.reduce((s,r)=>s+r.achievement,0)/scored) : 0;
  const avgTarget = scored ? Math.round(scorecard.reduce((s,r)=>s+r.scoreTarget,0)/scored) : 0;

  const matrixActivities = scorecard.map(r => ({ full:r.activity, short:r.short }));
  const clients = Object.keys(clientSet).map(cid => {
    const cells = matrix[cid] || {};
    const vals = matrixActivities.map(a => cells[a.full]).filter(v => v!=null && !isNaN(v));
    const avg = vals.length ? Math.round(vals.reduce((s,v)=>s+v,0)/vals.length) : 0;
    const sm = staffById_(companyInfo[cid].smopsId);
    return { company:companyInfo[cid].name, om: sm?sm.name:'', cells:cells, avg:avg };
  }).sort((a,b)=>a.company.localeCompare(b.company));

  const smopsOpts = {};
  Object.keys(companyInfo).forEach(cid => { const i=companyInfo[cid]; if (i.smopsId){ const sm=staffById_(i.smopsId); smopsOpts[i.smopsId]= sm?sm.name:i.smopsId; } });

  // ---- uploaded files for the selected company (HOD-wise / Company-wise) ----
  let uploads = [];
  if (filterCompany && ss_().getSheetByName('Task_Uploads')){
    readObjects_('Task_Uploads').rows.forEach(o=>{
      if (String(o['Company_ID']||'').trim() !== filterCompany) return;
      if (filterMonth && succMonthNorm_(o['Month']) !== filterMonth) return;
      uploads.push({
        activity: String(o['Activity']||''),
        responsive: String(o['Responsive']||''),
        month: succMonthDisplay_(succMonthNorm_(o['Month'])),
        employee: String(o['Employee_Name']||''),
        by: String(o['Uploaded_By']||''),
        name: String(o['File_Name']||''),
        url: String(o['File_URL']||''),
        at: String(o['Uploaded_At']||'')
      });
    });
    uploads.sort((a,b)=> a.activity.localeCompare(b.activity) || (b.at||'').localeCompare(a.at||''));
  }

  return {
    cards: { total:totalActivities, scored:scored, met:met, partial:partial, notMet:notMet, avgScore:avgScore, target:avgTarget },
    scorecard: scorecard,
    matrixActivities: matrixActivities,
    clients: clients,
    selectedMonth: filterMonth,
    selectedCompany: filterCompany || '',
    uploads: uploads,
    filters: {
      smops: Object.keys(smopsOpts).map(id=>({id:id,name:smopsOpts[id]})),
      companies: Object.keys(companyInfo).map(cid=>({id:cid,name:companyInfo[cid].name})).sort((a,b)=>a.name.localeCompare(b.name)),
      months: monthOptions
    }
  };
}


// Dashboard ke liye: company ki HOD list + saved manual scores (company view + HOD filter dono)
function getManualScores(token, companyId, month){
  requireRole_(token, [ROLES.ADMIN]);
  companyId = String(companyId||'').trim();
  const mon = month ? succMonthNorm_(month) : succMonthNorm_(new Date());
  const scopeMap = activityScopeMap_();
  const manualSet = manualActivitySet_();

  // activity order from Activity sheet
  const actObj = readObjects_(CFG.SHEETS.ACTIVITY);
  const hFull = [CFG.HDR.ACTIVITIES,'Activity'].find(h=>actObj.headers.indexOf(h)!==-1)||actObj.headers[0];
  const acts = [];
  const seen = {};
  actObj.rows.forEach(o=>{
    const a=String(o[hFull]||'').trim(); const l=a.toLowerCase();
    if (a && !seen[l] && manualSet[l]){ seen[l]=true; acts.push({ name:a, scope: scopeMap[l]||'company' }); }
  });

  const hods = companyId ? companyHods_(companyId) : [];
  const mm = manualScoresMap_();

  // build per-activity saved values
  const rows = acts.map(a=>{
    const key = companyId+'||'+a.name.toLowerCase()+'||'+mon;
    const rec = mm[key] || { company:null, hods:{} };
    if (a.scope === 'hod'){
      const hodVals = hods.map(h=>{
        const hv = rec.hods[h.id] || rec.hods[h.name] || {};
        return { id:h.id, name:h.name,
                 target: hv.target==null?'':hv.target, actual: hv.actual==null?'':hv.actual };
      });
      const acDone = hodVals.map(h=>h.actual).filter(v=>v!==''&&!isNaN(v));
      const avg = acDone.length ? Math.round(acDone.reduce((s,v)=>s+Number(v),0)/acDone.length) : '';
      return { activity:a.name, scope:'hod', hods:hodVals, avg:avg };
    }
    const c = rec.company || {};
    return { activity:a.name, scope:'company',
             target: c.target==null?'':c.target, actual: c.actual==null?'':c.actual };
  });

  return { companyId:companyId, month:mon, monthLabel:succMonthDisplay_(mon), hods:hods, activities:rows };
}

// Save manual score(s). payload:
//   company-wise: { companyId, month, activity, scope:'company', target, actual }
//   hod-wise:     { companyId, month, activity, scope:'hod', hodId, hodName, target, actual }
function saveManualScore(token, payload){
  const u = requireRole_(token, [ROLES.ADMIN]);
  payload = payload || {};
  const cid = String(payload.companyId||'').trim();
  const act = String(payload.activity||'').trim();
  const mon = succMonthNorm_(payload.month);
  if (!cid || !act || !mon) throw new Error('Company, activity, month required.');
  const scope = String(payload.scope||'company').toLowerCase()==='hod' ? 'hod' : 'company';
  const hodId   = String(payload.hodId||'').trim();
  const hodName = String(payload.hodName||'').trim();
  if (scope==='hod' && !hodId && !hodName) throw new Error('HOD required for HOD-wise activity.');

  const sh = ensureManualSheet_();
  const map = getHeaderMap_(sh);
  const tz = ss_().getSpreadsheetTimeZone();
  const nowStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');

  // find existing row (cid+act+mon+scope+hodId)
  let rowNum = -1;
  if (sh.getLastRow()>1){
    const vals = sh.getRange(2,1,sh.getLastRow()-1,sh.getLastColumn()).getValues();
    const cC=map['Company_ID'],cA=map['Activity'],cM=map['Month'],cS=map['Scope'],cH=map['HOD_ID'];
    for (let i=0;i<vals.length;i++){
      const r=vals[i];
      if (String(r[cC-1]||'').trim()!==cid) continue;
      if (String(r[cA-1]||'').trim().toLowerCase()!==act.toLowerCase()) continue;
      if (succMonthNorm_(r[cM-1])!==mon) continue;
      if (String(r[cS-1]||'company').toLowerCase()!==scope) continue;
      if (scope==='hod' && String(r[cH-1]||'').trim()!==hodId) continue;
      rowNum = i+2; break;
    }
  }

  const target = (payload.target===''||payload.target==null) ? '' : pctNum_(payload.target);
  const actual = (payload.actual===''||payload.actual==null) ? '' : pctNum_(payload.actual);
  const set = (rowN, h, v)=>{ if (map[h]) sh.getRange(rowN, map[h]).setValue(v); };

  if (rowNum===-1){
    const row=new Array(sh.getLastColumn()).fill(''); const put=(h,v)=>{ if(map[h]) row[map[h]-1]=v; };
    put('Company_ID',cid); put('Activity',act); put('Month',"'"+succMonthDisplay_(mon));
    put('Scope',scope); put('HOD_ID',scope==='hod'?hodId:''); put('HOD_Name',scope==='hod'?hodName:'');
    put('Score_Target_%', target===''?'':("'"+target+"%")); put('Actual_Score_%', actual===''?'':("'"+actual+"%"));
    put('Updated_By', u.username||u.email||''); put('Updated_At', nowStr);
    sh.appendRow(row);
  } else {
    set(rowNum,'Score_Target_%', target===''?'':("'"+target+"%"));
    set(rowNum,'Actual_Score_%', actual===''?'':("'"+actual+"%"));
    set(rowNum,'Updated_By', u.username||u.email||'');
    set(rowNum,'Updated_At', nowStr);
  }

  // rollup turant Success_Measures me reflect karo
  try { syncSuccessMeasures(mon); } catch(e){ Logger.log('manual->sync: '+e.message); }
  return { ok:true };
}




/*****************  ESCALATION DASHBOARD (Admin)  *****************/
const ESCALATION_HEADERS = [
  'Escalation_ID','Company_ID','Company_Name','OM','Activity','Target_Date','Actual_Date',
  'Status','Escalated_To','Escalation_Date','Last_Reminder','Resolution_Date',
  'Resolution_Method','Resolved_By','Recommended_Action','Schedule_ID'
];


/*=================================================== AUTO-FEED ===================================================*/
// Derives Action_Items + Escalations from overdue Calendar_Schedule items.
// IDEMPOTENT: keyed by Schedule_ID. Re-running updates the same rows (no duplicates).
// SAFE: only touches auto-rows (rows carrying a Schedule_ID). Manual rows (blank Schedule_ID) are never modified.
// RULES (per reference):
//   overdue >= 1 day  -> open Action_Item (follow-up tracker)
//   overdue >= 5 days -> active Escalation (HOD T+5 -> HR T+7 -> MD T+10)
//   activity Completed -> auto-close the action & resolve the escalation
const AUTO_ESCALATION_MIN_DAYS = 5;
const AUTO_ACTION_MIN_DAYS = 1;

function syncAutoFeed() {
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  const nowStr   = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');
  const daysBetween = (a,b) => Math.round((parseYMD_(b)-parseYMD_(a))/86400000);

  // company -> { name, om, hodEmail }
  const staffList = getStaffList_(); const staffMap={}; staffList.forEach(s=>staffMap[s.id]=s);
  const companyInfo = {};
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
    const cid=String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId=String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    companyInfo[cid]={ name:String(o[CFG.HDR.COMPANY_NAME]||'').trim()||cid, om:(staffMap[smId]||{}).name||'' };
  });

  const sched = readObjects_(CFG.SHEETS.SCHEDULE).rows;

  /* ---------- ACTION ITEMS ---------- */
  const aSh = ensureActionSheet_();
  const aMap = getHeaderMap_(aSh);
  const aVals = aSh.getDataRange().getValues();
  const aHdr = aVals[0].map(h=>String(h).trim()); const aIdx={}; aHdr.forEach((h,i)=>aIdx[h]=i);
  const aBySched = {};                                  // schId -> rowNumber (auto rows only)
  for (let i=1;i<aVals.length;i++){ const sid=String(aVals[i][aIdx['Schedule_ID']]||'').trim(); if (sid) aBySched[sid]=i+1; }

  const aAppend=[]; let aCreated=0, aClosed=0;
  sched.forEach(o=>{
    const id=String(o['Schedule_ID']||''); if(!id) return;
    const cid=String(o['Company_ID']||'').trim();
    const info=companyInfo[cid]||{name:String(o['Company_Name']||''),om:''};
    const status=String(o['Status']||'Scheduled');
    const date=toYMD_(o['Event_Date']);
    const activity=String(o['Activity']||'');
    const title=String(o['Title']||'');
    const overdue = date ? daysBetween(date,todayStr) : 0;
    const rowNum=aBySched[id];

    if (status==='Completed' || status==='Cancelled'){
      if (rowNum && String(aVals[rowNum-1][aIdx['Status']]||'')!=='Closed'){
        if (aMap['Status']) aSh.getRange(rowNum,aMap['Status']).setValue('Closed');
        const c2 = toYMD_(o['Completed_At']);
        const ldAt = toYMD_(o['Learner_Done_At']);
        const totalDly = (c2 && date) ? Math.max(0, daysBetween(date,c2)) : 0;
        let learnerDly = totalDly, staffDly = 0;
        if (ldAt && date){
          learnerDly = Math.max(0, daysBetween(date, ldAt));
          if (c2) staffDly = Math.max(0, daysBetween(ldAt, c2));
        }
        if (aMap['Delay_Days']) aSh.getRange(rowNum,aMap['Delay_Days']).setValue(totalDly);
        if (aMap['Learner_Delay_Days']) aSh.getRange(rowNum,aMap['Learner_Delay_Days']).setValue(learnerDly);
        if (aMap['Staff_Delay_Days']) aSh.getRange(rowNum,aMap['Staff_Delay_Days']).setValue(staffDly);
        aClosed++;
      }
      return;
    }
    if (overdue >= AUTO_ACTION_MIN_DAYS){
      if (rowNum){
        if (aMap['Delay_Days']) aSh.getRange(rowNum,aMap['Delay_Days']).setValue(overdue);
      } else {
        const assigners = splitCsv_(String(o['Company_Assigners']||''));
        const eInfo = doerInfoMap_(cid);
        const ownerName = assigners[0] || 'HOD';
        const ownerInfo = assigners[0] ? (eInfo[assigners[0].toLowerCase()] || {}) : {};
        const r=new Array(aSh.getLastColumn()).fill(''); const put=(h,v)=>{ if(aMap[h]) r[aMap[h]-1]=v; };
        put('Action_ID','ACT-'+Date.now()+'-'+id);
        put('Schedule_ID',id); put('Company_ID',cid); put('Company_Name',info.name);
        put('Activity',activity); put('Action','Follow up: '+(activity||title));
        put('Owner',ownerName); put('Owner_Email',ownerInfo.email||'');
        put('Employee_ID',ownerInfo.id||'');
        put('Target_Date',date); put('Status','Pending');
        put('Delay_Days',overdue); put('Created_At',nowStr);
        aAppend.push(r); aCreated++;
      }
    }
  });
  if (aAppend.length) aSh.getRange(aSh.getLastRow()+1,1,aAppend.length,aSh.getLastColumn()).setValues(aAppend);

  /* ---------- ESCALATIONS ---------- */
  const eSh = ensureSheet_('Escalations', ESCALATION_HEADERS);
  const eMap = getHeaderMap_(eSh);
  const eVals = eSh.getDataRange().getValues();
  const eHdr = eVals[0].map(h=>String(h).trim()); const eIdx={}; eHdr.forEach((h,i)=>eIdx[h]=i);
  const eBySched = {};
  for (let i=1;i<eVals.length;i++){ const sid=String(eVals[i][eIdx['Schedule_ID']]||'').trim(); if (sid) eBySched[sid]=i+1; }

  const eAppend=[]; let eCreated=0, eResolved=0;
  sched.forEach(o=>{
    const id=String(o['Schedule_ID']||''); if(!id) return;
    const cid=String(o['Company_ID']||'').trim();
    const info=companyInfo[cid]||{name:String(o['Company_Name']||''),om:''};
    const status=String(o['Status']||'Scheduled');
    const date=toYMD_(o['Event_Date']);
    const activity=String(o['Activity']||'');
    const overdue = date ? daysBetween(date,todayStr) : 0;
    const rowNum=eBySched[id];

    if (status==='Completed' || status==='Cancelled'){
      if (rowNum && String(eVals[rowNum-1][eIdx['Status']]||'')!=='Resolved'){
        const c2=toYMD_(o['Completed_At'])||todayStr;
        if (eMap['Status']) eSh.getRange(rowNum,eMap['Status']).setValue('Resolved');
        if (eMap['Actual_Date']) eSh.getRange(rowNum,eMap['Actual_Date']).setValue(c2);
        if (eMap['Resolution_Date']) eSh.getRange(rowNum,eMap['Resolution_Date']).setValue(c2);
        if (eMap['Resolution_Method'] && !eVals[rowNum-1][eIdx['Resolution_Method']]) eSh.getRange(rowNum,eMap['Resolution_Method']).setValue('Auto: activity completed');
        if (eMap['Resolved_By'] && !eVals[rowNum-1][eIdx['Resolved_By']]) eSh.getRange(rowNum,eMap['Resolved_By']).setValue(info.om||'System');
        eResolved++;
      }
      return;
    }
    if (overdue >= AUTO_ESCALATION_MIN_DAYS){
      const lv=escLevel_(overdue);
      if (rowNum){
        if (eMap['Escalated_To']) eSh.getRange(rowNum,eMap['Escalated_To']).setValue(lv.to);
        if (eMap['Last_Reminder']) eSh.getRange(rowNum,eMap['Last_Reminder']).setValue(todayStr);
      } else {
        const r=new Array(eSh.getLastColumn()).fill(''); const put=(h,v)=>{ if(eMap[h]) r[eMap[h]-1]=v; };
        put('Escalation_ID','ESC-'+Date.now()+'-'+id);
        put('Schedule_ID',id); put('Company_ID',cid); put('Company_Name',info.name); put('OM',info.om);
        put('Activity',activity); put('Target_Date',date); put('Status','Active');
        put('Escalated_To',lv.to); put('Escalation_Date',todayStr); put('Last_Reminder',todayStr);
        put('Recommended_Action','Auto: '+(activity||'activity')+' overdue '+overdue+' days — escalate to '+lv.to);
        eAppend.push(r); eCreated++;
      }
    }
  });
  if (eAppend.length) eSh.getRange(eSh.getLastRow()+1,1,eAppend.length,eSh.getLastColumn()).setValues(eAppend);

  const summary='Auto-feed: actions +'+aCreated+'/closed '+aClosed+', escalations +'+eCreated+'/resolved '+eResolved;
  Logger.log(summary);
  return summary;
}

// Install a daily trigger (run once from the editor)
function setupAutoFeedTrigger(){
  ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getHandlerFunction()==='syncAutoFeed') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('syncAutoFeed').timeBased().everyDays(1).atHour(6).create();
  return 'Auto-feed trigger installed (daily ~6am).';
}


function ensureEscalationSheet_(){ return ensureSheet_('Escalations', ESCALATION_HEADERS); }

function escLevel_(daysOverdue){
  if (daysOverdue >= 10) return { lvl:3, to:'MD' };
  if (daysOverdue >= 7)  return { lvl:2, to:'HR' };
  if (daysOverdue >= 5)  return { lvl:1, to:'HOD' };
  return { lvl:0, to:'' };
}

// scope: { smopsId, companyId } optional
function getEscalationDashboard(token, scope) {
  requireRole_(token, [ROLES.ADMIN]);
  scope = scope || {};
  try { syncAutoFeed(); } catch(e){ Logger.log('autofeed: '+e.message); }
  ensureEscalationSheet_();
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  const now = new Date();
  const monthPrefix = Utilities.formatDate(now, tz, 'yyyy-MM');  // current calendar month

  // company -> { name, smopsId }
  const companyInfo = {};
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
    const cid = String(o[CFG.HDR.COMPANY_ID]||'').trim();
    const smId = String(o[CFG.HDR.COMPANY_SMOPS]||'').trim();
    companyInfo[cid] = { name:String(o[CFG.HDR.COMPANY_NAME]||'').trim()||cid, smopsId:smId };
  });

  const filterSmops = scope.smopsId || '';
  const filterCompany = scope.companyId || '';

  const daysBetween = (a, b) => Math.round((parseYMD_(b) - parseYMD_(a)) / 86400000);

  const active = [], resolved = [];
  let overdueSum = 0, overdueN = 0, resDaysSum = 0, resN = 0;
  let l1 = 0, l2 = 0, l3 = 0;

  readObjects_('Escalations').rows.forEach(o => {
    const cid = String(o['Company_ID']||'').trim();
    const info = companyInfo[cid] || { name:String(o['Company_Name']||''), smopsId:'' };
    if (filterCompany && cid !== filterCompany) return;
    if (filterSmops && info.smopsId !== filterSmops) return;

    const status = String(o['Status']||'').trim();
    const target = toYMD_(o['Target_Date']);
    const actual = toYMD_(o['Actual_Date']);
    const om = String(o['OM']||'') || (staffById_(info.smopsId)||{}).name || '';

    if (status === 'Resolved') {
      const escDate = toYMD_(o['Escalation_Date']);
      const resDate = toYMD_(o['Resolution_Date']);
      if (resDate && resDate.indexOf(monthPrefix) === 0) {
        const taken = (escDate && resDate) ? daysBetween(escDate, resDate) : '';
        if (taken !== '' && !isNaN(taken)) { resDaysSum += taken; resN++; }
        resolved.push({ company:info.name||cid, om:om, activity:String(o['Activity']||''),
          escDate:escDate, resDate:resDate, daysTaken:(taken===''?'':taken),
          method:String(o['Resolution_Method']||''), resolvedBy:String(o['Resolved_By']||'') });
      }
      return;
    }

    // Active: compute overdue days & level
 const overdue = target ? daysBetween(target, todayStr) : 0;
    if (overdue > 0) { overdueSum += overdue; overdueN++; }
    const lv = escLevel_(overdue);
    if (lv.lvl === 1) l1++; else if (lv.lvl === 2) l2++; else if (lv.lvl === 3) l3++;

    active.push({ company:info.name||cid, om:om, activity:String(o['Activity']||''),
      daysOverdue:overdue, level:lv.lvl, levelLabel:(lv.lvl?('Level '+lv.lvl):'—'),
      escalatedTo:String(o['Escalated_To']||'')||lv.to,
      escDate:toYMD_(o['Escalation_Date']), lastReminder:toYMD_(o['Last_Reminder']),
      status:'Active', recommended:String(o['Recommended_Action']||'') });
  });

  active.sort((a,b)=>b.daysOverdue - a.daysOverdue);
  resolved.sort((a,b)=>(b.resDate||'').localeCompare(a.resDate||''));

  // smops filter options
  const smopsOpts = {};
  Object.keys(companyInfo).forEach(cid => { const i=companyInfo[cid]; if (i.smopsId){ const sm=staffById_(i.smopsId); smopsOpts[i.smopsId]= sm?sm.name:i.smopsId; } });

  return {
    cards: {
      activeCount: active.length,
      avgOverdue: overdueN ? Math.round((overdueSum/overdueN)*10)/10 : 0,
      resolvedMonth: resolved.length,
      avgResolution: resN ? Math.round((resDaysSum/resN)*10)/10 : 0,
      l1:l1, l2:l2, l3:l3
    },
    active: active,
    resolved: resolved,
    filters: {
      smops: Object.keys(smopsOpts).map(id=>({id:id,name:smopsOpts[id]})),
      companies: Object.keys(companyInfo).map(cid=>({id:cid,name:companyInfo[cid].name})).sort((a,b)=>a.name.localeCompare(b.name))
    }
  };
}



//-----------------------------------------------REPORT---------------------------------------------------------

/*****************  LOGS REPORT (Admin) — WhatsApp / Email logs + calendar data  *****************/
// type: 'whatsapp' | 'email'.  scope: { status, side, from, to }
function getLogsReport(token, type, scope) {
  requireRole_(token, [ROLES.ADMIN]);
  type = String(type||'whatsapp').toLowerCase();
  scope = scope || {};
  const statusFilter = String(scope.status||'').trim().toLowerCase();
  const sideFilter   = String(scope.side||'').trim().toLowerCase();
  const fromD = String(scope.from||'').trim();   // yyyy-MM-dd
  const toD   = String(scope.to||'').trim();
  const tz = ss_().getSpreadsheetTimeZone();

  const fmtTs = (v) => {
    if (v instanceof Date) return Utilities.formatDate(v, tz, 'yyyy-MM-dd HH:mm:ss');
    const s = String(v||'').trim();
    const d = new Date(s);
    if (!isNaN(d.getTime())) return Utilities.formatDate(d, tz, 'yyyy-MM-dd HH:mm:ss');
    return s;
  };
  const dayOf = (tsStr) => String(tsStr||'').substring(0,10);

  // schedule lookup by Schedule_ID
  const schedMap = {};
  readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
    const id = String(o['Schedule_ID']||'').trim(); if (!id) return;
    schedMap[id] = {
      activity: String(o['Activity']||''), company: String(o['Company_Name']||''),
      date: toYMD_(o['Event_Date']), time: toHM_(o['Event_Time']),
      title: String(o['Title']||''),
      status: String(o['Status']||''),
      doers: String(o['Company_Assigners']||'')
    };
  });

  let columns = [], rows = [];
  let total = 0, sent = 0, failed = 0, skipped = 0;
  const byDay = {};   // yyyy-MM-dd -> count

  const passDate = (day) => {
    if (fromD && day < fromD) return false;
    if (toD && day > toD) return false;
    return true;
  };

  if (type === 'email') {
    columns = ['Timestamp','Side','Recipient','Email','Subject','Log Status','Error',
               'Schedule_ID','Activity','Company','Event Date','Time','Session','Cal Status','Form Link'];
    if (ss_().getSheetByName('Scheduled_logs')) {
      readObjects_('Scheduled_logs').rows.forEach(o => {
        const st = String(o['Status']||'');
        const ts = fmtTs(o['Timestamp']); const day = dayOf(ts);
        const side = String(o['Side']||'');
        if (!passDate(day)) return;
        if (statusFilter && st.toLowerCase().indexOf(statusFilter) === -1) return;
        if (sideFilter && side.toLowerCase() !== sideFilter) return;
        total++; if (/sent/i.test(st)) sent++; else if (/fail/i.test(st)) failed++; else skipped++;
        if (day) byDay[day] = (byDay[day]||0)+1;
        const sid = String(o['Schedule_ID']||'').trim(); const s = schedMap[sid] || {};
        rows.push([ ts, side, String(o['Recipient_Name']||''), String(o['Recipient_Email']||''),
          String(o['Subject']||''), st, String(o['Error']||''),
          sid, s.activity || String(o['Activity']||''), s.company || String(o['Company_Name']||''),
          s.date||'', s.time||'', s.session||'', s.status||'', String(o['Form_Link']||'') ]);
      });
    }
  } else {
    columns = ['Timestamp','Action','Side','Recipient','Phone','Log Status','Error',
               'Schedule_ID','Activity','Company','Event Date','Time','Session','Cal Status','Form URL'];
    if (ss_().getSheetByName('Whatsapp_logs')) {
      readObjects_('Whatsapp_logs').rows.forEach(o => {
        const st = String(o['Status']||'');
        const ts = fmtTs(o['Timestamp']); const day = dayOf(ts);
        const side = String(o['Side']||'');
        if (!passDate(day)) return;
        if (statusFilter && st.toLowerCase().indexOf(statusFilter) === -1) return;
        if (sideFilter && side.toLowerCase() !== sideFilter) return;
        total++; if (/sent/i.test(st)) sent++; else if (/fail/i.test(st)) failed++; else skipped++;
        if (day) byDay[day] = (byDay[day]||0)+1;
        const sid = String(o['Schedule_ID']||'').trim(); const s = schedMap[sid] || {};
        rows.push([ ts, String(o['Action']||''), side, String(o['Recipient']||''), String(o['Phone']||''),
          st, String(o['Error']||''),
          sid, s.activity||'', s.company||'', s.date||'', s.time||'', s.session||'', s.status||'',
          String(o['Form_URL']||'') ]);
      });
    }
  }

  rows.sort((a,b) => String(b[0]).localeCompare(String(a[0])));   // newest first
  const cap = 3000; const truncated = rows.length > cap;
  if (truncated) rows = rows.slice(0, cap);

  // last 14 active days for mini sparkline
  const days = Object.keys(byDay).sort().slice(-14).map(d => ({ day:d, count:byDay[d] }));

  return { type:type, columns:columns, rows:rows,
    counts:{ total:total, sent:sent, failed:failed, skipped:skipped },
    spark:days, truncated:truncated };
}










//---------------------------------------------------Profile page-------------------------------------------


/*****************  PROFILE  *****************/
// Returns the full profile for the logged-in user (Staff or Employee).
function getProfile(token) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);

  if (u.side === 'staff') {
    const { rows } = readObjects_(CFG.SHEETS.STAFF);
    const o = rows.find(r => String(r[CFG.HDR.STAFF_ID] || '').trim() === String(u.staffId).trim())
           || rows.find(r => String(r[CFG.HDR.STAFF_EMAIL] || '').trim().toLowerCase() === String(u.email).trim().toLowerCase());
    if (!o) throw new Error('Profile not found.');
    return {
      side: 'staff',
      role: u.role,
      fields: [
        ['Staff ID',    String(o[CFG.HDR.STAFF_ID]   || '')],
        ['Name',        String(o[CFG.HDR.STAFF_NAME] || '')],
        ['Email',       String(o[CFG.HDR.STAFF_EMAIL]|| '')],
        ['Department',  String(o[CFG.HDR.STAFF_DEPT] || '')],
        ['Role',        String(o[CFG.HDR.STAFF_ROLE] || '')]
      ]
    };
  }

  // employee (Learner)
  const { rows } = readObjects_(CFG.SHEETS.EMPLOYEES);
  const o = rows.find(r => String(r[CFG.HDR.EMP_EMAIL] || '').trim().toLowerCase() === String(u.email).trim().toLowerCase());
  if (!o) throw new Error('Profile not found.');

  // company name lookup
  let companyName = String(o[CFG.HDR.EMP_COMPANY_ID] || '');
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(c => {
    if (String(c[CFG.HDR.COMPANY_ID] || '').trim() === String(o[CFG.HDR.EMP_COMPANY_ID] || '').trim())
      companyName = String(c[CFG.HDR.COMPANY_NAME] || companyName);
  });

  return {
    side: 'employee',
    role: u.role,
    fields: [
      ['Employee ID', String(o['Employee_ID'] || '')],
      ['Name',        String(o[CFG.HDR.EMP_NAME]  || '')],
      ['Email',       String(o[CFG.HDR.EMP_EMAIL] || '')],
      ['Company',     companyName],
      ['Department',  String(o[CFG.HDR.EMP_DEPT]  || '')],
      ['Role',        String(o[CFG.HDR.EMP_ROLE]  || '')]
    ]
  };
}

// Verifies old password, then writes the new one to the right sheet/row.
function changePassword(token, oldPass, newPass) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  oldPass = String(oldPass || '');
  newPass = String(newPass || '');

  if (!oldPass || !newPass) return { ok: false, error: 'Both old and new passwords are required.' };
  if (newPass.length < 6)   return { ok: false, error: 'New password must be at least 6 characters.' };
  if (newPass === oldPass)  return { ok: false, error: 'New password must be different from the old one.' };

  const sheetName = (u.side === 'staff') ? CFG.SHEETS.STAFF : CFG.SHEETS.EMPLOYEES;
  const emailHdr  = (u.side === 'staff') ? CFG.HDR.STAFF_EMAIL : CFG.HDR.EMP_EMAIL;
  const passHdr   = (u.side === 'staff') ? CFG.HDR.STAFF_PASS  : CFG.HDR.EMP_PASS;

  const sh = ss_().getSheetByName(sheetName);
  if (!sh) return { ok: false, error: 'Sheet not found.' };
  const map = getHeaderMap_(sh);
  if (!map[emailHdr] || !map[passHdr]) return { ok: false, error: 'Required columns missing.' };

  const last = sh.getLastRow();
  const emails = sh.getRange(2, map[emailHdr], last - 1, 1).getValues();
  const passes = sh.getRange(2, map[passHdr],  last - 1, 1).getValues();

  const want = String(u.email).trim().toLowerCase();
  for (let i = 0; i < emails.length; i++) {
    if (String(emails[i][0] || '').trim().toLowerCase() !== want) continue;
    // verify old password (plain-text, matching authenticateUser)
    if (String(passes[i][0] || '') !== oldPass)
      return { ok: false, error: 'Current password is incorrect.' };
    sh.getRange(i + 2, map[passHdr]).setValue(newPass);
    return { ok: true };
  }
  return { ok: false, error: 'Account not found.' };
}




/*****************  HOD DASHBOARD (self / admin-pick) — HOD as a single doer  *****************/
// scope: { employeeId, from, to } — Learner forced to self; Admin/Staff may pass employeeId.
function getHodDashboard(token, scope) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  scope = scope || {};
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // period (default = current month)
  let from = scope.from, to = scope.to;
  if (!from || !to) {
    const now = new Date();
    from = Utilities.formatDate(new Date(now.getFullYear(), now.getMonth(), 1), tz, 'yyyy-MM-dd');
    to   = Utilities.formatDate(new Date(now.getFullYear(), now.getMonth()+1, 0), tz, 'yyyy-MM-dd');
  }
  const inRange = d => d && d >= from && d <= to;

  // companies owned by this Staff (to scope the HOD picker); Learner = own company only
  let ownCompanies = null;
  if (u.role === ROLES.STAFF && u.staffId) {
    ownCompanies = {};
    readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
      if (String(o[CFG.HDR.COMPANY_SMOPS]||'').trim() === u.staffId)
        ownCompanies[String(o[CFG.HDR.COMPANY_ID]||'').trim()] = true;
    });
  } else if (u.role === ROLES.LEARNER && u.companyId) {
    ownCompanies = { [String(u.companyId).trim()]: true };
  }

  // index employees + company names
  const emps = readObjects_(CFG.SHEETS.EMPLOYEES).rows;
  const empById = {};
  emps.forEach(o => { const id = String(o['Employee_ID']||'').trim(); if (id) empById[id] = o; });
  const compName = {};
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o =>
    compName[String(o[CFG.HDR.COMPANY_ID]||'').trim()] = String(o[CFG.HDR.COMPANY_NAME]||'').trim());

  // HOD picker = distinct HOD_IDs across Company_Employees, resolved to employees
  const seenHod = {}, hodList = [];
  emps.forEach(o => {
    String(o['HOD_IDs']||'').split(/[,;|]/).map(s=>s.trim()).filter(Boolean).forEach(hid => {
      if (seenHod[hid]) return; seenHod[hid] = true;
      const e = empById[hid]; if (!e) return;
      const cid = String(e['Company_ID']||'').trim();
      if (ownCompanies && !ownCompanies[cid]) return;
      hodList.push({ id:hid, name:String(e['Employee_Name']||'').trim()||hid, companyId:cid, company:compName[cid]||cid });
    });
  });
  hodList.sort((a,b)=>a.name.localeCompare(b.name));

  // resolve target HOD — Learner (MD) bhi apni company ke HODs pick kar sakta hai
  let targetId = String(scope.employeeId||'').trim();
  if (!targetId){
    if (u.role === ROLES.LEARNER){
      const me = emps.find(o => String(o['Employee_Email']||'').trim().toLowerCase() === String(u.email).trim().toLowerCase());
      const myId = me ? String(me['Employee_ID']||'').trim() : '';
      targetId = (myId && hodList.some(h=>h.id===myId)) ? myId : (hodList[0] ? hodList[0].id : myId);
    } else {
      targetId = hodList[0] ? hodList[0].id : '';
    }
  }

  const hodRow = empById[targetId] || null;
  const hodCid = hodRow ? String(hodRow['Company_ID']||'').trim() : '';
  const hod = {
    id: targetId,
    name: hodRow ? String(hodRow['Employee_Name']||'').trim() : (targetId || '(none)'),
    company: compName[hodCid] || hodCid || '',
    department: hodRow ? String(hodRow['Department']||'').trim() : '',
    email: hodRow ? String(hodRow['Employee_Email']||'').trim() : ''
  };

  // ---- Activity_Tracker scoring (this HOD only) ----
  ensureTrackerSheet_();
  const groups = {};              // activity||month
  const myScheduleIds = {};
  const trackerRows = [];         // raw occurrences for detail table
  let planned=0, completed=0, missed=0, pending=0;
  const alerts = [];

  if (targetId) readObjects_('Activity_Tracker').rows.forEach(r => {
    if (String(r['Employee_ID']||'').trim() !== targetId) return;
    const date = toYMD_(r['Date']); if (!inRange(date)) return;
    const st = String(r['Status']||'').trim().toLowerCase();
    if (st === 'cancelled') return;                       // cancelled drops out entirely
    const activity = String(r['Activity']||'').trim();
    const month = trackerMonthKey_(r['Month']) || trackerMonthKey_(date);
    const sid = String(r['Schedule_ID']||'').trim(); if (sid) myScheduleIds[sid] = true;

    let cell;
    if (st === 'completed') { completed++; cell='done'; }
    else if (st === 'missed') { missed++; cell='missed'; }
    else if (date < todayStr) { missed++; cell='missed'; }   // auto-missed: past & not done
    else { pending++; cell='pending'; }
    planned++;

    const key = activity + '||' + month;
    const g = groups[key] || (groups[key] = { activity:activity, month:month, total:0, completed:0, missed:0, pending:0 });
    g.total++;
    if (cell==='done') g.completed++; else if (cell==='missed') g.missed++; else g.pending++;

    trackerRows.push({ date:date, month:month, activity:activity,
      status: (cell==='done'?'Completed':(cell==='missed'?'Missed':(st.charAt(0).toUpperCase()+st.slice(1)||'Scheduled'))) });

    if (cell==='missed') alerts.push({ level:'overdue', text: activity+' on '+date+' missed (not completed).' });
    else if (cell==='pending') {
      const dDays = Math.round((parseYMD_(date)-parseYMD_(todayStr))/86400000);
      if (dDays <= 3) alerts.push({ level:'soon', text: activity+' due '+(dDays===0?'today':'in '+dDays+' day'+(dDays===1?'':'s'))+' ('+date+').' });
    }
  });

  const scoreRows = Object.keys(groups).map(k => {
    const g = groups[k];
    g.label = g.completed + '/' + g.total;
    g.score = g.total>0 ? Math.round((g.completed/g.total)*100) : 0;
    return g;
  }).sort((a,b)=> (a.month||'').localeCompare(b.month||'') || a.activity.localeCompare(b.activity));

  // ---- Action_Items linked to this HOD's schedules ----
  ensureActionSheet_();
  const openActions = []; let acClosed=0, acTotal=0;
  const schedMapHod = getScheduleLearnerDoneMap_();
  readObjects_('Action_Items').rows.forEach(o => {
    const sid = String(o['Schedule_ID']||'').trim();
    if (!sid || !myScheduleIds[sid]) return;
    acTotal++;
    const st = String(o['Status']||'');
    if (st === 'Closed') { acClosed++; return; }
    const tgt = toYMD_(o['Target_Date']);
    const followUp = (tgt && tgt < todayStr) ? 'Overdue — follow up' : (st || 'Pending');
    const dl = actionDelayLabel_(o, schedMapHod);
    openActions.push({ activity:String(o['Activity']||''), action:String(o['Action']||''),
      owner:String(o['Owner']||''), employeeId:String(o['Employee_ID']||''),
      target:tgt, status:st||'Pending', delay:'', followUp:followUp,
      learnerDelay:dl.learner, staffDelay:dl.staff });
    if (tgt && tgt < todayStr) alerts.push({ level:'overdue', text:'Action "'+String(o['Action']||'')+'" overdue.' });
  });

  // dedupe alerts (overdue first)
  const seen = {}, uniq = [];
  alerts.sort((a,b)=>(a.level==='overdue'?0:1)-(b.level==='overdue'?0:1))
        .forEach(a => { if (!seen[a.text]) { seen[a.text]=1; uniq.push(a); } });

  return {
    period: { from:from, to:to },
    canPick: true,   // Learner/MD bhi apni company ke HODs pick kar sakta hai (list already scoped)
    hodOptions: hodList,
    selectedHod: targetId,
    hod: hod,
    cards: {
      activities: planned, completed: completed, missed: missed, pending: pending,
      completion: planned>0 ? Math.round((completed/planned)*100) : 0,
      openActions: openActions.length,
      actionClosure: acTotal>0 ? Math.round((acClosed/acTotal)*100) : 0
    },
    scoreRows: scoreRows,
    tracker: trackerRows.sort((a,b)=> (a.date||'').localeCompare(b.date||'') || a.activity.localeCompare(b.activity)),
    alerts: uniq,
    openActions: openActions
  };
}


function seedWhatsappVariableCatalog(){
  const vSh = ensureSheet_(WA.SHEET_VARIABLES, WA_VARIABLE_HEADERS);
  const vMap = getHeaderMap_(vSh);

  // saare data-fields jo mail/WhatsApp maps me available hote hain
  const FIELDS = [
    'Title','Activity','Company_Name','Event_Date','Event_Time',
    'Status','Departments','Staff_Assigner','Company_Assigners',
    'Comment','Form_URL','Recipient_Name'
  ];
  const ACTIONS = ['schedule','reminder','reschedule','cancel','completed'];
  const SIDES   = ['company','staff'];

  // existing keys
  const existing = {};
  if (vSh.getLastRow() > 1){
    const vals = vSh.getRange(2,1,vSh.getLastRow()-1,vSh.getLastColumn()).getValues();
    const cA=vMap['Action'], cS=vMap['Side'], cV=vMap['Variable'];
    vals.forEach(r => existing[
      String(r[cA-1]||'').trim().toLowerCase()+'||'+String(r[cS-1]||'').trim().toLowerCase()+'||'+String(r[cV-1]||'').trim().toLowerCase()
    ]=true);
  }

  const append=[]; let created=0;
  ACTIONS.forEach(action=>{
    SIDES.forEach(side=>{
      FIELDS.forEach((f,i)=>{
        const k = action+'||'+side+'||'+f.toLowerCase();
        if (existing[k]) return; existing[k]=true;
        const row=new Array(vSh.getLastColumn()).fill(''); const put=(h,v)=>{ if(vMap[h]) row[vMap[h]-1]=v; };
        put('Action',action); put('Side',side); put('Position',i+1);
        put('Variable',f); put('Source_Field',f);   // variable name = field name (self-map)
        append.push(row); created++;
      });
    });
  });
  if (append.length) vSh.getRange(vSh.getLastRow()+1,1,append.length,vSh.getLastColumn()).setValues(append);
  return 'Catalog seeded: '+created+' variable row(s) across '+ACTIONS.length+' actions × '+SIDES.length+' sides.';
}



//----------------------------------------------------REVIEW REPORTS------------------------------------------


/*****************  REVIEW REPORTS (Admin / OM / HOD)  *****************/
// status: { high:'…', mid:'…', low:'…' }  → applied at ≥85 / 70-84 / <70
const REVIEW_REPORT_SOURCES = [
  { id:'accountability', label:'Accountability', sheet:'HOD_Accountability_Responses',
    status:{ high:'Accountable', mid:'Partially Accountable', low:'Non-Accountable' } },
  { id:'ownership', label:'Ownership', sheet:'HOD_Ownership_Responses',
    status:{ high:'Taking Ownership', mid:'Lack of Ownership', low:'Irresponsible' } },
  { id:'culture', label:'Culture', sheet:'HOD_Culture_Responses',
    status:{ high:'Follows Culture', mid:'Knows but not Followed', low:'Ignore Culture' } },
  { id:'implementation', label:'Implementation Update Feedback', sheet:'Implementation_update_feedback_Responses' }
];

function reviewSourceById_(id){
  id = String(id||'').trim().toLowerCase();
  return REVIEW_REPORT_SOURCES.find(s => s.id === id) || REVIEW_REPORT_SOURCES[0];
}

// header array me se pehla matching header (case-insensitive)
function findHeader_(headers, candidates){
  const low = (headers||[]).map(h => String(h).trim().toLowerCase());
  for (const c of candidates){
    const i = low.indexOf(String(c).trim().toLowerCase());
    if (i !== -1) return headers[i];
  }
  return '';
}

// scope: { month, hodId }
function getReviewReports(token, sourceId, scope){
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  scope = scope || {};
  const source = reviewSourceById_(sourceId);

  // companies owned by this OM (Staff) — for scoping; Learner = own company
  let ownCompanies = null;
  if (u.role === ROLES.STAFF && u.staffId){
    ownCompanies = {};
    readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o => {
      if (String(o[CFG.HDR.COMPANY_SMOPS]||'').trim() === u.staffId)
        ownCompanies[String(o[CFG.HDR.COMPANY_ID]||'').trim()] = true;
    });
  } else if (u.role === ROLES.LEARNER && u.companyId){
    ownCompanies = { [String(u.companyId).trim()]: true };
  }

  // employees index + company names
  const emps = readObjects_(CFG.SHEETS.EMPLOYEES).rows;
  const empById = {};
  emps.forEach(o => { const id=String(o['Employee_ID']||'').trim(); if (id) empById[id]=o; });
  const compName = {};
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o =>
    compName[String(o[CFG.HDR.COMPANY_ID]||'').trim()] = String(o[CFG.HDR.COMPANY_NAME]||'').trim());

  // HOD picker = distinct HOD_IDs (scoped to OM's companies if Staff)
  const seenHod = {}, hodList = []; const allowedHodSet = {};
  emps.forEach(o => {
    String(o['HOD_IDs']||'').split(/[,;|]/).map(s=>s.trim()).filter(Boolean).forEach(hid => {
      if (seenHod[hid]) return; seenHod[hid]=true;
      const e = empById[hid]; if (!e) return;
      const cid = String(e['Company_ID']||'').trim();
      if (ownCompanies && !ownCompanies[cid]) return;
      allowedHodSet[hid] = true;
      hodList.push({ id:hid, name:String(e['Employee_Name']||'').trim()||hid, companyId:cid, company:compName[cid]||cid });
    });
  });
  hodList.sort((a,b)=>a.name.localeCompare(b.name));

  // role-based HOD lock: Learner jo khud HOD hai → self only; MD/other → poori company (no lock)
  let forcedHod = '';
  if (u.role === ROLES.LEARNER){
    const me = emps.find(o => String(o['Employee_Email']||'').trim().toLowerCase() === String(u.email).trim().toLowerCase());
    const myId = me ? String(me['Employee_ID']||'').trim() : '';
    // sirf tab lock karo jab ye employee actually kisi ka HOD ho (HOD list me hai)
    if (myId && hodList.some(h => h.id === myId)) forcedHod = myId;
    // warna forcedHod='' → company-scope (ownCompanies) se saare HODs dikhenge
  }

  // read source sheet + auto-detect columns
  const obj = readObjects_(source.sheet);
  const H = obj.headers;
  const hMonth = findHeader_(H, ['Month']);
  const hCid   = findHeader_(H, ['Company_ID','CompanyID','CID']);
  const hHodId = findHeader_(H, ['HOD_ID','Hod_ID','HODID']) || findHeader_(H, ['EID']);
  const hHodNm = findHeader_(H, ['HOD_Name','Hod_Name']);
  const hQid   = findHeader_(H, ['Question_ID','QID','Q_ID']);
  const hQ     = findHeader_(H, ['Question','Question_Title','Criteria','Title']);
  const hEid   = findHeader_(H, ['Employee_ID','Emp_ID','MD_ID','HOD_ID']);
  const hEnm   = findHeader_(H, ['Employee_Name','Emp_Name','Name','MD_Name','HOD_Name']);
  const hRate  = findHeader_(H, ['Rating','Score','Value']);
  const hAns   = findHeader_(H, ['Answer','Response','Yes_No','YesNo']);
  const hRemark= findHeader_(H, ['Remark','Remarks','Comment','Note']);

  const isMatrix = !!(hRate && (hEid || hEnm) && hQ);
  const isYesNo  = !isMatrix && !!(hAns && hQ);   // Implementation-style: Question + Yes/No answer

  const wantMonth = scope.month ? succMonthNorm_(scope.month) : '';
  const wantHod     = forcedHod || String(scope.hodId||'').trim();
  const wantCompany = String(scope.companyId||'').trim();
  const allowCompany = ownCompanies; // null for Admin

  const groups = {};   // hodId||month -> group
  const monthSet = {};
  let totalRows = 0, ratingSum = 0, ratingN = 0;

  obj.rows.forEach(r => {
    const cid   = hCid   ? String(r[hCid]||'').trim()   : '';
    const hodId = hHodId ? String(r[hHodId]||'').trim() : '';
    const mCanon= hMonth ? succMonthNorm_(r[hMonth])    : '';

    // --- scope ---
    if (allowCompany){
      if (cid){ if (!allowCompany[cid]) return; }
      else if (hodId && !allowedHodSet[hodId]) return;   // no company col → scope by HOD
    }
    if (wantCompany && cid && cid !== wantCompany) return;
    if (forcedHod && hodId !== forcedHod) return;
    if (wantHod   && hodId !== wantHod)   return;
    if (wantMonth && mCanon && mCanon !== wantMonth) return;

    if (mCanon) monthSet[mCanon] = true;
    totalRows++;

    const gk = hodId + '||' + mCanon;
    const g = groups[gk] || (groups[gk] = {
      hodId: hodId,
      hodName: (hHodNm ? String(r[hHodNm]||'').trim() : '')
               || (empById[hodId] ? String(empById[hodId]['Employee_Name']||'').trim() : hodId),
      companyId: cid || (empById[hodId] ? String(empById[hodId]['Company_ID']||'').trim() : ''),
      company: compName[cid] || (empById[hodId] ? (compName[String(empById[hodId]['Company_ID']||'').trim()]||'') : '') || cid,
      month: mCanon, monthLabel: mCanon ? succMonthDisplay_(mCanon) : '',
      questions:{}, qOrder:[], emps:{}, empOrder:[], rawRows:[]
    });

    if (isMatrix){
      const qid   = hQid ? String(r[hQid]||'').trim() : (hQ ? String(r[hQ]||'').trim() : '');
      const qtext = hQ ? String(r[hQ]||'').trim() : qid;
      const eid   = hEid ? String(r[hEid]||'').trim() : (hEnm ? String(r[hEnm]||'').trim() : '');
      const enm   = hEnm ? String(r[hEnm]||'').trim() : eid;
      const rate  = Number(r[hRate]);
      if (qid && !g.questions[qid]){ g.questions[qid]=qtext; g.qOrder.push(qid); }
      if (eid && !g.emps[eid]){ g.emps[eid]={ name:enm, ratings:{} }; g.empOrder.push(eid); }
      if (eid && qid && !isNaN(rate)){ g.emps[eid].ratings[qid]=rate; ratingSum+=rate; ratingN++; }
    } else if (isYesNo){
      const qtext = String(r[hQ]||'').trim();
      const ans   = String(r[hAns]||'').trim();
      const rem   = hRemark ? String(r[hRemark]||'').trim() : '';
      const isYes = /^(yes|y|true|1)$/i.test(ans);
      g.yn = g.yn || { items:[], yes:0, total:0, mdName:'' };
      if (hEnm && !g.yn.mdName) g.yn.mdName = String(r[hEnm]||'').trim();
      g.yn.items.push({ question:qtext, answer:ans, yes:isYes, remark:rem });
      g.yn.total++; if (isYes) g.yn.yes++;
      ratingN += 0;   // avg rating not applicable
    } else {
      g.rawRows.push(r);
    }
  });

  // build output
  const hods = Object.keys(groups).map(gk => {
    const g = groups[gk];
    if (isMatrix){
      const questions = g.qOrder.map(qid => ({ id:qid, text:g.questions[qid] }));
      const employees = g.empOrder.map(eid => {
        const e = g.emps[eid];
        const vals = g.qOrder.map(qid => e.ratings[qid]).filter(v => v!=null && !isNaN(v));
        const avg = vals.length ? Math.round((vals.reduce((s,v)=>s+v,0)/vals.length)*10)/10 : '';
        return { id:eid, name:e.name, ratings:e.ratings, avg:avg };
      });
      let s=0,n=0; employees.forEach(e=>g.qOrder.forEach(qid=>{ const v=e.ratings[qid]; if(v!=null&&!isNaN(v)){s+=v;n++;} }));
      return { hodId:g.hodId, hodName:g.hodName, company:g.company, month:g.month, monthLabel:g.monthLabel,
        matrix:true, questions:questions, employees:employees,
        avg: n? Math.round((s/n)*10)/10 : '', responses:n };
    }
    if (isYesNo && g.yn){
      const pct = g.yn.total>0 ? Math.round((g.yn.yes/g.yn.total)*100) : 0;
      return { hodId:g.hodId, hodName:(g.yn.mdName||g.hodName), company:g.company, month:g.month, monthLabel:g.monthLabel,
        yesno:true, items:g.yn.items, yes:g.yn.yes, total:g.yn.total, scorePct:pct };
    }
    return { hodId:g.hodId, hodName:g.hodName, company:g.company, month:g.month, monthLabel:g.monthLabel,
      matrix:false, columns:H, rows:g.rawRows.map(rr => H.map(h => reviewCell_(rr[h]))) };
  }).sort((a,b)=> (b.month||'').localeCompare(a.month||'') || String(a.hodName).localeCompare(String(b.hodName)));

  // month dropdown (newest first by real date)
  const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  const monthOptions = Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }))
    .sort((a,b)=>{
      const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
      if(!ma||!mb) return 0;
      return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
    });

  // ---- MONTHLY TREND: employee × month Score% (ALL months, respects company/HOD scope, ignores month filter) ----
  const MAX_RATING = 5;
  const trendMonthSet = {};
  const empTrend = {};    // empKey -> { name, company, byMonth:{ m:{sum,cnt,yes,tot} } }
  obj.rows.forEach(r => {
    const cid   = hCid ? String(r[hCid]||'').trim() : '';
    const hodId = hHodId ? String(r[hHodId]||'').trim() : '';
    const mCanon= hMonth ? succMonthNorm_(r[hMonth]) : '';
    if (!mCanon) return;
    if (allowCompany){ if (cid){ if(!allowCompany[cid]) return; } else if (hodId && !allowedHodSet[hodId]) return; }
    if (wantCompany && cid && cid !== wantCompany) return;
    if (forcedHod && hodId !== forcedHod) return;
    if (wantHod   && hodId !== wantHod)   return;

    trendMonthSet[mCanon] = true;
    const company = compName[cid] || (empById[hodId] ? (compName[String(empById[hodId]['Company_ID']||'').trim()]||'') : '') || cid;

    if (isMatrix){
      const eid = hEid ? String(r[hEid]||'').trim() : (hEnm ? String(r[hEnm]||'').trim() : '');
      const enm = hEnm ? String(r[hEnm]||'').trim() : eid;
      const rate = Number(r[hRate]);
      if (!eid || isNaN(rate)) return;
      const e = empTrend[eid] || (empTrend[eid]={ name:enm, company:company, byMonth:{} });
      const mm = e.byMonth[mCanon] || (e.byMonth[mCanon]={ sum:0, cnt:0, yes:0, tot:0 });
      mm.sum += rate; mm.cnt++;
    } else if (isYesNo){
      const eid = hEid ? String(r[hEid]||'').trim() : (hEnm ? String(r[hEnm]||'').trim() : '');
      const enm = hEnm ? String(r[hEnm]||'').trim() : eid;
      if (!eid) return;
      const ans = String(r[hAns]||'').trim();
      const e = empTrend[eid] || (empTrend[eid]={ name:enm, company:company, byMonth:{} });
      const mm = e.byMonth[mCanon] || (e.byMonth[mCanon]={ sum:0, cnt:0, yes:0, tot:0 });
      mm.tot++; if (/^(yes|y|true|1)$/i.test(ans)) mm.yes++;
    }
  });

  const trendMonths = Object.keys(trendMonthSet).map(m=>({id:m,name:succMonthDisplay_(m)}))
    .sort((a,b)=>{
      const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
      if(!ma||!mb) return 0;
      return (Number(ma[2])*12+monIdx[ma[1]]) - (Number(mb[2])*12+monIdx[mb[1]]);   // oldest→newest
    });

  const trendEmployees = Object.keys(empTrend).map(k=>{
    const e = empTrend[k]; const scores = {};
    Object.keys(e.byMonth).forEach(m=>{
      const mm = e.byMonth[m];
      let pct = null;
      if (isYesNo) pct = mm.tot>0 ? Math.round((mm.yes/mm.tot)*100) : null;
      else pct = mm.cnt>0 ? Math.round((mm.sum/(mm.cnt*MAX_RATING))*100) : null;
      scores[m] = pct;
    });
    return { name:e.name, company:e.company, scores:scores };
  }).sort((a,b)=> String(a.company).localeCompare(String(b.company)) || String(a.name).localeCompare(String(b.name)));

  return {
    role: u.role,
    source: { id:source.id, label:source.label, sheet:source.sheet, status: source.status || null },
    sources: REVIEW_REPORT_SOURCES.map(s => ({ id:s.id, label:s.label })),
    canPickHod: (u.role === ROLES.ADMIN || u.role === ROLES.STAFF || (u.role === ROLES.LEARNER && !forcedHod)),
    companyOptions: (function(){
      const seen = {}, out = [];
      hodList.forEach(h => { if (h.companyId && !seen[h.companyId]){ seen[h.companyId]=true; out.push({ id:h.companyId, name:h.company||h.companyId }); } });
      return out.sort((a,b)=>a.name.localeCompare(b.name));
    })(),
    hodOptions: hodList,
    selectedHod: wantHod || '',
    monthOptions: monthOptions,
    selectedMonth: wantMonth || '',
    isMatrix: isMatrix,
    isYesNo: isYesNo,
    trend: { months: trendMonths, employees: trendEmployees },
    hods: hods,
    totals: { responses: totalRows, hodCount: hods.length, avgRating: ratingN ? Math.round((ratingSum/ratingN)*10)/10 : '' }
  };
}


// raw cell formatter: Date -> dd/MM/yyyy (with time if non-midnight), warna as-is string
function reviewCell_(v){
  if (v instanceof Date){
    const tz = ss_().getSpreadsheetTimeZone();
    const hasTime = v.getHours() || v.getMinutes() || v.getSeconds();
    return Utilities.formatDate(v, tz, hasTime ? 'dd/MM/yyyy HH:mm' : 'dd/MM/yyyy');
  }
  return String(v==null ? '' : v);
}


// One-time: purane duplicate Company_ID+Activity+Month rows hatao (latest Updated_At rakho).
function dedupeSuccessMeasures(){
  const sh = ss_().getSheetByName('Success_Measures');
  if (!sh || sh.getLastRow() < 3) return (Logger.log('Nothing to dedupe.'));
  const map = getHeaderMap_(sh);
  const cC=map['Company_ID'], cA=map['Activity'], cM=map['Month'], cU=map['Updated_At'];
  const vals = sh.getRange(2,1,sh.getLastRow()-1,sh.getLastColumn()).getValues();
  const best = {}; const dup = [];
  vals.forEach((r,i)=>{
    const cid=String(r[cC-1]||'').trim(), act=String(r[cA-1]||'').trim();
    if (!cid || !act) return;
    const key = cid+'||'+act.toLowerCase()+'||'+succMonthNorm_(r[cM-1]);
    const upd = cU ? String(r[cU-1]||'') : '';
    if (!best[key]){ best[key]={idx:i,upd:upd}; return; }
    if (upd >= best[key].upd){ dup.push(best[key].idx); best[key]={idx:i,upd:upd}; }
    else dup.push(i);
  });
  dup.map(i=>i+2).sort((a,b)=>b-a).forEach(rn=>sh.deleteRow(rn));
  return(Logger.log('Removed '+dup.length+' duplicate row(s).'));
}


function debugReview(){ Logger.log(JSON.stringify(reviewScoreMap_())); }

/*==================================================================================
   ACTIVITY LIFECYCLE MODULE
   - Predefined reminder rules (Day-2 / Day-1 / same-day 2h)
   - Escalation ladder (D+1 pending -> D+2 critical -> D+3 Lapsed)
   - Learner reschedule-request + staff approve/reject
   - Learner "mark done" -> staff confirm-complete (final complete = staff only)
==================================================================================*/

const REMINDER_RULE_HEADERS = ['Activity','Stage','Offset_Value','Offset_Unit','Offset_Dir','Channel','Active'];
function ensureReminderRulesSheet_(){
  const sh = ensureSheet_('Activity_Reminder_Rules', REMINDER_RULE_HEADERS);
  if (sh.getLastRow() < 2){
    // default rules apply to ALL activities (Activity = '*')
    sh.appendRow(['*','Initiate (Day-2)',      2,'DAYS','before','Email','Yes']);
    sh.appendRow(['*','Pre-Reminder (Day-1)',  1,'DAYS','before','Email','Yes']);
    sh.appendRow(['*','Same-day 2h before',    2,'HRS','before','Both','Yes']);
  }
  return sh;
}

const RESCHED_HEADERS = ['Request_ID','Schedule_ID','Company_ID','Company_Name','Activity','Title',
  'Old_Date','Old_Time','New_Date','New_Time','Reason','Requested_By','Requested_At',
  'Status','Decided_By','Decided_At','Note'];
function ensureReschedSheet_(){ return ensureSheet_('Reschedule_Requests', RESCHED_HEADERS); }

/* ---------- predefined reminders on save ---------- */
function autoRemindersFromRules_(payload, occMeta){
  const sh = ensureReminderRulesSheet_();
  const rules = readObjects_('Activity_Reminder_Rules').rows.filter(o=>{
    if (String(o['Active']||'').trim().toLowerCase() === 'no') return false;
    const a = String(o['Activity']||'').trim();
    return (!a || a === '*' || a.toLowerCase() === String(payload.activity||'').trim().toLowerCase());
  });
  if (!rules.length) return 0;
  const rem = rules.map(o=>({
    channel: String(o['Channel']||'Email'),
    type: 'offset',
    dir:  String(o['Offset_Dir']||'before').toLowerCase()==='after' ? 'after' : 'before',
    value: Number(o['Offset_Value'])||0,
    unit:  String(o['Offset_Unit']||'DAYS').toUpperCase()
  }));
  return writeReminders_(payload, occMeta, rem);
}

/* ---------- recipient resolution from Company_Employees ---------- */
function addEmails_(set, raw){
  String(raw||'').split(/[,;|]/).map(x=>x.trim()).filter(Boolean).forEach(e=>{ if (isEmail_(e)) set[e.toLowerCase()]=e; });
}
// returns { owners:[], hods:[], hrs:[], mds:[], smops:[] } (emails)
function escalationRecipients_(sched){
  const cid = String(sched['Company_ID']||'').trim();
  const doerNames = splitCsv_(sched['Company_Assigners']).map(s=>s.toLowerCase());
  const emps = readObjects_(CFG.SHEETS.EMPLOYEES).rows.filter(o=>String(o['Company_ID']||'').trim()===cid);
  const owners={}, hods={}, hrs={}, mds={};
  emps.forEach(o=>{
    const nm = String(o['Employee_Name']||'').trim().toLowerCase();
    if (doerNames.indexOf(nm)!==-1){
      addEmails_(owners, o['Employee_Email']);
      addEmails_(hods,   o['HOD_Email']);
      addEmails_(hrs,    o['HR_Email']);
      addEmails_(mds,    o['MD_Email']);
    }
  });
  // company-wide fallback if doer rows didn't yield HR / MD / HOD
  const need = (obj)=>Object.keys(obj).length===0;
  if (need(hrs)||need(mds)||need(hods)) emps.forEach(o=>{
    if (need(hrs)) addEmails_(hrs, o['HR_Email']);
    if (need(mds)) addEmails_(mds, o['MD_Email']);
    if (need(hods)) addEmails_(hods, o['HOD_Email']);
  });
  const smops={};
  splitCsv_(sched['Staff_Assigner']).forEach(n=>{ const e=staffEmailByName_(n); if (isEmail_(e)) smops[e.toLowerCase()]=e; });
  const vals = o => Object.keys(o).map(k=>o[k]);
  return { owners:vals(owners), hods:vals(hods), hrs:vals(hrs), mds:vals(mds), smops:vals(smops) };
}

function escBody_(sched, label, note){
  const m = buildMap_(sched);
  return '<div style="font-family:Arial,sans-serif;color:#1e293b">'
    + '<h3 style="color:#b91c1c">'+esc_(label)+': '+esc_(m.Title)+'</h3>'
    + '<p>'+esc_(note)+'</p>'
    + '<table style="border-collapse:collapse;font-size:14px">'
    + '<tr><td style="padding:3px 10px;color:#64748b">Activity</td><td style="padding:3px 10px"><b>'+esc_(m.Activity)+'</b></td></tr>'
    + '<tr><td style="padding:3px 10px;color:#64748b">Company</td><td style="padding:3px 10px">'+esc_(m.Company_Name)+'</td></tr>'
    + '<tr><td style="padding:3px 10px;color:#64748b">Scheduled Date</td><td style="padding:3px 10px">'+esc_(m.Event_Date)+(m.Event_Time?' '+esc_(m.Event_Time):'')+'</td></tr>'
    + '<tr><td style="padding:3px 10px;color:#64748b">Doer(s)</td><td style="padding:3px 10px">'+esc_(sched['Company_Assigners']||'')+'</td></tr>'
    + '</table></div>';
}

/* ---------- daily escalation ladder + lapse ---------- */
// Run daily (morning). Calendar days (Sat/Sun counted).
function runEscalationLadder(){
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');
  const nowStr   = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd HH:mm:ss');
  const daysBetween = (a,b) => Math.round((parseYMD_(b)-parseYMD_(a))/86400000);

  const sh = ensureScheduleSheet_();
  const map = getHeaderMap_(sh);
  if (sh.getLastRow() < 2) return 'no schedules';
  const vals = sh.getRange(2,1,sh.getLastRow()-1,sh.getLastColumn()).getValues();
  const H = Object.keys(map);
  const objOf = (rowArr)=>{ const o={}; H.forEach(h=>o[h]=rowArr[map[h]-1]); return o; };

  let pending=0, critical=0, lapsed=0;
  vals.forEach((rowArr, i)=>{
    const rowNum = i+2;
    const o = objOf(rowArr);
    const status = String(o['Status']||'Scheduled').trim();
    const statusLower = status.toLowerCase();
    // only open items; learner-done rows wait for staff, not escalated
    if (['completed','cancelled','lapsed','pending completion'].indexOf(statusLower)!==-1) return;
    if (String(o['Learner_Done']||'').trim().toLowerCase()==='yes') return;
    const date = toYMD_(o['Event_Date']); if (!date || date >= todayStr) return;   // only past-due
    const d = daysBetween(date, todayStr);      // 1 = next day, etc.
    let stage = Number(o['Esc_Stage']||0) || 0;
    const rec = escalationRecipients_(o);
    const uniq = arr => Array.from(new Set(arr.filter(Boolean)));

    const setCell = (h,v)=>{ if (map[h]) sh.getRange(rowNum, map[h]).setValue(v); };

    // D+1 -> pending escalation (owner, HOD, HR ; CC SMOps)
    if (d >= 1 && stage < 1){
      const to = uniq([].concat(rec.owners, rec.hods, rec.hrs));
      const cc = uniq(rec.smops);
      if (to.length){
        const subject='[Pending Action] '+(o['Title']||'')+' – '+(o['Activity']||'')+' not updated';
        const html = escBody_(o,'Pending Action Escalation','This activity was scheduled on '+date+' and has not been marked complete. Please update its status today.');
        try { MailApp.sendEmail({ to:to.join(','), cc:cc.join(','), subject:subject, htmlBody:html, name:CFG.MAIL.FROM_NAME, replyTo:CFG.MAIL.REPLY_TO }); } catch(e){ Logger.log('esc1 mail: '+e.message); }
      }
      // WhatsApp to owners (template-gated; silently skips if no template)
      splitCsv_(o['Company_Assigners']).forEach(n=>{ waNotify_('reminder','company', buildMap_(o), null, n); });
      setCell('Esc_Stage', 1); stage = 1; pending++;
    }
    // D+2 -> critical to MD (CC SMOps + owners)
    if (d >= 2 && stage < 2){
      const to = uniq(rec.mds.length ? rec.mds : [].concat(rec.hods, rec.hrs));
      const cc = uniq([].concat(rec.smops, rec.owners));
      if (to.length){
        const subject='[CRITICAL] '+(o['Title']||'')+' – '+(o['Activity']||'')+' overdue';
        const html = escBody_(o,'Critical Escalation','This activity (scheduled '+date+') is still not completed after 2 days. Immediate attention required before it lapses.');
        try { MailApp.sendEmail({ to:to.join(','), cc:cc.join(','), subject:subject, htmlBody:html, name:CFG.MAIL.FROM_NAME, replyTo:CFG.MAIL.REPLY_TO }); } catch(e){ Logger.log('esc2 mail: '+e.message); }
      }
      setCell('Esc_Stage', 2); stage = 2; critical++;
    }
    // D+3 -> Lapsed
    if (d >= 3 && stage < 3){
      setCell('Status', 'Lapsed');
      setCell('Esc_Stage', 3); stage = 3; lapsed++;
      try { updateTrackerStatus_(String(o['Schedule_ID']||''), 'Lapsed'); } catch(e){ Logger.log('lapse tracker: '+e.message); }
      const to = uniq([].concat(rec.owners, rec.hods, rec.hrs, rec.mds));
      const cc = uniq(rec.smops);
      if (to.length){
        const subject='[LAPSED] '+(o['Title']||'')+' – '+(o['Activity']||'');
        const html = escBody_(o,'Activity Lapsed','This activity (scheduled '+date+') was not completed within the allowed window and has been automatically marked LAPSED.');
        try { MailApp.sendEmail({ to:to.join(','), cc:cc.join(','), subject:subject, htmlBody:html, name:CFG.MAIL.FROM_NAME, replyTo:CFG.MAIL.REPLY_TO }); } catch(e){ Logger.log('lapse mail: '+e.message); }
      }
    }
  });
  const msg = 'Escalation ladder: '+pending+' pending, '+critical+' critical, '+lapsed+' lapsed ['+todayStr+']';
  Logger.log(msg);
  return msg;
}
function setupEscalationTrigger(){
  ScriptApp.getProjectTriggers().forEach(t=>{ if (t.getHandlerFunction()==='runEscalationLadder') ScriptApp.deleteTrigger(t); });
  ScriptApp.newTrigger('runEscalationLadder').timeBased().everyDays(1).atHour(7).create();
  return 'Escalation trigger installed (daily ~7am).';
}

/* ---------- LEARNER: request reschedule (>=12h before) ---------- */
function requestReschedule(token, scheduleId, newDate, newTime, reason){
  const u = requireRole_(token, [ROLES.LEARNER]);
  const sched = getScheduleById_(scheduleId);
  if (!sched) throw new Error('Activity not found.');
  if (String(sched['Company_ID']||'').trim() !== String(u.companyId||'').trim())
    throw new Error('You can only reschedule your own company activities.');
  const st = String(sched['Status']||'');
  if (['Completed','Cancelled','Lapsed'].indexOf(st)!==-1) throw new Error('This activity is '+st+' — cannot reschedule.');

  const tz = ss_().getSpreadsheetTimeZone();
  const oldDate = toYMD_(sched['Event_Date']); const oldTime = toHM_(sched['Event_Time']) || '00:00';
  const evtParts = String(oldTime).split(':').map(Number);
  const d = parseYMD_(oldDate);
  const evt = d ? new Date(d.getFullYear(),d.getMonth(),d.getDate(),evtParts[0]||0,evtParts[1]||0,0) : null;
  if (evt){
    const hrsLeft = (evt.getTime() - Date.now())/3600000;
    if (hrsLeft < 12) throw new Error('Reschedule requests must be raised at least 12 hours before the activity.');
  }
  if (!newDate) throw new Error('Please choose a new date.');

  const sh = ensureReschedSheet_(); const map = getHeaderMap_(sh);
  const now = new Date(); const rid = 'RR-'+now.getTime();
  const row = new Array(sh.getLastColumn()).fill(''); const put=(h,v)=>{ if (map[h]) row[map[h]-1]=v; };
  put('Request_ID',rid); put('Schedule_ID',scheduleId); put('Company_ID',sched['Company_ID']||'');
  put('Company_Name',sched['Company_Name']||''); put('Activity',sched['Activity']||''); put('Title',sched['Title']||'');
  put('Old_Date',oldDate); put('Old_Time',"'"+(oldTime||'')); put('New_Date',newDate); put('New_Time',newTime?("'"+newTime):'');
  put('Reason',reason||''); put('Requested_By',u.username||u.email||''); put('Requested_At',Utilities.formatDate(now,tz,'yyyy-MM-dd HH:mm:ss'));
  put('Status','Pending');
  sh.appendRow(row);

  // notify staff/admin
  const staffTo = {};
  splitCsv_(sched['Staff_Assigner']).forEach(n=>{ const e=staffEmailByName_(n); if (isEmail_(e)) staffTo[e]=1; });
  // also company's SMOps
  readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o=>{ if (String(o[CFG.HDR.COMPANY_ID]||'').trim()===String(sched['Company_ID']||'').trim()){
    const sm=staffById_(String(o[CFG.HDR.COMPANY_SMOPS]||'').trim()); if (sm&&isEmail_(sm.email)) staffTo[sm.email]=1; } });
  const to = Object.keys(staffTo);
  if (to.length){
    const subject='[Reschedule Request] '+(sched['Title']||'')+' – '+(sched['Activity']||'');
    const html='<div style="font-family:Arial,sans-serif;color:#1e293b"><h3 style="color:#7c3aed">Reschedule Request</h3>'
      + '<p><b>'+esc_(u.username||u.email)+'</b> requested to move this activity.</p>'
      + '<table style="border-collapse:collapse;font-size:14px">'
      + '<tr><td style="padding:3px 10px;color:#64748b">Activity</td><td style="padding:3px 10px"><b>'+esc_(sched['Activity']||'')+'</b></td></tr>'
      + '<tr><td style="padding:3px 10px;color:#64748b">Company</td><td style="padding:3px 10px">'+esc_(sched['Company_Name']||'')+'</td></tr>'
      + '<tr><td style="padding:3px 10px;color:#64748b">From</td><td style="padding:3px 10px">'+esc_(oldDate)+' '+esc_(oldTime)+'</td></tr>'
      + '<tr><td style="padding:3px 10px;color:#64748b">To</td><td style="padding:3px 10px">'+esc_(newDate)+' '+esc_(newTime||'')+'</td></tr>'
      + '<tr><td style="padding:3px 10px;color:#64748b">Reason</td><td style="padding:3px 10px">'+esc_(reason||'—')+'</td></tr>'
      + '</table><p style="color:#64748b">Approve/reject from the Reschedule Requests panel.</p></div>';
    try { sendMail_(to.join(','), subject, html); } catch(e){ Logger.log('resched mail: '+e.message); }
  }
  return { ok:true, requestId:rid };
}

/* ---------- LEARNER: mark done (staff confirms final complete) ---------- */
function markLearnerDone(token, scheduleId){
  const u = requireRole_(token, [ROLES.LEARNER]);
  const sh = ensureScheduleSheet_(); const map = getHeaderMap_(sh);
  const row = findScheduleRow_(sh, map, scheduleId); if (row===-1) throw new Error('Activity not found.');
  const rowVals = sh.getRange(row,1,1,sh.getLastColumn()).getValues()[0];
  const get=h=>map[h]?rowVals[map[h]-1]:'';
  if (String(get('Company_ID')||'').trim() !== String(u.companyId||'').trim()) throw new Error('Not your company activity.');
  const st = String(get('Status')||'');
  if (['Completed','Cancelled','Lapsed'].indexOf(st)!==-1) throw new Error('This activity is '+st+'.');
  const tz = ss_().getSpreadsheetTimeZone();
  const set=(h,v)=>{ if (map[h]) sh.getRange(row,map[h]).setValue(v); };
  set('Learner_Done','Yes'); set('Learner_Done_By',u.username||u.email||''); set('Learner_Done_At',Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss'));
  set('Esc_Stage', 0);
  // notify staff to confirm
  const sched = getScheduleById_(scheduleId) || {};
  const staffTo={}; splitCsv_(sched['Staff_Assigner']).forEach(n=>{ const e=staffEmailByName_(n); if (isEmail_(e)) staffTo[e]=1; });
  const to=Object.keys(staffTo);
  if (to.length){
    const subject='[Marked Done] '+(sched['Title']||'')+' – awaiting your confirmation';
    const html='<div style="font-family:Arial,sans-serif;color:#1e293b"><h3 style="color:#15803d">Activity marked done by doer</h3>'
      +'<p><b>'+esc_(u.username||u.email)+'</b> marked <b>'+esc_(sched['Activity']||'')+'</b> ('+esc_(sched['Company_Name']||'')+') as done. Please confirm to finalize completion.</p></div>';
    try { sendMail_(to.join(','), subject, html); } catch(e){ Logger.log('done mail: '+e.message); }
  }
  return { ok:true };
}

/* ---------- STAFF/ADMIN: confirm completion (final) ---------- */
function confirmCompletion(token, scheduleId){
  const actor = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF]);
  const sh = ensureScheduleSheet_(); const map = getHeaderMap_(sh);
  const row = findScheduleRow_(sh, map, scheduleId); if (row===-1) throw new Error('Activity not found.');
  const tz = ss_().getSpreadsheetTimeZone();
  const set=(h,v)=>{ if (map[h]) sh.getRange(row,map[h]).setValue(v); };
  const learnerDoneAtVal = map['Learner_Done_At'] ? sh.getRange(row, map['Learner_Done_At']).getValue() : '';
  set('Status','Completed');
  set('Esc_Stage', 0);
  const completedAtStr = Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss');
  set('Completed_At', completedAtStr);
  set('Completed_by', actor.username||actor.email||'');
  closeLinkedActionItems_(scheduleId, completedAtStr, learnerDoneAtVal);
  try { updateTrackerStatus_(scheduleId,'Completed'); } catch(e){ Logger.log('confirm tracker: '+e.message); }
  const sched = getScheduleById_(scheduleId) || {};
  const payload = { title:sched['Title'], activity:sched['Activity'], companyId:sched['Company_ID'],
    companyName:sched['Company_Name'], planStart:toYMD_(sched['Event_Date']), eventTime:toHM_(sched['Event_Time']),
    status:'Completed', departments:splitCsv_(sched['Departments']), staffAssigners:splitCsv_(sched['Staff_Assigner']),
    companyAssigners:splitCsv_(sched['Company_Assigners']), comment:sched['Comment']||'', _scheduleId:scheduleId };
  try { enqueueStatusMail_(payload,'completed'); } catch(e){ Logger.log('confirm mail: '+e.message); }
  return { ok:true };
}


function closeLinkedActionItems_(scheduleId, completedAtStr, learnerDoneAtStr) {
  if (!scheduleId) return;
  ensureActionSheet_();
  const sh = ss_().getSheetByName('Action_Items');
  const data = sh.getDataRange().getValues();
  const headers = data[0];
  const map = {}; headers.forEach((h,i)=>map[h]=i+1);
  const tz = ss_().getSpreadsheetTimeZone();
  const c2 = toYMD_(completedAtStr);
  const ldAt = learnerDoneAtStr ? toYMD_(learnerDoneAtStr) : '';

  for (let r=1; r<data.length; r++){
    const row = data[r];
    if (String(row[map['Schedule_ID']-1]||'').trim() !== scheduleId) continue;
    if (String(row[map['Status']-1]||'') === 'Closed') continue;
    const tgt = toYMD_(row[map['Target_Date']-1]);
    const totalDly = (c2 && tgt) ? Math.max(0, daysBetween(tgt, c2)) : 0;
    let learnerDly = totalDly, staffDly = 0;
    if (ldAt && tgt){
      learnerDly = Math.max(0, daysBetween(tgt, ldAt));
      if (c2) staffDly = Math.max(0, daysBetween(ldAt, c2));
    }
    const rowNum = r+1;
    if (map['Status']) sh.getRange(rowNum, map['Status']).setValue('Closed');
    if (map['Delay_Days']) sh.getRange(rowNum, map['Delay_Days']).setValue(totalDly);
    if (map['Learner_Delay_Days']) sh.getRange(rowNum, map['Learner_Delay_Days']).setValue(learnerDly);
    if (map['Staff_Delay_Days']) sh.getRange(rowNum, map['Staff_Delay_Days']).setValue(staffDly);
  }
}

/* ---------- STAFF/ADMIN: list + decide reschedule requests ---------- */
function getRescheduleRequests(token, statusFilter){
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF]);
  ensureReschedSheet_();
  let own = null;
  if (u.role===ROLES.STAFF && u.staffId){ own={}; readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o=>{
    if (String(o[CFG.HDR.COMPANY_SMOPS]||'').trim()===u.staffId) own[String(o[CFG.HDR.COMPANY_ID]||'').trim()]=true; }); }
  const want = String(statusFilter||'Pending');
  const out = [];
  readObjects_('Reschedule_Requests').rows.forEach(o=>{
    if (own && !own[String(o['Company_ID']||'').trim()]) return;
    if (want && want!=='All' && String(o['Status']||'')!==want) return;
    out.push({ id:String(o['Request_ID']||''), scheduleId:String(o['Schedule_ID']||''),
      company:String(o['Company_Name']||''), activity:String(o['Activity']||''), title:String(o['Title']||''),
      oldDate:toYMD_(o['Old_Date']), oldTime:toHM_(o['Old_Time']), newDate:toYMD_(o['New_Date']), newTime:toHM_(o['New_Time']),
      reason:String(o['Reason']||''), by:String(o['Requested_By']||''), at:String(o['Requested_At']||''),
      status:String(o['Status']||''), note:String(o['Note']||'') });
  });
  out.sort((a,b)=>(b.at||'').localeCompare(a.at||''));
  return { requests:out };
}

function decideRescheduleRequest(token, requestId, approve, note){
  const actor = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF]);
  const rsh = ensureReschedSheet_(); const rmap = getHeaderMap_(rsh);
  // find request row
  let rRow=-1; const last=rsh.getLastRow();
  if (last>1){ const ids=rsh.getRange(2,rmap['Request_ID'],last-1,1).getValues();
    for (let i=0;i<ids.length;i++) if (String(ids[i][0])===String(requestId)){ rRow=i+2; break; } }
  if (rRow===-1) throw new Error('Request not found.');
  const rget=h=>rmap[h]?rsh.getRange(rRow,rmap[h]).getValue():'';
  if (String(rget('Status'))!=='Pending') throw new Error('Already decided.');
  const scheduleId=String(rget('Schedule_ID')||'');
  const tz=ss_().getSpreadsheetTimeZone(); const nowStr=Utilities.formatDate(new Date(),tz,'yyyy-MM-dd HH:mm:ss');
  const rset=(h,v)=>{ if (rmap[h]) rsh.getRange(rRow,rmap[h]).setValue(v); };

  if (approve){
    // apply new date/time to schedule -> Rescheduled, reset esc stage
    const sh=ensureScheduleSheet_(); const map=getHeaderMap_(sh);
    const row=findScheduleRow_(sh,map,scheduleId); if (row===-1) throw new Error('Schedule not found.');
    const newDate=toYMD_(rget('New_Date')); const newTime=toHM_(rget('New_Time'));
    const set=(h,v)=>{ if (map[h]) sh.getRange(row,map[h]).setValue(v); };
    let cnt=Number(map['Reschedule_Count']?sh.getRange(row,map['Reschedule_Count']).getValue():0)||0;
    set('Event_Date',newDate); if (newTime) set('Event_Time',"'"+newTime);
    set('Status','Rescheduled'); set('Reschedule_Count',cnt+1); set('Esc_Stage',0);
    try { updateTrackerStatus_(scheduleId,'Rescheduled'); } catch(e){ Logger.log('rr tracker: '+e.message); }
    const sched=getScheduleById_(scheduleId)||{};
    const payload={ title:sched['Title'], activity:sched['Activity'], companyId:sched['Company_ID'], companyName:sched['Company_Name'],
      planStart:newDate, eventTime:newTime, status:'Rescheduled', departments:splitCsv_(sched['Departments']),
      staffAssigners:splitCsv_(sched['Staff_Assigner']), companyAssigners:splitCsv_(sched['Company_Assigners']), _scheduleId:scheduleId };
    try { enqueueStatusMail_(payload,'reschedule'); } catch(e){ Logger.log('rr mail: '+e.message); }
    rset('Status','Approved');
  } else {
    rset('Status','Rejected');
  }
  rset('Decided_By',actor.username||actor.email||''); rset('Decided_At',nowStr); rset('Note',note||'');

  // notify requester
  const sched=getScheduleById_(scheduleId)||{};
  const reqBy=String(rget('Requested_By')||'');
  let reqEmail=''; readObjects_(CFG.SHEETS.EMPLOYEES).rows.forEach(o=>{
    if (String(o['Employee_Name']||'').trim()===reqBy || String(o['Employee_Email']||'').trim()===reqBy) reqEmail=String(o['Employee_Email']||''); });
  if (isEmail_(reqEmail)){
    const decision = approve?'Approved':'Rejected';
    const subject='[Reschedule '+decision+'] '+(sched['Title']||sched['Activity']||'');
    const html='<div style="font-family:Arial,sans-serif;color:#1e293b"><h3 style="color:'+(approve?'#15803d':'#b91c1c')+'">Reschedule '+decision+'</h3>'
      +'<p>Your reschedule request for <b>'+esc_(sched['Activity']||'')+'</b> was <b>'+decision.toLowerCase()+'</b>.'
      +(note?' Note: '+esc_(note):'')+'</p></div>';
    try { sendMail_(reqEmail, subject, html); } catch(e){ Logger.log('rr notify: '+e.message); }
  }
  return { ok:true };
}


/*=================================================== EMPLOYEE ACTIVITY DASHBOARD (Company Employees — MD view) ===================================================*/
function getEmployeeActivityDashboard(token, scope) {
  const u = requireRole_(token, [ROLES.ADMIN, ROLES.STAFF, ROLES.LEARNER]);
  scope = scope || {};
  const tz = ss_().getSpreadsheetTimeZone();
  const todayStr = Utilities.formatDate(new Date(), tz, 'yyyy-MM-dd');

  // company scope
  let companyId = '';
  if (u.role === ROLES.LEARNER) companyId = String(u.companyId||'').trim();
  else companyId = String(scope.companyId||'').trim();

  // month filter (blank = all months)
  const filterMonth = scope.month ? succMonthNorm_(scope.month) : '';
  const filterEmp = String(scope.employeeId||'').trim();
  const filterDesig = String(scope.designation||'').trim().toLowerCase();
  const filterSide = String(scope.side||'').trim();   // 'OM' | 'Client' | ''
  const creatorMap = filterSide ? getCreatorRoleMap_() : null;

  // Schedule_ID -> Created_By side, for filtering Activity_Tracker rows by who scheduled them
  const schedSideMap = {};
  if (filterSide) {
    readObjects_(CFG.SHEETS.SCHEDULE).rows.forEach(o => {
      const sid = String(o['Schedule_ID']||'').trim();
      if (sid) schedSideMap[sid] = scheduledBySide_(o['Created_By'], creatorMap);
    });
  }

  // company name (for header)
  let companyName = '';
  if (companyId) readObjects_(CFG.SHEETS.COMPANIES).rows.forEach(o=>{
    if (String(o[CFG.HDR.COMPANY_ID]||'').trim() === companyId) companyName = String(o[CFG.HDR.COMPANY_NAME]||'').trim();
  });

  // Employee roster for this company (id -> {name, designation, dept, email})
  const emps = readObjects_(CFG.SHEETS.EMPLOYEES).rows.filter(o =>
    !companyId || String(o[CFG.HDR.EMP_COMPANY_ID]||'').trim() === companyId);
  const empMeta = {}; // id -> meta
  const designSet = {};
  emps.forEach(o => {
    const id = String(o['Employee_ID']||'').trim(); if (!id) return;
    const desig = String(o['Designation']||'').trim();
    if (desig) designSet[desig] = true;
    empMeta[id] = {
      id: id,
      name: String(o[CFG.HDR.EMP_NAME]||'').trim() || id,
      designation: desig,
      department: String(o[CFG.HDR.EMP_DEPT]||'').trim(),
      email: String(o[CFG.HDR.EMP_EMAIL]||'').trim(),
      role: String(o[CFG.HDR.EMP_ROLE]||'').trim()
    };
  });

  // Aggregate Activity_Tracker per employee
  const agg = {};   // empId -> { total, completed, missed, pending, byActivity:{} }
  const monthSet = {};
  ensureTrackerSheet_();
  readObjects_('Activity_Tracker').rows.forEach(r => {
    const empId = String(r['Employee_ID']||'').trim();
    if (!empId || !empMeta[empId]) return;   // only employees of this company
    const st = String(r['Status']||'').trim().toLowerCase();
    if (st === 'cancelled') return;
    const date = toYMD_(r['Date']);
    const month = trackerMonthKey_(r['Month']) || trackerMonthKey_(date);
    if (month) monthSet[month] = true;
    if (filterMonth && month !== filterMonth) return;
    if (filterSide){
      const sid = String(r['Schedule_ID']||'').trim();
      if (!sid || schedSideMap[sid] !== filterSide) return;
    }

    const a = agg[empId] || (agg[empId] = { total:0, completed:0, missed:0, pending:0, byActivity:{} });
    a.total++;
    let cell;
    if (st === 'completed') { a.completed++; cell='done'; }
    else if (st === 'missed' || date < todayStr) { a.missed++; cell='missed'; }
    else { a.pending++; cell='pending'; }

    const act = String(r['Activity']||'').trim();
    if (act){
      const ac = a.byActivity[act] || (a.byActivity[act] = { total:0, completed:0 });
      ac.total++; if (cell==='done') ac.completed++;
    }
  });

  // Build employee rows (respecting employee/designation filters)
  const rows = Object.keys(empMeta).filter(id => {
    if (filterEmp && id !== filterEmp) return false;
    if (filterDesig && empMeta[id].designation.toLowerCase() !== filterDesig) return false;
    return true;
  }).map(id => {
    const meta = empMeta[id];
    const a = agg[id] || { total:0, completed:0, missed:0, pending:0, byActivity:{} };
    const score = a.total > 0 ? Math.round((a.completed / a.total) * 100) : 0;
    const activities = Object.keys(a.byActivity).map(act => {
      const ac = a.byActivity[act];
      return { activity: act, completed: ac.completed, total: ac.total,
        pct: ac.total>0 ? Math.round((ac.completed/ac.total)*100) : 0 };
    }).sort((x,y)=>x.activity.localeCompare(y.activity));
    return {
      id: id, name: meta.name, designation: meta.designation||'—',
      department: meta.department||'—', email: meta.email,
      total: a.total, completed: a.completed, missed: a.missed, pending: a.pending,
      score: score, activities: activities
    };
  }).sort((x,y)=> y.score - x.score || x.name.localeCompare(y.name));

  // overall KPIs (across filtered rows)
  const totalEmployees = rows.length;
  const totalActivities = rows.reduce((s,r)=>s+r.total,0);
  const totalCompleted = rows.reduce((s,r)=>s+r.completed,0);
  const totalMissed = rows.reduce((s,r)=>s+r.missed,0);
  const totalPending = rows.reduce((s,r)=>s+r.pending,0);
  const avgScore = totalEmployees>0 ? Math.round(rows.reduce((s,r)=>s+r.score,0)/totalEmployees) : 0;

  // month options + designation options
  const monIdx = {jan:0,feb:1,mar:2,apr:3,may:4,jun:5,jul:6,aug:7,sep:8,oct:9,nov:10,dec:11};
  const monthOptions = Object.keys(monthSet).map(m => ({ id:m, name:succMonthDisplay_(m) }))
    .sort((a,b)=>{
      const ma=a.id.match(/^([a-z]{3})(\d{2})$/), mb=b.id.match(/^([a-z]{3})(\d{2})$/);
      if(!ma||!mb) return 0;
      return (Number(mb[2])*12+monIdx[mb[1]]) - (Number(ma[2])*12+monIdx[ma[1]]);
    });

  const companyOptions = (u.role === ROLES.LEARNER) ? [] :
    readObjects_(CFG.SHEETS.COMPANIES).rows.map(o=>({
      id:String(o[CFG.HDR.COMPANY_ID]||'').trim(), name:String(o[CFG.HDR.COMPANY_NAME]||'').trim()
    })).filter(c=>c.name).sort((a,b)=>a.name.localeCompare(b.name));

  return {
    company: companyName,
    companyId: companyId,
    canPickCompany: (u.role !== ROLES.LEARNER),
    companyOptions: companyOptions,
    employeeOptions: Object.keys(empMeta).map(id=>({id:id,name:empMeta[id].name})).sort((a,b)=>a.name.localeCompare(b.name)),
    designationOptions: Object.keys(designSet).sort(),
    monthOptions: monthOptions,
    selectedMonth: filterMonth,
    selectedSide: filterSide,
    cards: {
      totalEmployees: totalEmployees, totalActivities: totalActivities,
      completed: totalCompleted, missed: totalMissed, pending: totalPending,
      avgScore: avgScore
    },
    rows: rows
  };
}


function getCreatorRoleMap_() {
  // returns { emailLower: 'Staff' | 'Learner' }
  const map = {};
  getStaffList_().forEach(s => { if (s.email) map[String(s.email).trim().toLowerCase()] = 'Staff'; });
  readObjects_(CFG.SHEETS.EMPLOYEES).rows.forEach(o => {
    const em = String(o[CFG.HDR.EMP_EMAIL]||'').trim().toLowerCase();
    if (em && !map[em]) map[em] = 'Learner';
  });
  return map;
}
function scheduledBySide_(createdBy, creatorMap) {
  const em = String(createdBy||'').trim().toLowerCase();
  const role = creatorMap[em];
  if (role === 'Staff') return 'OM';
  if (role === 'Learner') return 'Client';
  return 'Unknown';
}