import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Briefcase, MapPin, Clock, GraduationCap, PartyPopper, XCircle, Loader2, Upload, X,
} from 'lucide-react';
import { getPublicJob, submitApplication, readFileAsUpload } from '../../../services/hrmsPublicApi';

/**
 * HRMS ▸ PUBLIC job application page.
 *
 * The only page in this app that renders with no session. Mounted OUTSIDE PrivateRoute in
 * App.jsx, and it must stay that way — wrapping it would redirect every candidate to /login.
 *
 * It deliberately renders its own standalone chrome rather than the app shell: an applicant
 * is not a user of this ERP and should never see its navigation, branding or modules.
 *
 * Errors come from the server verbatim and are intentionally vague ("This application link
 * is not valid") — the page must not become a way to discover which codes exist.
 */

const MAX_MB = 15;
const MAX_CERTS = 10;

const FIELD = 'w-full h-10 px-3 rounded-lg border border-slate-300 bg-white text-[14px] text-slate-900 focus:border-slate-500 focus:outline-none';
const LABEL = 'block text-[12px] font-semibold text-slate-700 mb-1.5';

const Shell = ({ children }) => (
  <div className="min-h-screen bg-slate-50 py-8 px-4">
    <div className="max-w-3xl mx-auto">{children}</div>
  </div>
);

const Card = ({ children, className = '' }) => (
  <div className={`bg-white rounded-2xl border border-slate-200 shadow-sm ${className}`}>
    {children}
  </div>
);

const Fact = ({ icon: Icon, label, value }) => (
  value ? (
    <div className="flex items-center gap-2 text-[13px] text-slate-600">
      <Icon size={14} className="shrink-0 text-slate-400" />
      <span><span className="text-slate-400">{label}:</span> {value}</span>
    </div>
  ) : null
);

const ApplyPage = () => {
  const { code } = useParams();

  const [job, setJob] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [done, setDone] = useState(null);

  const [form, setForm] = useState({
    candidate_name: '', can_email: '', can_contact: '',
    current_location: '', total_experience: '', qualification: '',
    current_company: '', current_ctc: '', expected_ctc: '', notice_period: '',
    linkedin: '', portfolio: '', cover_note: '', declaration: false,
  });
  const [resume, setResume] = useState(null);
  const [certificates, setCertificates] = useState([]);

  const set = (k) => (e) =>
    setForm((f) => ({ ...f, [k]: e.target.type === 'checkbox' ? e.target.checked : e.target.value }));

  useEffect(() => {
    document.title = 'Apply';
    getPublicJob(code)
      .then(({ data }) => {
        // An `external` posting is a signpost, not a form — send the applicant onward.
        if (data?.external && data.external_url) {
          window.location.replace(data.external_url);
          return;
        }
        setJob(data);
        if (data?.title) document.title = `Apply — ${data.title}`;
      })
      .catch((err) => setLoadError(
        err?.response?.data?.detail || 'This application link is not valid.'))
      .finally(() => setLoading(false));
  }, [code]);

  const pickResume = (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    if (file.size > MAX_MB * 1024 * 1024) {
      setError(`Your resume is too large. The limit is ${MAX_MB} MB.`);
      e.target.value = '';
      return;
    }
    setError('');
    setResume(file);
  };

  const pickCertificates = (e) => {
    const files = Array.from(e.target.files || []);
    if (certificates.length + files.length > MAX_CERTS) {
      setError(`You can attach at most ${MAX_CERTS} certificates.`);
      e.target.value = '';
      return;
    }
    const tooBig = files.find((f) => f.size > MAX_MB * 1024 * 1024);
    if (tooBig) {
      setError(`"${tooBig.name}" is too large. The limit is ${MAX_MB} MB per file.`);
      e.target.value = '';
      return;
    }
    setError('');
    setCertificates((c) => [...c, ...files]);
  };

  const submit = async (e) => {
    e.preventDefault();
    setError('');
    if (!form.declaration) {
      setError('Please confirm that the information provided is accurate.');
      return;
    }
    setSubmitting(true);
    try {
      const payload = { ...form };
      if (resume) payload.resume = await readFileAsUpload(resume);
      if (certificates.length) {
        payload.certificates = await Promise.all(certificates.map(readFileAsUpload));
      }
      const { data } = await submitApplication(code, payload);
      setDone(data);
      window.scrollTo({ top: 0, behavior: 'smooth' });
    } catch (err) {
      setError(err?.response?.data?.detail
        || 'Your application could not be submitted. Please try again.');
    } finally {
      setSubmitting(false);
    }
  };

  if (loading) {
    return (
      <Shell>
        <div className="py-24 flex flex-col items-center gap-3 text-slate-500">
          <Loader2 size={24} className="animate-spin" />
          <p className="text-[14px]">Loading this role…</p>
        </div>
      </Shell>
    );
  }

  if (loadError) {
    return (
      <Shell>
        <Card className="p-8 text-center">
          <XCircle size={34} className="mx-auto text-slate-400" />
          <h1 className="mt-4 text-[18px] font-bold text-slate-900">Link unavailable</h1>
          <p className="mt-2 text-[14px] text-slate-600">{loadError}</p>
          <p className="mt-4 text-[12.5px] text-slate-400">
            If someone shared this with you, ask them for an up-to-date link.
          </p>
        </Card>
      </Shell>
    );
  }

  if (done) {
    return (
      <Shell>
        <Card className="p-8 text-center">
          <PartyPopper size={34} className="mx-auto text-emerald-500" />
          <h1 className="mt-4 text-[20px] font-bold text-slate-900">
            {done.duplicate ? 'You have already applied' : 'Application submitted!'}
          </h1>
          <p className="mt-2 text-[14px] text-slate-600">{done.message}</p>
          {done.reference && (
            <p className="mt-5 inline-block px-3 py-1.5 rounded-lg bg-slate-100 font-mono text-[13px] text-slate-700">
              Reference: {done.reference}
            </p>
          )}
          <p className="mt-5 text-[12.5px] text-slate-400">
            Keep this reference. The hiring team will be in touch by email.
          </p>
        </Card>
      </Shell>
    );
  }

  return (
    <Shell>
      <Card className="p-6 mb-4">
        <div className="flex items-start gap-3">
          <div className="h-11 w-11 rounded-xl bg-slate-900 text-white grid place-items-center shrink-0">
            <Briefcase size={19} />
          </div>
          <div className="min-w-0">
            <h1 className="text-[20px] font-bold text-slate-900">{job.title}</h1>
            <p className="text-[13px] text-slate-500">
              {[job.department, job.employment_type].filter(Boolean).join(' · ')}
            </p>
          </div>
        </div>
        <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-2">
          <Fact icon={MapPin} label="Location" value={job.location} />
          <Fact icon={Clock} label="Experience" value={job.experience} />
          <Fact icon={GraduationCap} label="Qualification" value={job.qualifications} />
          <Fact icon={Briefcase} label="Openings" value={job.vacancies} />
        </div>
        {job.responsibilities && (
          <div className="mt-5 pt-4 border-t border-slate-100">
            <h2 className="text-[13px] font-bold text-slate-900">About the role</h2>
            <p className="mt-1.5 text-[13.5px] text-slate-600 whitespace-pre-wrap">{job.responsibilities}</p>
          </div>
        )}
        {job.skills && (
          <div className="mt-4">
            <h2 className="text-[13px] font-bold text-slate-900">Skills</h2>
            <p className="mt-1.5 text-[13.5px] text-slate-600 whitespace-pre-wrap">{job.skills}</p>
          </div>
        )}
        {job.benefits && (
          <div className="mt-4">
            <h2 className="text-[13px] font-bold text-slate-900">Benefits</h2>
            <p className="mt-1.5 text-[13.5px] text-slate-600 whitespace-pre-wrap">{job.benefits}</p>
          </div>
        )}
      </Card>

      <Card className="p-6">
        <h2 className="text-[16px] font-bold text-slate-900">Apply for this role</h2>
        <p className="text-[12.5px] text-slate-500">Fields marked * are required.</p>

        <form onSubmit={submit} className="mt-5 space-y-5">
          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-slate-400 mb-3">
              Your details
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div className="sm:col-span-2">
                <label className={LABEL} htmlFor="a-name">Full name *</label>
                <input id="a-name" required value={form.candidate_name}
                  onChange={set('candidate_name')} className={FIELD} autoComplete="name" />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-email">Email *</label>
                <input id="a-email" type="email" required value={form.can_email}
                  onChange={set('can_email')} className={FIELD} autoComplete="email" />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-phone">Phone *</label>
                <input id="a-phone" required value={form.can_contact}
                  onChange={set('can_contact')} className={FIELD} autoComplete="tel" />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-loc">Current location</label>
                <input id="a-loc" value={form.current_location} onChange={set('current_location')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-notice">Notice period</label>
                <input id="a-notice" value={form.notice_period} onChange={set('notice_period')} className={FIELD} />
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-slate-400 mb-3">
              Education &amp; experience
            </h3>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
              <div>
                <label className={LABEL} htmlFor="a-qual">Highest qualification</label>
                <input id="a-qual" value={form.qualification} onChange={set('qualification')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-exp">Total experience</label>
                <input id="a-exp" value={form.total_experience} onChange={set('total_experience')}
                  placeholder="e.g. 4 years" className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-company">Current company</label>
                <input id="a-company" value={form.current_company} onChange={set('current_company')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-cctc">Current CTC</label>
                <input id="a-cctc" value={form.current_ctc} onChange={set('current_ctc')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-ectc">Expected CTC</label>
                <input id="a-ectc" value={form.expected_ctc} onChange={set('expected_ctc')} className={FIELD} />
              </div>
              <div>
                <label className={LABEL} htmlFor="a-li">LinkedIn / portfolio</label>
                <input id="a-li" value={form.linkedin} onChange={set('linkedin')} className={FIELD} />
              </div>
            </div>
          </div>

          <div>
            <h3 className="text-[12px] font-bold uppercase tracking-widest text-slate-400 mb-3">
              Documents
            </h3>
            <div className="space-y-3">
              <div>
                <label className={LABEL} htmlFor="a-resume">Resume (PDF or Word, max {MAX_MB} MB)</label>
                <label htmlFor="a-resume"
                  className="flex items-center gap-2 h-10 px-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 text-[13px] text-slate-500 cursor-pointer hover:border-slate-400">
                  <Upload size={15} />
                  <span className="truncate">{resume ? resume.name : 'Choose a file…'}</span>
                </label>
                <input id="a-resume" type="file" className="hidden"
                  accept=".pdf,.doc,.docx,application/pdf" onChange={pickResume} />
              </div>

              <div>
                <label className={LABEL} htmlFor="a-certs">
                  Certificates (optional, up to {MAX_CERTS})
                </label>
                <label htmlFor="a-certs"
                  className="flex items-center gap-2 h-10 px-3 rounded-lg border border-dashed border-slate-300 bg-slate-50 text-[13px] text-slate-500 cursor-pointer hover:border-slate-400">
                  <Upload size={15} /> Add certificates…
                </label>
                <input id="a-certs" type="file" multiple className="hidden"
                  accept=".pdf,.doc,.docx,image/*" onChange={pickCertificates} />
                {certificates.length > 0 && (
                  <ul className="mt-2 space-y-1">
                    {certificates.map((f, i) => (
                      <li key={`${f.name}-${i}`}
                        className="flex items-center gap-2 text-[12.5px] text-slate-600">
                        <span className="truncate flex-1">{f.name}</span>
                        <button type="button" onClick={() => setCertificates((c) => c.filter((_, j) => j !== i))}
                          className="p-0.5 text-slate-400 hover:text-red-500">
                          <X size={13} />
                        </button>
                      </li>
                    ))}
                  </ul>
                )}
              </div>

              <div>
                <label className={LABEL} htmlFor="a-note">Anything else you would like us to know?</label>
                <textarea id="a-note" rows={3} value={form.cover_note} onChange={set('cover_note')}
                  className="w-full px-3 py-2 rounded-lg border border-slate-300 bg-white text-[14px] text-slate-900 resize-none focus:border-slate-500 focus:outline-none" />
              </div>
            </div>
          </div>

          <label className="flex items-start gap-2.5 cursor-pointer">
            <input type="checkbox" checked={form.declaration} onChange={set('declaration')}
              className="mt-1" required />
            <span className="text-[13px] text-slate-600">
              I confirm that the information provided above is accurate and complete. *
            </span>
          </label>

          {error && (
            <div className="p-3 rounded-lg bg-red-50 border border-red-200 text-[13px] text-red-700">
              {error}
            </div>
          )}

          <button type="submit" disabled={submitting}
            className="w-full h-11 rounded-lg bg-slate-900 text-white text-[14px] font-bold disabled:opacity-50 flex items-center justify-center gap-2">
            {submitting && <Loader2 size={16} className="animate-spin" />}
            {submitting ? 'Submitting…' : 'Submit application'}
          </button>
        </form>
      </Card>

      <p className="mt-4 text-center text-[11.5px] text-slate-400">
        Your details are shared only with this company&apos;s hiring team.
      </p>
    </Shell>
  );
};

export default ApplyPage;
