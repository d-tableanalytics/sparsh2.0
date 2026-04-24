import React, { useState, useEffect } from 'react';
import { useAuth } from '../context/AuthContext';
import { useNavigate, Link } from 'react-router-dom';
import { Mail, Lock, Eye, EyeOff } from 'lucide-react';
import './Login.css';

// Assets
import loginIllustration from '../assets/login-illustration.svg';
import sparshLogo from '../assets/sparshLogo.png';

const Login = () => {
  const { login, user } = useAuth();
  const navigate = useNavigate();

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState('');
  const [isLoading, setIsLoading] = useState(false);

  useEffect(() => {
    if (user) {
      navigate('/');
    }
  }, [user, navigate]);

  const handleSubmit = async (e) => {
    e.preventDefault();
    setIsLoading(true);
    setError('');

    try {
      await login(email, password);
    } catch (err) {
      setError('Invalid credentials or server error. Please try again.');
    } finally {
      setIsLoading(false);
    }
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

          <form onSubmit={handleSubmit} className="login-form">
            <div className="input-group">
              <label htmlFor="email">Email Address <span>*</span></label>
              <div className="input-wrapper">
                <Mail className="input-icon" size={18} />
                <input
                  id="email"
                  type="email"
                  placeholder="name@company.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                />
              </div>
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

          <footer className="login-footer">
            <p className="footer-company">
              Designed & Managed by <span style={{ color: '#2563eb' }}>D-TABLE ANALYTICS</span>
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
