import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  UserCheck, PartyPopper, XCircle, Loader2, Upload, X, Plus, Trash2,
} from 'lucide-react';
import {
  getPublicOnboarding, submitOnboarding, readFileAsUpload,
} from '../../../services/hrmsPublicApi';

/**
 * HRMS ▸ PUBLIC pre-onboarding form.
 *
 * Mounted OUTSIDE PrivateRoute. A new hire is not yet a user of this ERP and must never see
 * its navigation.
 *
 * The one rule worth stating: **PAN or Aadhaar is required, and the server enforces it.**
 * The check below is a courtesy that saves a round trip — it is not the guard. The source
 * HRMS checked this in the browser only (BACKEND_ANALYSIS §8), so any request that skipped
 * the form put an employee into payroll with no identity document at all.
 *
 * Submitting is once-only: HR verifies these details by hand, and letting them change
 * afterwards would silently invalidate that verification. Revisiting shows a calm done
 * screen rather than an error — someone re-checking their own link has done nothing wrong.
 */

const MAX_MB = 15;

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 py-8 px-4">
    <div className="max-w-2xl mx-auto">{children}</div>
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const FIELD = 'w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-[13.5px] text-slate-900 focus:outline-none focus:ring-2 focus:ring-indigo-500/30 focus:border-indigo-500';
const LABEL = 'block text-[12px] font-semibold text-slate-700 mb-1.5';

const Field = ({ id, label, hint, children }) => (
  <div>
    <label className={LABEL} htmlFor={id}>{label}</label>
    {children}
    {hint && <p className="text-[11.5px] text-slate-500 mt-1">{hint}</p>}
  </div>
);

const OnboardPage = () => {
  const { code } = useParams();

  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [done, setDone] = useState(false);

  const [form, setForm] = useState({
    pan: '', aadhaar: '', passport: '', driving_license: '',
    date_of_birth: '', gender: '', address: '',
    bank_name: '', bank_account: '', bank_ifsc: '',
    emergency_contact_name: '', emergency_contact_phone: '', emergency_contact_relation: '',
    asset_requirements: '',
  });
  const [references, setReferences] = useState([]);
  const [files, setFiles] = useState([]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  useEffect(() => {
    document.title = 'Joining details';
    getPublicOnboarding(code)
      .then(({ data: d }) => {
        setData(d);
        if (d?.already_submitted) setDone(true);
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const pickFiles = (e) => {
    const chosen = Array.from(e.target.files || []);
    const max = data?.max_documents || 15;
    if (files.length + chosen.length > max) {
      setError(`You can attach at most ${max} documents.`);
      e.target.value = '';
      return;
    }
    const tooBig = chosen.find((f) => f.size > MAX_MB * 1024 * 1024);
    if (tooBig) {
      setError(`"${tooBig.name}" is too large. The limit is ${MAX_MB} MB per file.`);
      e.target.value = '';
      return;
    }
    setError('');
    setFiles((c) => [...c, ...chosen]);
  };

  const addReference = () => {
    const max = data?.max_references || 5;
    if (references.length >= max) {
      setError(`You can add at most ${max} references.`);
      return;
    }
    setReferences((r) => [...r, { name: '', relation: '', phone: '' }]);
  };

  const setReference = (i, key) => (e) => setReferences((rows) =>
    rows.map((r, idx) => (idx === i ? { ...r, [key]: e.target.value } : r)));

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    // Courtesy check only — the server enforces this regardless of what the browser did.
    if (!form.pan.trim() && !form.aadhaar.trim()) {
      setError('Provide your PAN or your Aadhaar number — at least one is required.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = {
        ...form,
        gender: form.gender || null,
        references: references.filter((r) => r.name.trim()),
        documents: files.length ? await Promise.all(files.map(readFileAsUpload)) : [],
      };
      await submitOnboarding(code, payload);
      setDone(true);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err?.response?.data?.detail || 'Your details could not be submitted.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <Card className="py-16 flex flex-col items-center gap-3">
          <Loader2 size={22} className="animate-spin text-indigo-600" />
          <p className="text-[13px] text-slate-500">Loading your form…</p>
        </Card>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="py-16 px-6 flex flex-col items-center gap-3 text-center">
          <XCircle size={26} className="text-slate-400" />
          <p className="text-[15px] font-bold text-slate-900">Link unavailable</p>
          <p className="text-[13px] text-slate-500 max-w-sm">{loadError}</p>
        </Card>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <Card className="py-16 px-6 flex flex-col items-center gap-3 text-center">
          <PartyPopper size={28} className="text-indigo-600" />
          <p className="text-[16px] font-bold text-slate-900">Thank you</p>
          <p className="text-[13.5px] text-slate-600 max-w-md">
            Your details have been received. The HR team will verify them and be in touch
            before your joining date.
          </p>
          {data?.joining_date && (
            <p className="text-[12.5px] text-slate-500">
              Joining on {new Date(data.joining_date).toLocaleDateString('en-IN', {
                day: '2-digit', month: 'long', year: 'numeric',
              })}
            </p>
          )}
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card className="overflow-hidden">
        <div className="px-6 py-5 border-b border-slate-200 flex items-start gap-3">
          <div className="h-10 w-10 rounded-xl bg-indigo-50 text-indigo-600 grid place-items-center shrink-0">
            <UserCheck size={19} />
          </div>
          <div>
            <h1 className="text-[17px] font-bold text-slate-900">
              Welcome{data?.candidate_name ? `, ${data.candidate_name}` : ''}
            </h1>
            <p className="text-[12.5px] text-slate-500 mt-0.5">
              {data?.designation ? `${data.designation} · ` : ''}
              Please complete your joining details.
            </p>
          </div>
        </div>

        <form onSubmit={submit} className="p-6 space-y-6">
          <section className="space-y-3">
            <h2 className="text-[13px] font-bold text-slate-900">Identity</h2>
            <p className="text-[12px] text-slate-500 -mt-1">
              Provide your PAN or your Aadhaar number — at least one is required.
            </p>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <Field id="pan" label="PAN" hint="e.g. ABCDE1234F">
                <input id="pan" className={FIELD} value={form.pan} onChange={set('pan')}
                  autoComplete="off" />
              </Field>
              <Field id="aadhaar" label="Aadhaar" hint="12 digits">
                <input id="aadhaar" className={FIELD} value={form.aadhaar}
                  onChange={set('aadhaar')} inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="passport" label="Passport number (optional)">
                <input id="passport" className={FIELD} value={form.passport}
                  onChange={set('passport')} />
              </Field>
              <Field id="dl" label="Driving licence (optional)">
                <input id="dl" className={FIELD} value={form.driving_license}
                  onChange={set('driving_license')} />
              </Field>
              <Field id="dob" label="Date of birth">
                <input id="dob" type="date" className={FIELD} value={form.date_of_birth}
                  onChange={set('date_of_birth')} />
              </Field>
              <Field id="gender" label="Gender">
                <select id="gender" className={FIELD} value={form.gender}
                  onChange={set('gender')}>
                  <option value="">Prefer not to say</option>
                  <option value="Male">Male</option>
                  <option value="Female">Female</option>
                  <option value="Other">Other</option>
                </select>
              </Field>
            </div>
            <Field id="address" label="Current address">
              <textarea id="address" rows={3} value={form.address} onChange={set('address')}
                className={`${FIELD} h-auto py-2 resize-y`} />
            </Field>
          </section>

          <section className="space-y-3">
            <h2 className="text-[13px] font-bold text-slate-900">Bank details for salary</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Field id="bank" label="Bank name">
                <input id="bank" className={FIELD} value={form.bank_name}
                  onChange={set('bank_name')} />
              </Field>
              <Field id="acct" label="Account number">
                <input id="acct" className={FIELD} value={form.bank_account}
                  onChange={set('bank_account')} inputMode="numeric" autoComplete="off" />
              </Field>
              <Field id="ifsc" label="IFSC" hint="e.g. HDFC0001234">
                <input id="ifsc" className={FIELD} value={form.bank_ifsc}
                  onChange={set('bank_ifsc')} autoComplete="off" />
              </Field>
            </div>
          </section>

          <section className="space-y-3">
            <h2 className="text-[13px] font-bold text-slate-900">Emergency contact</h2>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
              <Field id="ec-name" label="Name">
                <input id="ec-name" className={FIELD} value={form.emergency_contact_name}
                  onChange={set('emergency_contact_name')} />
              </Field>
              <Field id="ec-phone" label="Phone">
                <input id="ec-phone" className={FIELD} value={form.emergency_contact_phone}
                  onChange={set('emergency_contact_phone')} inputMode="tel" />
              </Field>
              <Field id="ec-rel" label="Relationship">
                <input id="ec-rel" className={FIELD} value={form.emergency_contact_relation}
                  onChange={set('emergency_contact_relation')} />
              </Field>
            </div>
          </section>

          <section className="space-y-3">
            <div className="flex items-center justify-between">
              <h2 className="text-[13px] font-bold text-slate-900">References (optional)</h2>
              <button type="button" onClick={addReference}
                className="h-8 px-3 rounded-lg border border-slate-300 text-[12px] font-semibold text-slate-600 hover:bg-slate-50 flex items-center gap-1.5">
                <Plus size={13} /> Add
              </button>
            </div>
            {references.map((r, i) => (
              // Index key: rows are only appended and removed by position, and there
              // is no stable id until the server has them.
              <div key={i} className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_1fr_auto] gap-2">
                <input className={FIELD} placeholder="Name" value={r.name}
                  onChange={setReference(i, 'name')} aria-label={`Reference ${i + 1} name`} />
                <input className={FIELD} placeholder="Relationship" value={r.relation}
                  onChange={setReference(i, 'relation')}
                  aria-label={`Reference ${i + 1} relationship`} />
                <input className={FIELD} placeholder="Phone" value={r.phone}
                  onChange={setReference(i, 'phone')}
                  aria-label={`Reference ${i + 1} phone`} />
                <button type="button"
                  onClick={() => setReferences((rows) => rows.filter((_, idx) => idx !== i))}
                  className="h-10 w-10 grid place-items-center rounded-lg border border-slate-300 text-slate-400 hover:text-rose-600"
                  aria-label={`Remove reference ${i + 1}`}>
                  <Trash2 size={15} />
                </button>
              </div>
            ))}
          </section>

          <section className="space-y-3">
            <h2 className="text-[13px] font-bold text-slate-900">Documents</h2>
            <p className="text-[12px] text-slate-500 -mt-1">
              PAN card, Aadhaar, education certificates, previous payslips or relieving
              letter. PDF, Word or images, up to {MAX_MB} MB each.
            </p>
            <label className="flex items-center justify-center gap-2 h-20 rounded-lg border-2 border-dashed border-slate-300 text-[13px] text-slate-500 cursor-pointer hover:border-indigo-400 hover:text-indigo-600">
              <Upload size={16} /> Choose files
              <input type="file" multiple className="hidden" onChange={pickFiles}
                accept=".pdf,.doc,.docx,.png,.jpg,.jpeg" />
            </label>
            {files.length > 0 && (
              <ul className="space-y-1.5">
                {files.map((f, i) => (
                  <li key={`${f.name}-${f.size}-${i}`}
                    className="flex items-center gap-2 text-[12.5px] text-slate-700">
                    <span className="truncate flex-1">{f.name}</span>
                    <button type="button"
                      onClick={() => setFiles((c) => c.filter((_, idx) => idx !== i))}
                      className="p-1 rounded text-slate-400 hover:text-rose-600"
                      aria-label={`Remove ${f.name}`}>
                      <X size={14} />
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <Field id="assets" label="Anything you need on day one? (optional)"
            hint="e.g. a laptop with more memory, a left-handed mouse, dietary needs for induction">
            <textarea id="assets" rows={2} value={form.asset_requirements}
              onChange={set('asset_requirements')}
              className={`${FIELD} h-auto py-2 resize-y`} />
          </Field>

          {error && (
            <p className="text-[12.5px] font-semibold text-rose-600 bg-rose-50 border border-rose-200 rounded-lg px-3 py-2">
              {error}
            </p>
          )}

          <button type="submit" disabled={submitting}
            className="w-full h-11 rounded-lg bg-indigo-600 text-white text-[14px] font-bold hover:bg-indigo-700 disabled:opacity-60 transition-colors">
            {submitting ? 'Submitting…' : 'Submit my details'}
          </button>
          <p className="text-[11.5px] text-slate-500 text-center">
            You can submit this form once. Contact the HR team if something needs to change
            afterwards.
          </p>
        </form>
      </Card>
    </Shell>
  );
};

export default OnboardPage;
