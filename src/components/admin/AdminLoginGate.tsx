import React, { useState } from 'react';

interface AdminLoginGateProps {
  onLoginSuccess: (email: string) => void;
  onBackToPublic: () => void;
}

export const AdminLoginGate: React.FC<AdminLoginGateProps> = ({
  onLoginSuccess,
  onBackToPublic
}) => {
  const [email, setEmail] = useState('admin@helm.warning');
  const [password, setPassword] = useState('••••••••');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!email) {
      setError('Email is required');
      return;
    }
    setLoading(true);
    setTimeout(() => {
      setLoading(false);
      onLoginSuccess(email);
    }, 400);
  };

  return (
    <div id="loginView">
      <div className="login-card">
        <div className="login-logo">
          <span className="logo-badge">HW</span> Helm.Warning
        </div>
        <div className="login-sub">Admin Console — restricted operator access</div>

        {error && <div className="login-error">{error}</div>}

        <form onSubmit={handleSubmit}>
          <label className="login-label" htmlFor="loginEmail">
            Email
          </label>
          <input
            className="login-input"
            type="email"
            id="loginEmail"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="admin@helm.warning"
            autoComplete="username"
            required
          />

          <label className="login-label" htmlFor="loginPassword">
            Password
          </label>
          <input
            className="login-input"
            type="password"
            id="loginPassword"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            autoComplete="current-password"
            required
          />

          <button className="btn btn-primary" type="submit" id="loginBtn" style={{ width: '100%' }} disabled={loading}>
            {loading ? <span className="spinner"></span> : 'Sign In'}
          </button>
        </form>

        <div style={{ textAlign: 'center', marginTop: '20px' }}>
          <a
            href="#public"
            onClick={(e) => {
              e.preventDefault();
              onBackToPublic();
            }}
            style={{ fontSize: '13px', color: 'var(--text-light)', textDecoration: 'none' }}
          >
            ← Back to public maritime portal
          </a>
        </div>
      </div>
    </div>
  );
};
