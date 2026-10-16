import React, { useState } from 'react';
import { NavWarning, RawMessage } from '../types/maritime';
import {
  X,
  Database,
  Key,
  Globe,
  ShieldCheck,
  Check,
  AlertCircle,
  Table,
  RefreshCw,
  ExternalLink
} from 'lucide-react';

interface SupabaseSyncConfigModalProps {
  isOpen: boolean;
  onClose: () => void;
  warnings: NavWarning[];
  rawMessages: RawMessage[];
}

export const SupabaseSyncConfigModal: React.FC<SupabaseSyncConfigModalProps> = ({
  isOpen,
  onClose,
  warnings,
  rawMessages
}) => {
  const [supabaseUrl, setSupabaseUrl] = useState(() => localStorage.getItem('HELM_SUPABASE_URL') || 'https://demo-helm-database.supabase.co');
  const [supabaseKey, setSupabaseKey] = useState(() => localStorage.getItem('HELM_SUPABASE_KEY') || 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.e30.demo_service_key');
  const [activeTable, setActiveTable] = useState<'nav_warnings' | 'raw_messages'>('nav_warnings');
  const [isSaved, setIsSaved] = useState(false);

  if (!isOpen) return null;

  const handleSave = () => {
    localStorage.setItem('HELM_SUPABASE_URL', supabaseUrl);
    localStorage.setItem('HELM_SUPABASE_KEY', supabaseKey);
    setIsSaved(true);
    setTimeout(() => setIsSaved(false), 2000);
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[92vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-950/80 rounded-lg border border-emerald-800/60 text-emerald-400">
              <Database className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                Supabase Differential Sync & Database Inspector
              </h2>
              <p className="text-xs text-slate-400">
                Target database tables: <span className="font-mono text-cyan-400">nav_warnings</span> (bulletins) & <span className="font-mono text-purple-400">raw_messages</span> (audit trail)
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Configuration Bar */}
        <div className="p-4 bg-slate-950 border-b border-slate-800 space-y-3">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs">
            <div>
              <label className="text-slate-400 block mb-1 flex items-center gap-1.5 font-medium">
                <Globe className="w-3.5 h-3.5 text-cyan-400" />
                SUPABASE_URL:
              </label>
              <input
                type="text"
                value={supabaseUrl}
                onChange={(e) => setSupabaseUrl(e.target.value)}
                className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-md text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                placeholder="https://your-project.supabase.co"
              />
            </div>
            <div>
              <label className="text-slate-400 block mb-1 flex items-center gap-1.5 font-medium">
                <Key className="w-3.5 h-3.5 text-emerald-400" />
                SUPABASE_KEY (Service / Anon Key):
              </label>
              <input
                type="password"
                value={supabaseKey}
                onChange={(e) => setSupabaseKey(e.target.value)}
                className="w-full px-3 py-1.5 bg-slate-900 border border-slate-700 rounded-md text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500"
                placeholder="eyJhbGciOi..."
              />
            </div>
          </div>

          <div className="flex items-center justify-between text-xs pt-1">
            <span className="text-slate-500">
              When missing or running in dev, the differential engine writes to local persistent state.
            </span>
            <button
              onClick={handleSave}
              className={`px-3 py-1 rounded text-xs font-medium transition flex items-center gap-1.5 ${
                isSaved ? 'bg-emerald-600 text-white' : 'bg-slate-800 hover:bg-slate-700 text-slate-200'
              }`}
            >
              {isSaved ? <Check className="w-3.5 h-3.5" /> : null}
              <span>{isSaved ? 'Configuration Saved' : 'Save Connection Details'}</span>
            </button>
          </div>
        </div>

        {/* Table Selector Tabs */}
        <div className="flex items-center justify-between px-4 py-2 bg-slate-900 border-b border-slate-800 text-xs">
          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTable('nav_warnings')}
              className={`px-3 py-1.5 rounded-lg font-medium transition flex items-center gap-1.5 ${
                activeTable === 'nav_warnings'
                  ? 'bg-cyan-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <Table className="w-3.5 h-3.5" />
              <span>nav_warnings ({warnings.length} rows)</span>
            </button>
            <button
              onClick={() => setActiveTable('raw_messages')}
              className={`px-3 py-1.5 rounded-lg font-medium transition flex items-center gap-1.5 ${
                activeTable === 'raw_messages'
                  ? 'bg-purple-600 text-white shadow-sm'
                  : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
              }`}
            >
              <Table className="w-3.5 h-3.5" />
              <span>raw_messages ({rawMessages.length} rows)</span>
            </button>
          </div>

          <span className="text-slate-500 text-[11px]">
            Primary Key: <strong className="font-mono text-slate-300">warning_id, source_id</strong>
          </span>
        </div>

        {/* Database Rows Table */}
        <div className="p-4 overflow-x-auto overflow-y-auto flex-1 text-xs">
          {activeTable === 'nav_warnings' ? (
            <table className="w-full text-left border-collapse font-mono text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 bg-slate-950">
                  <th className="p-2">warning_id</th>
                  <th className="p-2">source_id</th>
                  <th className="p-2">navarea</th>
                  <th className="p-2">category</th>
                  <th className="p-2">status</th>
                  <th className="p-2">lat</th>
                  <th className="p-2">lon</th>
                  <th className="p-2">title</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {warnings.map((w) => (
                  <tr key={w.warning_id} className="hover:bg-slate-800/40 text-slate-300">
                    <td className="p-2 text-cyan-300 font-bold">{w.warning_id}</td>
                    <td className="p-2 text-slate-400">{w.source_id}</td>
                    <td className="p-2">{w.navarea}</td>
                    <td className="p-2 text-amber-300 uppercase">{w.category}</td>
                    <td className="p-2">
                      <span className={w.status === 'active' ? 'text-emerald-400' : 'text-rose-400'}>
                        {w.status}
                      </span>
                    </td>
                    <td className="p-2 text-slate-400">{w.latitude?.toFixed(4) || '-'}</td>
                    <td className="p-2 text-slate-400">{w.longitude?.toFixed(4) || '-'}</td>
                    <td className="p-2 font-sans truncate max-w-xs text-slate-200">{w.title}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : (
            <table className="w-full text-left border-collapse font-mono text-[11px]">
              <thead>
                <tr className="border-b border-slate-800 text-slate-400 bg-slate-950">
                  <th className="p-2">warning_id</th>
                  <th className="p-2">source_id</th>
                  <th className="p-2">checksum_sha256</th>
                  <th className="p-2">received_timestamp</th>
                  <th className="p-2">subject_header</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800/60">
                {rawMessages.map((m, idx) => (
                  <tr key={`${m.warning_id}-${idx}`} className="hover:bg-slate-800/40 text-slate-300">
                    <td className="p-2 text-purple-300 font-bold">{m.warning_id}</td>
                    <td className="p-2 text-slate-400">{m.source_id}</td>
                    <td className="p-2 text-purple-400/90 truncate max-w-xs">
                      {m.checksum_sha256.slice(0, 20)}...
                    </td>
                    <td className="p-2 text-slate-400 truncate">{m.received_timestamp}</td>
                    <td className="p-2 font-sans truncate max-w-xs text-slate-200">
                      {m.subject_header}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400">
          <span>Differential sync uses checksum_sha256 to guarantee zero-duplication</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
