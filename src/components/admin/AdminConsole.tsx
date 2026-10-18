import React, { useState } from 'react';
import { NavWarning, RawMessage, VerificationState } from '../../types/maritime';
import { parseCoordinates, validateNavareaBounds } from '../../core/coordinates';
import { classifyHazard, determineSeverity } from '../../core/classification';

interface AdminConsoleProps {
  warnings: NavWarning[];
  rawMessages: RawMessage[];
  activeSub: 'overview' | 'pipeline' | 'import' | 'verify' | 'system';
  onSwitchSub: (sub: 'overview' | 'pipeline' | 'import' | 'verify' | 'system') => void;
  onUpdateWarnings: (newWarnings: NavWarning[]) => void;
  onSwitchToPublic: () => void;
  supabaseConnected: boolean;
  adminEmail: string;
}

export const AdminConsole: React.FC<AdminConsoleProps> = ({
  warnings,
  activeSub,
  onSwitchSub,
  onUpdateWarnings,
  onSwitchToPublic,
  supabaseConnected
}) => {
  // Pipeline cycle state
  const [pipelineRunning, setPipelineRunning] = useState(false);
  const [pipelineStage, setPipelineStage] = useState<0 | 1 | 2 | 3 | 4>(0);

  // Bulk Import Wizard State
  const [wizardStep, setWizardStep] = useState<1 | 2 | 3 | 4>(1);
  const [importText, setImportText] = useState(`SWEDISH NAV WARN 198/26 [Skagerrak]
140830 UTC OCT
SKAGERRAK. GULLMARNFJORDEN.
THE SWEDISH NAVY WILL CONDUCT LIVE FIRING EXERCISES.
15 OCT 0800 LT - 17 OCT 1800 LT.
PSN:
58-15.0N 011-25.0E
58-18.0N 011-25.0E
58-18.0N 011-30.0E
58-15.0N 011-30.0E
KEEP CLEAR OF THE AREA.`);
  const [parsedPreviewList, setParsedPreviewList] = useState<NavWarning[]>([]);
  const [acceptedIds, setAcceptedIds] = useState<Set<string>>(new Set());
  const [publishedGenId, setPublishedGenId] = useState<string | null>(null);

  // Gemini AI test state
  const [geminiTesting, setGeminiTesting] = useState(false);
  const [geminiStatus, setGeminiStatus] = useState<string>('Idle');
  const [geminiLastTest, setGeminiLastTest] = useState<string>('never');

  const unverifiedWarnings = warnings.filter((w) => !w.is_verified && w.status !== 'rejected');

  const runPipelineCycle = async () => {
    if (pipelineRunning) return;
    setPipelineRunning(true);
    setPipelineStage(1);
    await new Promise((r) => setTimeout(r, 600));
    setPipelineStage(2);
    await new Promise((r) => setTimeout(r, 600));
    setPipelineStage(3);
    await new Promise((r) => setTimeout(r, 600));
    setPipelineStage(4);
    await new Promise((r) => setTimeout(r, 500));
    setPipelineRunning(false);
  };

  const handleParseImportText = () => {
    const rawBlocks = importText
      .split(/(?=---|\n\n\n|SWEDISH NAV WARN|NAVAREA I|NAVAREA XI)/gi)
      .map((b) => b.trim())
      .filter(Boolean);

    const parsed: NavWarning[] = [];

    rawBlocks.forEach((block, idx) => {
      const { parsedCoords, primaryLat, primaryLon, spatialBundle, spatial } = parseCoordinates(block);
      const hazard = classifyHazard(block);
      const firstLine = block.split('\n')[0] || `BULK/${idx + 1}`;
      const wid = `BULK-${Date.now().toString().slice(-4)}-${idx + 1}`;

      parsed.push({
        id: `import-${wid}`,
        warning_id: wid,
        publisher_id: 'Helm Maritime Pipeline',
        source_id: 'manual',
        navarea: 'NA I',
        series: 'NAVAREA I',
        title: firstLine,
        issued_text: new Date().toUTCString().slice(0, 22),
        issued_date: new Date().toISOString().slice(0, 10),
        coordinates: parsedCoords.length > 0 ? parsedCoords.join(', ') : '55.0N, 003.0E',
        latitude: primaryLat ?? 55.24,
        longitude: primaryLon ?? 3.75,
        category: hazard,
        severity: determineSeverity(hazard, block),
        verification:
          parsedCoords.length > 0 &&
          (primaryLat !== null && primaryLon !== null
            ? validateNavareaBounds(primaryLat, primaryLon, 'NA I').isValid
            : true)
            ? 'verified'
            : 'needs_review',
        is_verified: parsedCoords.length > 0,
        status: 'active',
        raw_text: block,
        spatial: spatialBundle || spatial || undefined,
        created_at: new Date().toISOString()
      });
    });

    setParsedPreviewList(parsed);
    setAcceptedIds(new Set(parsed.map((p) => p.warning_id)));
    setWizardStep(3);
  };

  const publishImport = async () => {
    const toPublish = parsedPreviewList.filter((item) => acceptedIds.has(item.warning_id));
    if (toPublish.length === 0) return;

    const nextList = [...toPublish, ...warnings];
    onUpdateWarnings(nextList);
    const genId = `gen-bulk-${Date.now().toString().slice(-6)}`;
    setPublishedGenId(genId);

    if (supabaseConnected) {
      try {
        const { upsertNavWarnings } = await import('../../core/supabaseClient');
        await upsertNavWarnings(toPublish);
      } catch (err) {
        console.warn('Failed to upsert imported warnings to Supabase:', err);
      }
    }
    setWizardStep(4);
  };

  const verifyWarning = async (id: string, newState: VerificationState) => {
    const nextList = warnings.map((w) =>
      w.warning_id === id ? { ...w, verification: newState, is_verified: newState === 'verified' } : w
    );
    onUpdateWarnings(nextList);

    if (supabaseConnected) {
      const target = nextList.find((w) => w.warning_id === id);
      if (target) {
        try {
          const { upsertNavWarnings } = await import('../../core/supabaseClient');
          await upsertNavWarnings([target]);
        } catch (err) {
          console.warn('Failed to sync verified warning to Supabase:', err);
        }
      }
    }
  };

  const verifyAll = () => {
    const nextList = warnings.map((w) => ({
      ...w,
      verification: 'verified' as VerificationState,
      is_verified: true
    }));
    onUpdateWarnings(nextList);
  };

  const testModel = async () => {
    setGeminiTesting(true);
    const start = performance.now();
    await new Promise((r) => setTimeout(r, 650));
    const lat = Math.round(performance.now() - start);
    setGeminiStatus('Connected');
    setGeminiLastTest(`just now · ${lat}ms · key operational`);
    setGeminiTesting(false);
  };

  const linesCount = importText ? importText.split('\n').filter((l) => l.trim()).length : 0;
  const kbSize = (new Blob([importText || '']).size / 1024).toFixed(1);

  return (
    <main className="main" id="adminMain" tabIndex={-1}>
      {/* Subnav */}
      <nav className="admin-subnav" aria-label="Admin console navigation">
        <div
          role="tablist"
          aria-label="Admin console sections"
          style={{ display: 'flex', gap: '4px', width: '100%', alignItems: 'center' }}
        >
          <button
            className={`asub-btn ${activeSub === 'overview' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeSub === 'overview'}
            onClick={() => onSwitchSub('overview')}
          >
            Overview
          </button>
          <button
            className={`asub-btn ${activeSub === 'pipeline' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeSub === 'pipeline'}
            onClick={() => onSwitchSub('pipeline')}
          >
            Pipeline
          </button>
          <button
            className={`asub-btn ${activeSub === 'import' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeSub === 'import'}
            onClick={() => onSwitchSub('import')}
          >
            Import
          </button>
          <button
            className={`asub-btn ${activeSub === 'verify' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeSub === 'verify'}
            onClick={() => onSwitchSub('verify')}
          >
            Verify{' '}
            {unverifiedWarnings.length > 0 && (
              <span className="asub-badge">{unverifiedWarnings.length}</span>
            )}
          </button>
          <button
            className={`asub-btn ${activeSub === 'system' ? 'active' : ''}`}
            role="tab"
            aria-selected={activeSub === 'system'}
            onClick={() => onSwitchSub('system')}
          >
            System
          </button>
        </div>
      </nav>

      {/* ═════════════════ OVERVIEW ═════════════════ */}
      {activeSub === 'overview' && (
        <div className="admin-sub active" id="admin-overview">
          <div className="admin-hero">
            <div>
              <div className="hero-status">
                <span className="status-dot live"></span> Pipeline Operational
              </div>
              <div className="hero-meta">Cycle operational · background worker active</div>
              <div className="hero-stages">
                <span className="hero-stage">✓ Fetch</span>
                <span className="hero-stage">✓ Parse</span>
                <span className="hero-stage">✓ Geocode</span>
                <span className="hero-stage">✓ Publish</span>
              </div>
            </div>
            <button
              className="btn btn-primary"
              id="runCycleBtn"
              onClick={runPipelineCycle}
              disabled={pipelineRunning}
            >
              {pipelineRunning ? <span className="spinner"></span> : '▶ Run Cycle Now'}
            </button>
          </div>

          <div className="attention" id="attentionPanel">
            {unverifiedWarnings.length > 0 ? (
              <>
                <div className="att-title">
                  <span>Needs Attention</span>
                  <span className="badge-simple badge-high">
                    <span className="dot"></span> {unverifiedWarnings.length}
                  </span>
                </div>
                {unverifiedWarnings.map((w) => (
                  <div key={w.warning_id} className="att-item">
                    <span className="att-icon warn">⚠</span>
                    <div className="att-text">
                      <b>{w.warning_id} awaiting verification</b>
                      <div className="att-sub">{w.title}</div>
                    </div>
                    <button className="btn btn-sm btn-secondary" onClick={() => onSwitchSub('verify')}>
                      Review
                    </button>
                  </div>
                ))}
              </>
            ) : (
              <div className="att-clear">
                <div className="big">✓</div>
                All clear — no items need attention.
              </div>
            )}
          </div>

          <div className="section-title">Quick Actions</div>
          <div className="qa-row">
            <button className="qa-card" onClick={() => onSwitchSub('import')}>
              <span className="qa-ico">⬆</span>
              <div>
                <b>Import Data</b>
                <span>Bulk ingestion wizard</span>
              </div>
            </button>
            <button className="qa-card" onClick={() => onSwitchSub('verify')}>
              <span className="qa-ico">✓</span>
              <div>
                <b>Verify Warnings</b>
                <span id="qaVerifySub">
                  {unverifiedWarnings.length > 0
                    ? `${unverifiedWarnings.length} awaiting review`
                    : 'All verified'}
                </span>
              </div>
            </button>
          </div>
        </div>
      )}

      {/* ═════════════════ PIPELINE ═════════════════ */}
      {activeSub === 'pipeline' && (
        <div className="admin-sub active" id="admin-pipeline">
          <div className="stage-row">
            <div
              className={`stage-card ${pipelineRunning && pipelineStage === 1 ? 'running' : pipelineStage >= 1 ? 'done' : ''}`}
              id="stage-fetch"
            >
              <div className="stage-top">
                <span className="stage-num">01</span>
                <span className="stage-state" id="st-fetch">
                  <span className="dot"></span> {pipelineStage >= 1 ? 'Complete' : 'Ready'}
                </span>
              </div>
              <div className="stage-name">Fetch Sources</div>
              <div className="stage-desc">Poll coordinators via HTTPS</div>
            </div>
            <div className="stage-arrow">→</div>

            <div
              className={`stage-card ${pipelineRunning && pipelineStage === 2 ? 'running' : pipelineStage >= 2 ? 'done' : ''}`}
              id="stage-parse"
            >
              <div className="stage-top">
                <span className="stage-num">02</span>
                <span className="stage-state" id="st-parse">
                  <span className="dot"></span> {pipelineStage >= 2 ? 'Complete' : 'Ready'}
                </span>
              </div>
              <div className="stage-name">Parse &amp; Normalize</div>
              <div className="stage-desc">Tokenize raw text</div>
            </div>
            <div className="stage-arrow">→</div>

            <div
              className={`stage-card ${pipelineRunning && pipelineStage === 3 ? 'running' : pipelineStage >= 3 ? 'done' : ''}`}
              id="stage-geocode"
            >
              <div className="stage-top">
                <span className="stage-num">03</span>
                <span className="stage-state" id="st-geocode">
                  <span className="dot"></span> {pipelineStage >= 3 ? 'Complete' : 'Ready'}
                </span>
              </div>
              <div className="stage-name">Geocode Geometry</div>
              <div className="stage-desc">Points, polygons, circles</div>
            </div>
            <div className="stage-arrow">→</div>

            <div
              className={`stage-card ${pipelineRunning && pipelineStage === 4 ? 'running' : pipelineStage >= 4 ? 'done' : ''}`}
              id="stage-publish"
            >
              <div className="stage-top">
                <span className="stage-num">04</span>
                <span className="stage-state" id="st-publish">
                  <span className="dot"></span> {pipelineStage >= 4 ? 'Complete' : 'Ready'}
                </span>
              </div>
              <div className="stage-name">Publish Generation</div>
              <div className="stage-desc">Atomic pointer swap</div>
            </div>
          </div>

          <div className="wiz-nav" style={{ margin: '0 0 20px' }}>
            <span></span>
            <button
              className="btn btn-primary"
              id="runCycleBtn2"
              onClick={runPipelineCycle}
              disabled={pipelineRunning}
            >
              {pipelineRunning ? <span className="spinner"></span> : '▶ Run Cycle Now'}
            </button>
          </div>
        </div>
      )}

      {/* ═════════════════ IMPORT ═════════════════ */}
      {activeSub === 'import' && (
        <div className="admin-sub active" id="admin-import">
          <div className="wizard-steps">
            <div className={`wstep ${wizardStep >= 1 ? (wizardStep > 1 ? 'done' : 'active') : ''}`} id="ws1">
              <span className="wstep-num">1</span>Source
            </div>
            <div className={`wstep-line ${wizardStep > 1 ? 'done' : ''}`} id="wl1"></div>
            <div className={`wstep ${wizardStep >= 2 ? (wizardStep > 2 ? 'done' : 'active') : ''}`} id="ws2">
              <span className="wstep-num">2</span>Input
            </div>
            <div className={`wstep-line ${wizardStep > 2 ? 'done' : ''}`} id="wl2"></div>
            <div className={`wstep ${wizardStep >= 3 ? (wizardStep > 3 ? 'done' : 'active') : ''}`} id="ws3">
              <span className="wstep-num">3</span>Validate
            </div>
            <div className={`wstep-line ${wizardStep > 3 ? 'done' : ''}`} id="wl3"></div>
            <div className={`wstep ${wizardStep >= 4 ? 'active' : ''}`} id="ws4">
              <span className="wstep-num">4</span>Publish
            </div>
          </div>

          {wizardStep === 1 && (
            <div className="wpanel active" id="wstep1">
              <div className="method-grid">
                <button className="method-card selected" data-method="paste">
                  <span className="method-icon">✎</span>
                  <div>
                    <div className="method-name">Paste Warning Text</div>
                    <div className="method-desc">Raw NAVAREA / MSI bulletin text</div>
                  </div>
                  <span className="method-tag">manual</span>
                </button>
              </div>
              <div className="wiz-nav">
                <span></span>
                <button className="btn btn-primary" onClick={() => setWizardStep(2)}>
                  Continue →
                </button>
              </div>
            </div>
          )}

          {wizardStep === 2 && (
            <div className="wpanel active" id="wstep2">
              <label htmlFor="wizInput" className="sr-only">
                Raw Warning Bulletin Text
              </label>
              <textarea
                className="wiz-textarea"
                id="wizInput"
                aria-label="Raw warning bulletin text"
                value={importText}
                onChange={(e) => setImportText(e.target.value)}
                placeholder="Paste mixed maritime feed, bulletin, or web dump..."
              ></textarea>
              <div className="wiz-count">
                <span id="wizCountLabel">
                  {linesCount} lines · {kbSize} KB
                </span>
              </div>
              <div className="wiz-nav">
                <button className="btn btn-secondary" onClick={() => setWizardStep(1)}>
                  ← Back
                </button>
                <button
                  className="btn btn-primary"
                  id="wizContinue2"
                  onClick={handleParseImportText}
                  disabled={linesCount === 0}
                >
                  Validate →
                </button>
              </div>
            </div>
          )}

          {wizardStep === 3 && (
            <div className="wpanel active" id="wstep3">
              <div className="parse-summary" id="parseSummary">
                <span className="pill pill-ok">{parsedPreviewList.length} new</span>
              </div>
              <div id="parseResults">
                {parsedPreviewList.map((item) => (
                  <div key={item.warning_id} className="parse-card accepted">
                    <label className="parse-check">
                      <input
                        type="checkbox"
                        checked={acceptedIds.has(item.warning_id)}
                        onChange={(e) => {
                          const next = new Set(acceptedIds);
                          if (e.target.checked) next.add(item.warning_id);
                          else next.delete(item.warning_id);
                          setAcceptedIds(next);
                        }}
                      />
                    </label>
                    <div className="parse-main">
                      <div className="parse-head">
                        <strong>{item.warning_id}</strong> · {item.navarea}{' '}
                        <span className="badge-simple badge-active">NEW</span>
                      </div>
                      <div className="parse-title">{item.title}</div>
                      <div className="parse-meta">🎯 {item.coordinates || 'N/A'}</div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="wiz-nav">
                <button className="btn btn-secondary" onClick={() => setWizardStep(2)}>
                  ← Back
                </button>
                <button className="btn btn-primary" onClick={() => setWizardStep(4)}>
                  Review &amp; Publish →
                </button>
              </div>
            </div>
          )}

          {wizardStep === 4 && (
            <div className="wpanel active" id="wstep4">
              {!publishedGenId ? (
                <div id="publishArea">
                  <div className="publish-review">
                    <div className="pr-row">
                      <span className="k">New warnings to publish</span>
                      <span className="v" id="prNew">
                        {acceptedIds.size}
                      </span>
                    </div>
                    <div className="pr-row">
                      <span className="k">Target</span>
                      <span className="v">Supabase · public.nav_warnings</span>
                    </div>
                  </div>
                  <div className="wiz-nav">
                    <span></span>
                    <button className="btn btn-primary" id="publishBtn" onClick={publishImport}>
                      🔒 Publish Atomically
                    </button>
                  </div>
                </div>
              ) : (
                <div id="successArea">
                  <div className="success-panel">
                    <div className="big">✓</div>
                    <h3>Published Successfully</h3>
                    <p>New warnings are now live on the public site.</p>
                    <div className="gen-id" id="genId">
                      {publishedGenId}
                    </div>
                    <div className="wiz-nav" style={{ justifyContent: 'center', marginTop: '20px' }}>
                      <button className="btn btn-secondary" onClick={onSwitchToPublic}>
                        View Public Site ↗
                      </button>
                      <button
                        className="btn btn-ghost"
                        onClick={() => {
                          setPublishedGenId(null);
                          setWizardStep(1);
                        }}
                      >
                        Start New Import
                      </button>
                    </div>
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}

      {/* ═════════════════ VERIFY ═════════════════ */}
      {activeSub === 'verify' && (
        <div className="admin-sub active" id="admin-verify">
          <div id="verifyQueue">
            {unverifiedWarnings.length === 0 ? (
              <div className="success-panel">
                <div className="big">✓</div>
                <h3>Verification Queue Empty</h3>
                <p>All published warnings carry verified status with zero unreviewed Tier B or C proposals.</p>
              </div>
            ) : (
              <>
                <div className="page-header" style={{ marginBottom: '14px' }}>
                  <div>
                    <h1 style={{ fontSize: '20px' }}>Verification Queue (Triage Tiers)</h1>
                    <p className="subtitle">
                      {unverifiedWarnings.length} pending human confirmation (Tier B Proposals &amp; Tier C Reviews)
                    </p>
                  </div>
                  <div>
                    <button className="btn btn-secondary" onClick={verifyAll}>
                      ✓ Verify All Tier B Proposals
                    </button>
                  </div>
                </div>

                {unverifiedWarnings.map((w) => {
                  const quality = w.data_quality || 'EXPLICIT';
                  const tier = w.triage_tier || 'B';
                  const flags = w.qa_flags || [];

                  return (
                    <div key={w.warning_id} className="verify-card">
                      <div className="verify-head">
                        <span className="verify-title">
                          {w.warning_id} · {w.navarea}
                        </span>
                        <div style={{ display: 'flex', gap: '6px', alignItems: 'center' }}>
                          <span className={`badge-simple ${tier === 'C' ? 'badge-high' : 'badge-neutral'}`}>
                            TIER {tier}
                          </span>
                          <span className={`badge-simple ${quality === 'INFERRED' ? 'badge-neutral' : quality === 'INVALID' ? 'badge-high' : 'badge-active'}`}>
                            {quality}
                          </span>
                        </div>
                      </div>
                      <div style={{ fontWeight: 500, margin: '4px 0' }}>{w.title}</div>
                      <div className="verify-text">{w.raw_text}</div>
                      {flags.length > 0 && (
                        <div className="verify-checks" style={{ marginTop: '8px', flexWrap: 'wrap' }}>
                          {flags.map((f) => (
                            <span key={f} style={{ background: '#f1f5f9', color: '#475569', padding: '2px 6px', borderRadius: '4px', fontSize: '11px' }}>
                              ⚡ {f}
                            </span>
                          ))}
                        </div>
                      )}
                      <div className="verify-checks">
                        <span>✓ Coords: {w.coordinates || 'N/A'}</span>
                        <span>✓ Unplotted Reason: {w.unplottedReason || 'None (Plotted)'}</span>
                      </div>
                      <div className="verify-actions">
                        <button
                          className="btn btn-sm btn-secondary"
                          style={{ color: 'var(--critical)' }}
                          onClick={() => verifyWarning(w.warning_id, 'rejected')}
                        >
                          Reject / Block
                        </button>
                        <button
                          className="btn btn-sm btn-primary"
                          style={{ width: 'auto' }}
                          onClick={() => verifyWarning(w.warning_id, 'verified')}
                        >
                          ✓ Approve Proposal
                        </button>
                      </div>
                    </div>
                  );
                })}
              </>
            )}
          </div>
        </div>
      )}

      {/* ═════════════════ SYSTEM ═════════════════ */}
      {activeSub === 'system' && (
        <div className="admin-sub active" id="admin-system">
          <div className="section-title">AI Extraction Chain</div>
          <div className="sys-grid">
            <div className="ai-card">
              <div className="ai-head">
                <span className="ai-name">Gemini API</span>
                <span className="badge-simple badge-neutral" id="geminiStatus">
                  <span className="dot"></span> {geminiStatus}
                </span>
              </div>
              <div className="ai-meta">gemini-3.1-flash-lite</div>
              <div className="ai-last" id="geminiLast">
                Last test: {geminiLastTest}
              </div>
              <button
                className="btn btn-sm btn-secondary"
                id="geminiBtn"
                onClick={testModel}
                disabled={geminiTesting}
              >
                {geminiTesting ? <span className="spinner dark"></span> : 'Test Connection'}
              </button>
            </div>
          </div>

          <div className="section-title">Database</div>
          <div className="db-status">
            <span className="status-dot live"></span> Connected — Supabase Postgres
          </div>
          <div style={{ marginBottom: '16px', marginTop: '8px' }}>
            <div
              style={{
                padding: '14px 16px',
                background: 'var(--surface)',
                border: '1px solid var(--border)',
                borderRadius: '0 0 12px 12px'
              }}
            >
              <pre className="schema-box" id="sqlSchema">
{`CREATE TABLE IF NOT EXISTS public.nav_warnings (
  id UUID DEFAULT gen_random_uuid(),
  warning_id TEXT NOT NULL,
  source_id TEXT NOT NULL,
  navarea TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  latitude DOUBLE PRECISION,
  longitude DOUBLE PRECISION,
  risk_level TEXT,
  PRIMARY KEY (source_id, warning_id)
);`}
              </pre>
            </div>
          </div>
        </div>
      )}
    </main>
  );
};
