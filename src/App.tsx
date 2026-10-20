import React, { useState, useEffect } from 'react';
import {
  NavWarning,
  RawMessage
} from './types/maritime';
import { getInitialSeedData } from './data/seedWarnings';
import {
  testSupabaseConnection,
  fetchLiveNavWarnings,
  fetchLiveRawMessages,
  subscribeToNavWarningChanges
} from './core/supabaseClient';
import { Header, AppMode, PublicTab, AdminTab } from './components/Header';
import { PublicPortal } from './components/public/PublicPortal';
import { AdminConsole } from './components/admin/AdminConsole';
import { AdminLoginGate } from './components/admin/AdminLoginGate';

export function App() {
  // Navigation State
  const [appMode, setAppMode] = useState<AppMode>('public');
  const [publicTab, setPublicTab] = useState<PublicTab>('map');
  const [adminTab, setAdminTab] = useState<AdminTab>('overview');
  const [isDrawerOpen, setIsDrawerOpen] = useState(false);

  // Admin Auth State
  const [isAdminAuthenticated, setIsAdminAuthenticated] = useState<boolean>(() => {
    return localStorage.getItem('HELM_ADMIN_AUTH') === 'true';
  });
  const [adminEmail, setAdminEmail] = useState<string>(() => {
    return localStorage.getItem('HELM_ADMIN_EMAIL') || 'admin@helm.warning';
  });

  // Data State
  const [warnings, setWarnings] = useState<NavWarning[]>([]);
  const [rawMessages, setRawMessages] = useState<RawMessage[]>([]);
  const [supabaseConnected, setSupabaseConnected] = useState<boolean>(false);
  const [toastMessage, setToastMessage] = useState<string | null>(null);

  const showToast = (msg: string) => {
    setToastMessage(msg);
    setTimeout(() => setToastMessage(null), 2600);
  };

  // Device classification on body
  useEffect(() => {
    const detectDevice = () => {
      const w = window.innerWidth;
      const ua = /Android|iPhone|iPad|iPod|Mobile/i.test(navigator.userAgent);
      document.body.classList.remove('is-mobile', 'is-tablet', 'is-desktop');
      if (w <= 768 || (ua && w <= 1024)) {
        document.body.classList.add('is-mobile');
      } else if (w <= 1024) {
        document.body.classList.add('is-tablet');
      } else {
        document.body.classList.add('is-desktop');
      }
    };
    detectDevice();
    window.addEventListener('resize', detectDevice);
    return () => window.removeEventListener('resize', detectDevice);
  }, []);

  // Load Initial Data
  useEffect(() => {
    const initializeData = async () => {
      const savedW = localStorage.getItem('HELM_NAV_WARNINGS');
      const savedM = localStorage.getItem('HELM_RAW_MESSAGES');

      let currentW: NavWarning[] = [];
      let currentM: RawMessage[] = [];

      if (savedW && savedM) {
        try {
          currentW = JSON.parse(savedW);
          currentM = JSON.parse(savedM);
        } catch {
          // ignore error
        }
      }

      if (currentW.length === 0) {
        const seed = getInitialSeedData();
        currentW = seed.warnings;
        currentM = seed.messages;
      }

      setWarnings(currentW);
      setRawMessages(currentM);

      // Verify Supabase connection
      const health = await testSupabaseConnection();
      setSupabaseConnected(health.success);

      if (health.success) {
        const liveRes = await fetchLiveNavWarnings();
        if (liveRes.data && liveRes.data.length > 0) {
          setWarnings(liveRes.data);
          localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(liveRes.data));
        }
      }
    };

    initializeData();

    // Subscribe to Realtime Postgres Changes on nav_warnings and nav_warning_geometries
    const unsubscribe = subscribeToNavWarningChanges(async () => {
      const liveRes = await fetchLiveNavWarnings();
      if (liveRes.data) {
        setWarnings(liveRes.data);
        localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(liveRes.data));
        showToast('Realtime update: navigation warnings refreshed');
      }
    });

    // 60-second fallback polling cycle for intermittent connections
    const pollingInterval = setInterval(async () => {
      const liveRes = await fetchLiveNavWarnings();
      if (liveRes.data) {
        setWarnings(liveRes.data);
        localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(liveRes.data));
      }
    }, 60000);

    return () => {
      unsubscribe();
      clearInterval(pollingInterval);
    };
  }, []);


  // Refresh handler
  const handleRefreshData = async () => {
    const health = await testSupabaseConnection();
    setSupabaseConnected(health.success);

    if (health.success) {
      const liveW = await fetchLiveNavWarnings();
      const liveM = await fetchLiveRawMessages();
      if (liveW.data && liveW.data.length > 0) {
        setWarnings(liveW.data);
        localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(liveW.data));
      }
      if (liveM.data && liveM.data.length > 0) {
        setRawMessages(liveM.data);
        localStorage.setItem('HELM_RAW_MESSAGES', JSON.stringify(liveM.data));
      }
      showToast('Data refreshed — latest published generation loaded');
    } else {
      showToast('Data refreshed — using cached synchronized dataset');
    }
  };

  const handleUpdateWarnings = (newWarnings: NavWarning[]) => {
    setWarnings(newWarnings);
    localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(newWarnings));
  };

  const handleAdminLogin = (email: string) => {
    setIsAdminAuthenticated(true);
    setAdminEmail(email);
    localStorage.setItem('HELM_ADMIN_AUTH', 'true');
    localStorage.setItem('HELM_ADMIN_EMAIL', email);
    showToast(`Authenticated as ${email}`);
  };

  const handleAdminLogout = () => {
    setIsAdminAuthenticated(false);
    localStorage.removeItem('HELM_ADMIN_AUTH');
    setAppMode('public');
    setPublicTab('map');
    showToast('Signed out of admin console');
  };

  const toggleDrawer = () => {
    setIsDrawerOpen((prev) => !prev);
  };

  const closeDrawer = () => {
    setIsDrawerOpen(false);
  };

  return (
    <>
      <a href="#main" className="skip-link">
        Skip to main content
      </a>

      {/* Top Header */}
      <Header
        mode={appMode}
        onSetMode={(m) => {
          setAppMode(m);
          closeDrawer();
        }}
        publicTab={publicTab}
        onSetPublicTab={(t) => {
          setPublicTab(t);
          closeDrawer();
        }}
        adminTab={adminTab}
        onSetAdminTab={(t) => setAdminTab(t)}
        isAdminAuthenticated={isAdminAuthenticated}
        adminEmail={adminEmail}
        onLogoutAdmin={handleAdminLogout}
        warningsCount={warnings.length}
        onToggleDrawer={toggleDrawer}
        isDrawerOpen={isDrawerOpen}
      />

      {/* Drawer Overlay & Navigation */}
      <div
        className={`drawer-overlay ${isDrawerOpen ? 'open' : ''}`}
        id="drawerOverlay"
        onClick={closeDrawer}
        aria-hidden="true"
      ></div>

      <nav
        className={`drawer ${isDrawerOpen ? 'open' : ''}`}
        id="drawer"
        aria-label="Mobile drawer navigation"
        aria-hidden={!isDrawerOpen}
      >
        <div className="drawer-header">
          <span className="logo-badge" aria-hidden="true">
            HW
          </span>{' '}
          Helm.Warning
        </div>
        <div className="drawer-nav">
          <button
            className={`drawer-item ${appMode === 'public' && publicTab === 'map' ? 'active' : ''}`}
            onClick={() => {
              setAppMode('public');
              setPublicTab('map');
              closeDrawer();
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
            </svg>
            Map View<span className="badge">{warnings.length}</span>
          </button>

          <button
            className={`drawer-item ${appMode === 'public' && publicTab === 'data' ? 'active' : ''}`}
            onClick={() => {
              setAppMode('public');
              setPublicTab('data');
              closeDrawer();
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
            </svg>
            Data Bank<span className="badge">{warnings.length}</span>
          </button>

          <button
            className={`drawer-item ${appMode === 'public' && publicTab === 'sources' ? 'active' : ''}`}
            onClick={() => {
              setAppMode('public');
              setPublicTab('sources');
              closeDrawer();
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
            </svg>
            Sources
          </button>

          <div style={{ height: '1px', background: 'var(--border)', margin: '8px 0' }}></div>

          <button
            className={`drawer-item ${appMode === 'admin' ? 'active' : ''}`}
            onClick={() => {
              setAppMode('admin');
              closeDrawer();
            }}
          >
            <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
              <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
              <path d="M7 11V7a5 5 0 0 1 10 0v4" />
            </svg>
            Admin Console 🔐
          </button>
        </div>
        <div className="drawer-footer">
          Automated decision-support system.
          <br />
          Not a substitute for GMDSS.
        </div>
      </nav>

      {/* Main Views */}
      {appMode === 'public' ? (
        <>
          <PublicPortal
            warnings={warnings}
            rawMessages={rawMessages}
            activeTab={publicTab}
            onSwitchTab={(t) => setPublicTab(t)}
            onRefreshData={handleRefreshData}
          />

          {/* Bottom Nav on Mobile */}
          <nav className="bottom-nav" aria-label="Mobile bottom navigation">
            <div
              role="tablist"
              aria-label="Mobile navigation views"
              style={{ display: 'flex', width: '100%', alignItems: 'center' }}
            >
              <button
                className={`bottom-nav-item ${publicTab === 'map' ? 'active' : ''}`}
                role="tab"
                aria-selected={publicTab === 'map'}
                onClick={() => setPublicTab('map')}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M9 20l-5.447-2.724A1 1 0 013 16.382V5.618a1 1 0 011.447-.894L9 7m0 13l6-3m-6 3V7m6 10l4.553 2.276A1 1 0 0021 18.382V7.618a1 1 0 00-.553-.894L15 4m0 13V4m0 0L9 7" />
                </svg>
                <span>Map</span>
                <span className="bottom-badge">{warnings.length}</span>
              </button>

              <button
                className={`bottom-nav-item ${publicTab === 'data' ? 'active' : ''}`}
                role="tab"
                aria-selected={publicTab === 'data'}
                onClick={() => setPublicTab('data')}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M3 10h18M7 15h1m4 0h1m-7 4h12a3 3 0 003-3V8a3 3 0 00-3-3H6a3 3 0 00-3 3v8a3 3 0 003 3z" />
                </svg>
                <span>Data</span>
              </button>

              <button
                className={`bottom-nav-item ${publicTab === 'sources' ? 'active' : ''}`}
                role="tab"
                aria-selected={publicTab === 'sources'}
                onClick={() => setPublicTab('sources')}
              >
                <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                  <path d="M19 11H5m14 0a2 2 0 012 2v6a2 2 0 01-2 2H5a2 2 0 01-2-2v-6a2 2 0 012-2m14 0V9a2 2 0 00-2-2M5 11V9a2 2 0 012-2m0 0V5a2 2 0 012-2h6a2 2 0 012 2v2M7 7h10" />
                </svg>
                <span>Sources</span>
              </button>
            </div>
          </nav>

          {/* Public Footer */}
          <footer className="site-footer">
            <div className="footer-inner">
              <div>Helm.Warning — NAVAREA Maritime Safety Information Pipeline</div>
              <div className="footer-disclaimer">
                Automated decision-support system. Not a substitute for GMDSS or official MSI.
              </div>
            </div>
          </footer>
        </>
      ) : !isAdminAuthenticated ? (
        <AdminLoginGate
          onLoginSuccess={handleAdminLogin}
          onBackToPublic={() => {
            setAppMode('public');
            setPublicTab('map');
          }}
        />
      ) : (
        <AdminConsole
          warnings={warnings}
          rawMessages={rawMessages}
          activeSub={adminTab}
          onSwitchSub={(s) => setAdminTab(s)}
          onUpdateWarnings={handleUpdateWarnings}
          onSwitchToPublic={() => {
            setAppMode('public');
            setPublicTab('map');
          }}
          supabaseConnected={supabaseConnected}
          adminEmail={adminEmail}
        />
      )}

      {/* Floating Toast Notification */}
      <div
        className={`toast ${toastMessage ? 'show' : ''}`}
        id="toast"
        role="status"
        aria-live="polite"
      >
        {toastMessage}
      </div>
    </>
  );
}

export default App;
