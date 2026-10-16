import React, { useState, useEffect } from 'react';
import { NavWarning } from '../types/maritime';
import {
  Compass,
  Radio,
  Terminal,
  Sparkles,
  FlaskConical,
  Database,
  Clock,
  Layers,
  ShieldCheck,
  Activity
} from 'lucide-react';

interface NavbarProps {
  warnings: NavWarning[];
  onOpenRunner: () => void;
  onOpenStudio: () => void;
  onOpenTests: () => void;
  onOpenDatabase: () => void;
}

export const Navbar: React.FC<NavbarProps> = ({
  warnings,
  onOpenRunner,
  onOpenStudio,
  onOpenTests,
  onOpenDatabase
}) => {
  const [utcTime, setUtcTime] = useState('');
  const [localTime, setLocalTime] = useState('');

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setUtcTime(now.toUTCString().slice(17, 25) + ' UTC');
      setLocalTime(now.toLocaleTimeString([], { hour12: false }));
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  const activeWarningsCount = warnings.filter((w) => w.status === 'active').length;
  const militaryCount = warnings.filter((w) => w.category === 'military' && w.status === 'active').length;
  const atonCount = warnings.filter((w) => w.category === 'aton' && w.status === 'active').length;
  const electronicCount = warnings.filter((w) => w.category === 'electronic' && w.status === 'active').length;

  return (
    <header className="bg-slate-950 border-b border-slate-800 px-4 py-2.5 flex items-center justify-between gap-4 select-none shrink-0">
      {/* Brand & Station Header */}
      <div className="flex items-center gap-3">
        <div className="flex items-center gap-2.5">
          <div className="p-2 bg-gradient-to-br from-cyan-500 to-blue-600 rounded-lg shadow-md text-white">
            <Compass className="w-5 h-5 animate-spin" style={{ animationDuration: '30s' }} />
          </div>
          <div>
            <div className="flex items-center gap-2">
              <span className="font-bold tracking-wider text-base text-white font-mono">
                HELM
              </span>
              <span className="text-[11px] px-1.5 py-0.2 rounded bg-cyan-950 text-cyan-300 border border-cyan-800/60 font-mono">
                v2.0 REACT
              </span>
            </div>
            <div className="text-[11px] text-slate-400 font-medium">
              Consolidated NAVAREA Warning Operations (Baltic • NAVAREA I • NAVAREA XI)
            </div>
          </div>
        </div>

        {/* Live Station Status Badge */}
        <div className="hidden lg:flex items-center gap-2 ml-4 pl-4 border-l border-slate-800 text-xs">
          <span className="relative flex h-2 w-2">
            <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
            <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
          </span>
          <span className="text-slate-300 font-medium">Scrapers Operational</span>
          <span className="text-slate-600">•</span>
          <span className="text-slate-400 font-mono text-[11px]">Interval: 6H</span>
        </div>
      </div>

      {/* Center Clocks (UTC & Local) */}
      <div className="hidden md:flex items-center gap-4 px-3 py-1 bg-slate-900/90 rounded-lg border border-slate-800 text-xs font-mono">
        <div className="flex items-center gap-1.5 text-cyan-400">
          <Clock className="w-3.5 h-3.5" />
          <span className="font-bold">{utcTime || '00:00:00 UTC'}</span>
        </div>
        <span className="text-slate-700">|</span>
        <div className="flex items-center gap-1.5 text-slate-400">
          <span>LOC:</span>
          <span>{localTime || '00:00:00'}</span>
        </div>
      </div>

      {/* Right Controls & Quick Actions */}
      <div className="flex items-center gap-2">
        <button
          onClick={onOpenRunner}
          className="px-3 py-1.5 bg-cyan-600 hover:bg-cyan-500 text-white rounded-lg text-xs font-semibold flex items-center gap-1.5 transition shadow-sm"
          title="Run NAVAREA Ingestion & Sync Pipelines"
        >
          <Terminal className="w-3.5 h-3.5" />
          <span className="hidden sm:inline">Run Pipelines</span>
        </button>

        <button
          onClick={onOpenStudio}
          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition border border-slate-700"
          title="Open Custom Bulletin Parser Studio"
        >
          <Sparkles className="w-3.5 h-3.5 text-purple-400" />
          <span className="hidden sm:inline">Parser Studio</span>
        </button>

        <button
          onClick={onOpenTests}
          className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition border border-slate-700"
          title="Run Unit Test Suites"
        >
          <FlaskConical className="w-3.5 h-3.5 text-emerald-400" />
          <span className="hidden sm:inline">Test Suites</span>
        </button>

        <button
          onClick={onOpenDatabase}
          className="p-1.5 sm:px-3 sm:py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 rounded-lg text-xs font-semibold flex items-center gap-1.5 transition border border-slate-700"
          title="Supabase Database & Differential Sync Inspection"
        >
          <Database className="w-3.5 h-3.5 text-cyan-400" />
          <span className="hidden md:inline">Database</span>
        </button>
      </div>
    </header>
  );
};
