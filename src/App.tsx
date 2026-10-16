import React, { useState, useEffect } from 'react';
import {
  NavWarning,
  RawMessage,
  SpatialFeature,
  NavareaRegion,
  PipelineExecutionLog
} from './types/maritime';
import { getInitialSeedData } from './data/seedWarnings';
import { Navbar } from './components/Navbar';
import { MaritimeMap } from './components/MaritimeMap';
import { WarningList } from './components/WarningList';
import { WarningDetailModal } from './components/WarningDetailModal';
import { PipelineRunnerModal } from './components/PipelineRunnerModal';
import { BulletinParserStudio } from './components/BulletinParserStudio';
import { TestSuiteRunnerModal } from './components/TestSuiteRunnerModal';
import { SupabaseSyncConfigModal } from './components/SupabaseSyncConfigModal';
import {
  ShieldAlert,
  Radio,
  Layers,
  MapPin,
  Flame,
  Zap,
  Anchor,
  Compass
} from 'lucide-react';

export function App() {
  const [warnings, setWarnings] = useState<NavWarning[]>([]);
  const [rawMessages, setRawMessages] = useState<RawMessage[]>([]);
  const [spatialFeatures, setSpatialFeatures] = useState<SpatialFeature[]>([]);

  const [selectedWarning, setSelectedWarning] = useState<NavWarning | null>(null);
  const [activeNavarea, setActiveNavarea] = useState<NavareaRegion | 'ALL'>('ALL');
  const [detailModalWarning, setDetailModalWarning] = useState<NavWarning | null>(null);

  // Modals state
  const [isRunnerOpen, setIsRunnerOpen] = useState(false);
  const [isStudioOpen, setIsStudioOpen] = useState(false);
  const [isTestsOpen, setIsTestsOpen] = useState(false);
  const [isDatabaseOpen, setIsDatabaseOpen] = useState(false);

  // Sync execution history
  const [syncHistory, setSyncHistory] = useState<PipelineExecutionLog[]>([]);

  // Initialize seed data from persistent storage or default
  useEffect(() => {
    const savedWarnings = localStorage.getItem('HELM_NAV_WARNINGS');
    const savedMessages = localStorage.getItem('HELM_RAW_MESSAGES');

    if (savedWarnings && savedMessages) {
      try {
        const parsedW = JSON.parse(savedWarnings);
        const parsedM = JSON.parse(savedMessages);
        setWarnings(parsedW);
        setRawMessages(parsedM);
        return;
      } catch (e) {
        // Fallback to fresh seed
      }
    }

    const { warnings: initW, messages: initM, spatialFeatures: initS } = getInitialSeedData();
    setWarnings(initW);
    setRawMessages(initM);
    setSpatialFeatures(initS);

    localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(initW));
    localStorage.setItem('HELM_RAW_MESSAGES', JSON.stringify(initM));
  }, []);

  // Save to localStorage when state updates
  const updateDatabaseState = (newWarnings: NavWarning[], newMessages: RawMessage[]) => {
    setWarnings(newWarnings);
    setRawMessages(newMessages);
    localStorage.setItem('HELM_NAV_WARNINGS', JSON.stringify(newWarnings));
    localStorage.setItem('HELM_RAW_MESSAGES', JSON.stringify(newMessages));
  };

  const handleApplySyncResult = (
    newWarnings: NavWarning[],
    newMessages: RawMessage[],
    log: PipelineExecutionLog
  ) => {
    updateDatabaseState(newWarnings, newMessages);
    setSyncHistory((prev) => [log, ...prev]);
  };

  const handleAddCustomWarning = (warn: NavWarning, msg: RawMessage) => {
    // Check if already exists
    const existingIndex = warnings.findIndex((w) => w.warning_id === warn.warning_id);
    let nextWarnings: NavWarning[];
    if (existingIndex >= 0) {
      nextWarnings = [...warnings];
      nextWarnings[existingIndex] = warn;
    } else {
      nextWarnings = [warn, ...warnings];
    }

    const nextMessages = [msg, ...rawMessages.filter((m) => m.warning_id !== msg.warning_id)];
    updateDatabaseState(nextWarnings, nextMessages);
    setSelectedWarning(warn);
  };

  const activeRawMessage = detailModalWarning
    ? rawMessages.find((m) => m.warning_id === detailModalWarning.warning_id)
    : undefined;

  // Key metrics calculation
  const totalCount = warnings.length;
  const activeCount = warnings.filter((w) => w.status === 'active').length;
  const militaryCount = warnings.filter((w) => w.category === 'military' && w.status === 'active').length;
  const electronicCount = warnings.filter((w) => w.category === 'electronic' && w.status === 'active').length;
  const atonCount = warnings.filter((w) => w.category === 'aton' && w.status === 'active').length;
  const subseaCount = warnings.filter((w) => w.category === 'subsea' && w.status === 'active').length;

  return (
    <div className="flex flex-col h-screen w-screen bg-slate-950 text-slate-100 overflow-hidden font-sans">
      {/* Top Navbar */}
      <Navbar
        warnings={warnings}
        onOpenRunner={() => setIsRunnerOpen(true)}
        onOpenStudio={() => setIsStudioOpen(true)}
        onOpenTests={() => setIsTestsOpen(true)}
        onOpenDatabase={() => setIsDatabaseOpen(true)}
      />

      {/* Quick Summary Strip */}
      <div className="bg-slate-900/90 border-b border-slate-800 px-4 py-1.5 flex items-center justify-between text-xs overflow-x-auto gap-4 shrink-0">
        <div className="flex items-center gap-4 text-slate-300 shrink-0">
          <div className="flex items-center gap-1.5">
            <span className="text-slate-400">Total Active Bulletins:</span>
            <span className="font-mono font-bold text-cyan-400">{activeCount}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-rose-500"></span>
            <span className="text-slate-400">Military Ops:</span>
            <span className="font-mono font-semibold text-rose-300">{militaryCount}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-purple-400"></span>
            <span className="text-slate-400">GNSS / Jamming:</span>
            <span className="font-mono font-semibold text-purple-300">{electronicCount}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-amber-400"></span>
            <span className="text-slate-400">AtoN Outages:</span>
            <span className="font-mono font-semibold text-amber-300">{atonCount}</span>
          </div>
          <span className="text-slate-700">|</span>
          <div className="flex items-center gap-1.5">
            <span className="w-2 h-2 rounded-full bg-cyan-400"></span>
            <span className="text-slate-400">Subsea Work:</span>
            <span className="font-mono font-semibold text-cyan-300">{subseaCount}</span>
          </div>
        </div>

        <div className="flex items-center gap-2 text-[11px] text-slate-400 shrink-0">
          <span>Sources:</span>
          <span className="font-mono text-slate-300">SMA Baltic</span>
          <span className="text-slate-600">•</span>
          <span className="font-mono text-slate-300">UKHO Admiralty</span>
          <span className="text-slate-600">•</span>
          <span className="font-mono text-slate-300">JCG Kaiho</span>
        </div>
      </div>

      {/* Main Content Area: Split View */}
      <main className="flex-1 flex flex-col md:flex-row overflow-hidden p-2 gap-2">
        {/* Left: Interactive Nautical Leaflet Map */}
        <section className="flex-1 h-full min-h-[360px] relative rounded-xl overflow-hidden border border-slate-800 shadow-lg">
          <MaritimeMap
            warnings={warnings}
            selectedWarning={selectedWarning}
            onSelectWarning={(w) => {
              setSelectedWarning(w);
              setDetailModalWarning(w);
            }}
            activeNavarea={activeNavarea}
          />
        </section>

        {/* Right: Filterable Navigational Warnings List */}
        <aside className="w-full md:w-[460px] lg:w-[500px] h-full flex flex-col shrink-0">
          <WarningList
            warnings={warnings}
            selectedWarning={selectedWarning}
            onSelectWarning={(w) => setSelectedWarning(w)}
            activeNavarea={activeNavarea}
            onChangeNavarea={(nav) => setActiveNavarea(nav)}
            onOpenDetailModal={(w) => setDetailModalWarning(w)}
          />
        </aside>
      </main>

      {/* Modals */}
      <WarningDetailModal
        warning={detailModalWarning}
        rawMessage={activeRawMessage}
        onClose={() => setDetailModalWarning(null)}
      />

      <PipelineRunnerModal
        isOpen={isRunnerOpen}
        onClose={() => setIsRunnerOpen(false)}
        currentWarnings={warnings}
        currentMessages={rawMessages}
        onApplySyncResult={handleApplySyncResult}
        syncHistory={syncHistory}
      />

      <BulletinParserStudio
        isOpen={isStudioOpen}
        onClose={() => setIsStudioOpen(false)}
        onAddParsedWarning={handleAddCustomWarning}
      />

      <TestSuiteRunnerModal
        isOpen={isTestsOpen}
        onClose={() => setIsTestsOpen(false)}
      />

      <SupabaseSyncConfigModal
        isOpen={isDatabaseOpen}
        onClose={() => setIsDatabaseOpen(false)}
        warnings={warnings}
        rawMessages={rawMessages}
      />
    </div>
  );
}

export default App;
