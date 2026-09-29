import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, useLocation, Link } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff, User, Building2, ArrowLeft } from 'lucide-react';
import './Login.css';

// Assets
import loginIllustration from '../assets/login-illustration.svg';
import sparshLogo from '../assets/sparshLogo.png';

const Login = () => {
  const { login, user } = useAuth();
  const navigate = useNavigate();
  const location = useLocation();

  // Which credential the user is typing. Email stays the default because it is what
  // everybody already uses; the username tab exists for people whose address is not unique.
  const [mode, setMode] = useState('email');
  const [identifier, setIdentifier] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);
  // Set when one email turns out to name accounts in several companies: the server sends the
  // list back and the form becomes a chooser rather than guessing on the user's behalf.
  const [accounts, setAccounts] = useState(null);

  const isEmail = mode === 'email';

  const switchMode = (next) => {
    setMode(next);
    setIdentifier('');
    setError('');
    setAccounts(null);
  };

  // Return the user to whatever they were trying to reach before being sent here (set by
  // PrivateRoute), so a mailed deep link such as an assigned TPMS form survives the login step.
  // Anyone arriving at /login directly has no `from` and still lands on the dashboard, so this
  // changes nothing for the ordinary sign-in path.
  const redirectTo = location.state?.from?.pathname
    ? `${location.state.from.pathname}${location.state.from.search || ''}`
    : '/';

  useEffect(() => {
    if (user) {
      navigate(redirectTo, { replace: true });
    }
  }, [user, navigate, redirectTo]);

  const attempt = async (companyId) => {
    setIsLoading(true);
    setError('');
    try {
      await login(identifier, password, companyId);
    } catch (err) {
      const status = err.response?.status;
      const detail = err.response?.data?.detail;
      if (status === 409 && detail?.accounts?.length) {
        // Not a failure — the password was right, the address just was not specific enough.
        setAccounts(detail.accounts);
        setError('');
      } else if (status === 403) {
        setError(typeof detail === 'string' ? detail : 'This account has been deactivated.');
      } else {
        setAccounts(null);
        setError(isEmail
          ? 'Incorrect email or password. Please try again.'
          : 'Incorrect username or password. Please try again.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    attempt();
  };

  return (
    <div className="login-container">
      {/* Left Column: Branding and Illustration */}
      <div className="login-left">
        <div className="login-left-content">
          <img src={loginIllustration} alt="Authentication Illustration" className="login-illustration" />
          <h1>Master Your Workflow</h1>
          <p>Elevate your productivity with our comprehensive suite of enterprise management tools.</p>
        </div>
      </div>

      {/* Right Column: Login Form */}
      <div className="login-right">
        <div className="login-form-container">
          <img src={sparshLogo} alt="Sparsh Magic Logo" className="login-logo" />

          <div className="login-header">
            <h2>Welcome back!</h2>
            <p>Please enter your credentials to access your account</p>
          </div>

          {accounts ? (
            /* One email, several companies. The password is already verified at this point —
               all that is missing is which account they meant. */
            <div className="login-form">
              <div className="account-chooser-head">
                <Building2 size={18} />
                <div>
                  <strong>Which company?</strong>
                  <p>This email is used for more than one. Pick the account to sign in to.</p>
                </div>
              </div>
              <div className="account-choices">
                {accounts.map((a) => (
                  <button
                    key={a.company_id || a.username}
                    type="button"
                    className="account-choice"
                    disabled={isLoading}
                    onClick={() => attempt(a.company_id)}
                  >
                    <span className="account-choice-name">{a.company_name}</span>
                    <span className="account-choice-meta">{a.username}</span>
                  </button>
                ))}
              </div>
              <button
                type="button"
                className="account-back"
                onClick={() => { setAccounts(null); setPassword(''); }}
              >
                <ArrowLeft size={14} /> Use a different account
              </button>
            </div>
          ) : (
          <form onSubmit={handleSubmit} className="login-form">
            <div className="credential-tabs" role="tablist">
              <button
                type="button"
                role="tab"
                aria-selected={isEmail}
                className={`credential-tab ${isEmail ? 'is-active' : ''}`}
                onClick={() => switchMode('email')}
              >
                <Mail size={15} /> Email
              </button>
              <button
                type="button"
                role="tab"
                aria-selected={!isEmail}
                className={`credential-tab ${!isEmail ? 'is-active' : ''}`}
                onClick={() => switchMode('username')}
              >
                <User size={15} /> Username
              </button>
            </div>

            <div className="input-group">
              <label htmlFor="identifier">
                {isEmail ? 'Email Address' : 'Username'} <span>*</span>
              </label>
              <div className="input-wrapper">
                {isEmail ? <Mail className="input-icon" size={18} />
                         : <User className="input-icon" size={18} />}
                <input
                  id="identifier"
                  /* Deliberately `text` even for email: the browser's own email validation
                     rejects a username, and switching the type would make the field fight the
                     tab the user just chose. The server decides what the value means. */
                  type="text"
                  autoComplete="username"
                  autoCapitalize="none"
                  spellCheck="false"
                  placeholder={isEmail ? 'name@company.com' : 'e.g. PTP_Users001'}
                  value={identifier}
                  onChange={(e) => setIdentifier(e.target.value)}
                  required
                />
              </div>
              {!isEmail && (
                <p className="input-hint">
                  Your company username, from your welcome email or your administrator.
                </p>
              )}
            </div>

            <div className="input-group">
              <label htmlFor="password">Password <span>*</span></label>
              <div className="input-wrapper">
                <Lock className="input-icon" size={18} />
                <input
                  id="password"
                  type={showPassword ? 'text' : 'password'}
                  placeholder="••••••••"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                />
                <div
                  className="eye-icon"
                  onClick={() => setShowPassword(!showPassword)}
                >
                  {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
                </div>
              </div>
            </div>

            <div className="form-footer">
              <label className="remember-me">
                <input type="checkbox" />
                <span>Remember me</span>
              </label>
              <Link to="/forgot-password"  className="forgot-password">Forgot Password?</Link>
            </div>

            {error && <p style={{ color: '#ef4444', fontSize: '0.85rem', textAlign: 'center' }}>{error}</p>}

            <button type="submit" className="signin-btn" disabled={isLoading}>
              {isLoading ? 'Signing In...' : 'Sign In'}
            </button>
          </form>
          )}

          <footer className="login-footer">
            <p className="footer-company">
<a href="https://www.dtableanalytics.com/" target="_blank" rel="noopener noreferrer" style={{ color: '#2563eb', fontWeight: 800, textDecoration: 'none' }}>Powered by D Table Analytics</a>
            </p>
            <p className="footer-copyright">
              Copyright © 2026 Sparsh Magic Pvt. Ltd.
            </p>
          </footer>
        </div>
      </div>
    </div>
  );
};

export default Login;
