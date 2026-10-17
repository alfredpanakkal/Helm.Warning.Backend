import React from 'react';

export type AppMode = 'public' | 'admin';
export type PublicTab = 'map' | 'data' | 'sources';
export type AdminTab = 'overview' | 'pipeline' | 'import' | 'verify' | 'system';

interface HeaderProps {
  mode: AppMode;
  onSetMode: (mode: AppMode) => void;
  publicTab: PublicTab;
  onSetPublicTab: (tab: PublicTab) => void;
  adminTab: AdminTab;
  onSetAdminTab: (tab: AdminTab) => void;
  isAdminAuthenticated: boolean;
  adminEmail: string;
  onLogoutAdmin: () => void;
  warningsCount: number;
  onToggleDrawer: () => void;
  isDrawerOpen: boolean;
}

export const Header: React.FC<HeaderProps> = ({
  mode,
  onSetMode,
  publicTab,
  onSetPublicTab,
  isAdminAuthenticated,
  adminEmail,
  onLogoutAdmin,
  warningsCount,
  onToggleDrawer,
  isDrawerOpen
}) => {
  if (mode === 'admin') {
    return (
      <header className="admin-header">
        <div className="admin-header-inner">
          <div className="admin-brand">
            <span className="logo-badge" aria-hidden="true">HW</span>
            <span>Helm.Warning</span>
            <span className="admin-chip">Admin</span>
          </div>

          <div className="admin-header-actions">
            {adminEmail && <span className="admin-user">{adminEmail}</span>}
            <button
              type="button"
              className="btn btn-ghost"
              onClick={() => onSetMode('public')}
              style={{ textDecoration: 'none' }}
            >
              View Site ↗
            </button>
            <button
              type="button"
              className="btn btn-sm btn-secondary"
              onClick={onLogoutAdmin}
            >
              Sign Out
            </button>
          </div>
        </div>
      </header>
    );
  }

  return (
    <header className="site-header">
      <div className="header-inner">
        <a
          href="#main"
          className="logo"
          onClick={(e) => {
            e.preventDefault();
            onSetMode('public');
            onSetPublicTab('map');
          }}
        >
          <span className="logo-badge" aria-hidden="true">HW</span>
          <span>Helm.Warning</span>
        </a>

        {/* PUBLIC NAVIGATION */}
        <nav className="main-nav" aria-label="Main navigation">
          <div
            role="tablist"
            aria-label="Main navigation views"
            style={{ display: 'flex', gap: '4px', alignItems: 'center' }}
          >
            <button
              className={`nav-tab ${publicTab === 'map' ? 'active' : ''}`}
              role="tab"
              aria-selected={publicTab === 'map'}
              id="tab-btn-map"
              onClick={() => onSetPublicTab('map')}
            >
              Map View <span className="badge">{warningsCount}</span>
            </button>
            <button
              className={`nav-tab ${publicTab === 'data' ? 'active' : ''}`}
              role="tab"
              aria-selected={publicTab === 'data'}
              id="tab-btn-data"
              onClick={() => onSetPublicTab('data')}
            >
              Data Bank <span className="badge">{warningsCount}</span>
            </button>
            <button
              className={`nav-tab ${publicTab === 'sources' ? 'active' : ''}`}
              role="tab"
              aria-selected={publicTab === 'sources'}
              id="tab-btn-sources"
              onClick={() => onSetPublicTab('sources')}
            >
              Sources
            </button>
            <button
              type="button"
              className="admin-nav-trigger"
              onClick={() => onSetMode('admin')}
              title="Access Operator Console"
            >
              <svg
                style={{ width: '14px', height: '14px', stroke: 'currentColor', fill: 'none', strokeWidth: 2 }}
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2"></rect>
                <path d="M7 11V7a5 5 0 0 1 10 0v4"></path>
              </svg>
              <span>Admin Console</span>
            </button>
          </div>
        </nav>

        {/* Mobile menu button */}
        <button
          className="menu-toggle"
          onClick={onToggleDrawer}
          aria-label="Navigation Menu"
          aria-expanded={isDrawerOpen}
          aria-controls="drawer"
        >
          <svg
            viewBox="0 0 24 24"
            fill="none"
            strokeWidth="2"
            strokeLinecap="round"
            aria-hidden="true"
            focusable="false"
          >
            <line x1="3" y1="6" x2="21" y2="6" />
            <line x1="3" y1="12" x2="21" y2="12" />
            <line x1="3" y1="18" x2="21" y2="18" />
          </svg>
        </button>
      </div>
    </header>
  );
};
