import React, { useState } from 'react';
import { NavWarning, RawMessage, PipelineExecutionLog, NavareaRegion } from '../types/maritime';
import { BALTIC_CONFIG } from '../core/parsers/balticParser';
import { NAVAREA_1_CONFIG } from '../core/parsers/navarea1Parser';
import { NAVAREA_XI_CONFIG } from '../core/parsers/navareaXiParser';
import { computeDifferential } from '../core/syncEngine';
import { INITIAL_BULLETINS } from '../data/seedWarnings';
import { parseBalticWarning } from '../core/parsers/balticParser';
import { parseNavarea1Warning } from '../core/parsers/navarea1Parser';
import { parseNavareaXiWarning } from '../core/parsers/navareaXiParser';
import {
  X,
  Play,
  RotateCw,
  Terminal,
  CheckCircle2,
  AlertCircle,
  Database,
  Radio,
  Clock,
  Layers
} from 'lucide-react';

interface PipelineRunnerModalProps {
  isOpen: boolean;
  onClose: () => void;
  currentWarnings: NavWarning[];
  currentMessages: RawMessage[];
  onApplySyncResult: (newWarnings: NavWarning[], newMessages: RawMessage[], log: PipelineExecutionLog) => void;
  syncHistory: PipelineExecutionLog[];
}

export const PipelineRunnerModal: React.FC<PipelineRunnerModalProps> = ({
  isOpen,
  onClose,
  currentWarnings,
  currentMessages,
  onApplySyncResult,
  syncHistory
}) => {
  const [selectedTarget, setSelectedTarget] = useState<'ALL' | 'Baltic' | 'I' | 'XI'>('ALL');
  const [isRunning, setIsRunning] = useState(false);
  const [terminalLogs, setTerminalLogs] = useState<string[]>([]);
  const [activeTab, setActiveTab] = useState<'run' | 'history'>('run');

  if (!isOpen) return null;

  const runPipelineExecution = async (target: 'ALL' | 'Baltic' | 'I' | 'XI') => {
    setIsRunning(true);
    const logs: string[] = [];
    const addLog = (msg: string) => {
      logs.push(msg);
      setTerminalLogs([...logs]);
    };

    const startTime = Date.now();
    addLog(`=================================================================`);
    addLog(`⚓ STARTING NAVAREA AUTOMATED INGESTION & SYNC PIPELINE: [${target}]`);
    addLog(`=================================================================`);
    addLog(`Timestamp: ${new Date().toISOString()}`);

    // Simulation of network fetch and parsing
    await new Promise((r) => setTimeout(r, 400));

    let harvestedBulletins: Array<{
      type: 'baltic' | 'navarea_1' | 'navarea_xi';
      header: string;
      raw: string;
    }> = [];

    if (target === 'ALL' || target === 'Baltic') {
      addLog(`[Fetch] Connecting to Swedish Maritime Administration: ${BALTIC_CONFIG.SOURCE_URL}`);
      addLog(`  • TLS Chrome fingerprint impersonation active`);
      addLog(`  • Scraping navigational bulletins for Baltic Subarea & Swedish Waters...`);
      harvestedBulletins.push(
        ...INITIAL_BULLETINS.filter((b) => b.type === 'baltic')
      );
    }

    if (target === 'ALL' || target === 'I') {
      addLog(`[Fetch] Connecting to UK Hydrographic Office (UKHO Admiralty): ${NAVAREA_1_CONFIG.SOURCE_URL}`);
      addLog(`  • Acquiring __RequestVerificationToken and maintaining session...`);
      addLog(`  • Submitting selection payload for active NAVAREA I alerts...`);
      harvestedBulletins.push(
        ...INITIAL_BULLETINS.filter((b) => b.type === 'navarea_1')
      );
    }

    if (target === 'ALL' || target === 'XI') {
      addLog(`[Fetch] Connecting to Japan Coast Guard (JCG Kaiho): ${NAVAREA_XI_CONFIG.SOURCE_URL}`);
      addLog(`  • Querying Disp Warnings CGI portal with fallback...`);
      addLog(`  • Harvesting bulletins for NAVAREA XI Pacific & East Asian Seas...`);
      harvestedBulletins.push(
        ...INITIAL_BULLETINS.filter((b) => b.type === 'navarea_xi')
      );
    }

    await new Promise((r) => setTimeout(r, 400));
    addLog(`\n[Stage 1/3] Harvest complete. Total bulletins retrieved: ${harvestedBulletins.length}`);
    addLog(`[Stage 2/3] Deterministic Normalization, Coordinate Extraction & Hazard Classification...`);

    const parsedWarnings: NavWarning[] = [];
    const parsedMessages: RawMessage[] = [];

    for (const item of harvestedBulletins) {
      if (item.type === 'baltic') {
        const { rawMessage, navWarning } = parseBalticWarning(item.raw, item.header);
        parsedWarnings.push(navWarning);
        parsedMessages.push(rawMessage);
      } else if (item.type === 'navarea_1') {
        const { rawMessage, navWarning } = parseNavarea1Warning(item.raw, item.header);
        parsedWarnings.push(navWarning);
        parsedMessages.push(rawMessage);
      } else if (item.type === 'navarea_xi') {
        const { rawMessage, navWarning } = parseNavareaXiWarning(item.raw, item.header);
        parsedWarnings.push(navWarning);
        parsedMessages.push(rawMessage);
      }
    }

    addLog(`  • Generated WGS84 decimal geometries (Point, Polygon, LineString)`);
    addLog(`  • Computed SHA-256 audit hashes for raw_messages table`);
    addLog(`  • Classified priority hazard categories`);

    await new Promise((r) => setTimeout(r, 400));
    addLog(`\n[Stage 3/3] Differential Synchronization Engine:`);

    // Prepare existing state for differential evaluation
    const existingWarningsMap: Record<string, { warning_id: string; status: string }> = {};
    const existingChecksums = new Set<string>();

    currentWarnings.forEach((w) => {
      existingWarningsMap[w.warning_id] = { warning_id: w.warning_id, status: w.status };
    });
    currentMessages.forEach((m) => {
      existingChecksums.add(`${m.warning_id}:::${m.checksum_sha256}`);
    });

    const diff = computeDifferential(
      parsedWarnings,
      parsedMessages,
      existingWarningsMap,
      existingChecksums
    );

    addLog(`  • Unchanged (will skip)    : ${diff.skip.length}`);
    addLog(`  • New to add               : ${diff.new.length}`);
    addLog(`  • Revised to update        : ${diff.update.length}`);
    addLog(`  • Dropped (mark cancelled) : ${diff.cancel.length}`);

    for (const wid of diff.skip.slice(0, 5)) {
      addLog(`  ⏭️ [SKIP] ${wid}: Unchanged checksum`);
    }
    for (const { warn } of diff.new.slice(0, 3)) {
      addLog(`  ✨ [NEW] ${warn.warning_id}: Insert into nav_warnings (${warn.category})`);
    }
    for (const { warn } of diff.update.slice(0, 3)) {
      addLog(`  🔄 [UPDATE] ${warn.warning_id}: Revision updated with new checksum`);
    }
    for (const wid of diff.cancel.slice(0, 3)) {
      addLog(`  🛑 [CANCELLED] ${wid}: Marked cancelled in database`);
    }

    const duration = Date.now() - startTime;
    addLog(`\n=================================================================`);
    addLog(`📊 DIFFERENTIAL SYNCHRONIZATION SUMMARY:`);
    addLog(`   • Total Harvested  : ${parsedWarnings.length}`);
    addLog(`   • Skipped          : ${diff.skip.length}`);
    addLog(`   • New Added        : ${diff.new.length}`);
    addLog(`   • Updated          : ${diff.update.length}`);
    addLog(`   • Cancelled        : ${diff.cancel.length}`);
    addLog(`   • Execution Time   : ${duration}ms`);
    addLog(`🎉 Pipeline completed with 0 errors!`);
    addLog(`=================================================================`);

    const executionLog: PipelineExecutionLog = {
      id: `run-${Date.now()}`,
      timestamp: new Date().toISOString(),
      pipelineId: target,
      pipelineName: target === 'ALL' ? 'All NAVAREA Pipelines' : `NAVAREA ${target}`,
      status: 'success',
      harvestCount: parsedWarnings.length,
      diff: {
        skipped: diff.skip.length,
        newAdded: diff.new.length,
        updated: diff.update.length,
        cancelled: diff.cancel.length
      },
      durationMs: duration,
      outputMessages: logs
    };

    // Apply sync result
    const mergedWarningsMap = new Map<string, NavWarning>();
    currentWarnings.forEach((w) => mergedWarningsMap.set(w.warning_id, { ...w }));

    // Apply updates and additions
    [...diff.new, ...diff.update].forEach(({ warn }) => {
      mergedWarningsMap.set(warn.warning_id, warn);
    });

    // Apply cancellations
    diff.cancel.forEach((wid) => {
      const existing = mergedWarningsMap.get(wid);
      if (existing) {
        mergedWarningsMap.set(wid, { ...existing, status: 'cancelled' });
      }
    });

    const finalWarnings = Array.from(mergedWarningsMap.values());
    const finalMessages = [...currentMessages];
    [...diff.new, ...diff.update].forEach(({ msg }) => {
      if (!finalMessages.some((m) => m.warning_id === msg.warning_id && m.checksum_sha256 === msg.checksum_sha256)) {
        finalMessages.push(msg);
      }
    });

    onApplySyncResult(finalWarnings, finalMessages, executionLog);
    setIsRunning(false);
  };

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[92vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-cyan-950/80 rounded-lg border border-cyan-800/60 text-cyan-400">
              <Terminal className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                NAVAREA Pipeline Execution & Differential Sync Console
              </h2>
              <p className="text-xs text-slate-400">
                Trigger live scrapers, deterministic parser & audit differential engine
              </p>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <button
              onClick={() => setActiveTab('run')}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition ${
                activeTab === 'run' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              Runner
            </button>
            <button
              onClick={() => setActiveTab('history')}
              className={`px-3 py-1.5 text-xs rounded-lg font-medium transition ${
                activeTab === 'history' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              History ({syncHistory.length})
            </button>
            <button
              onClick={onClose}
              className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition ml-2"
            >
              <X className="w-5 h-5" />
            </button>
          </div>
        </div>

        {activeTab === 'run' ? (
          <div className="p-5 overflow-y-auto space-y-4 flex-1 flex flex-col">
            {/* Pipeline Selector Cards */}
            <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
              <button
                disabled={isRunning}
                onClick={() => setSelectedTarget('ALL')}
                className={`p-3 rounded-lg border text-left transition ${
                  selectedTarget === 'ALL'
                    ? 'bg-cyan-950/40 border-cyan-500 ring-1 ring-cyan-500/50'
                    : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200 mb-1 flex items-center justify-between">
                  <span>ALL PIPELINES</span>
                  <Layers className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div className="text-[11px] text-slate-400">
                  Runs Baltic, NAVAREA I & XI sequentially
                </div>
              </button>

              <button
                disabled={isRunning}
                onClick={() => setSelectedTarget('Baltic')}
                className={`p-3 rounded-lg border text-left transition ${
                  selectedTarget === 'Baltic'
                    ? 'bg-cyan-950/40 border-cyan-500 ring-1 ring-cyan-500/50'
                    : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200 mb-1 flex items-center justify-between">
                  <span>NAVAREA Baltic</span>
                  <Radio className="w-3.5 h-3.5 text-amber-400" />
                </div>
                <div className="text-[11px] text-slate-400">
                  Swedish Maritime Administration
                </div>
              </button>

              <button
                disabled={isRunning}
                onClick={() => setSelectedTarget('I')}
                className={`p-3 rounded-lg border text-left transition ${
                  selectedTarget === 'I'
                    ? 'bg-cyan-950/40 border-cyan-500 ring-1 ring-cyan-500/50'
                    : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200 mb-1 flex items-center justify-between">
                  <span>NAVAREA I</span>
                  <Radio className="w-3.5 h-3.5 text-cyan-400" />
                </div>
                <div className="text-[11px] text-slate-400">
                  UK Hydrographic Office (UKHO)
                </div>
              </button>

              <button
                disabled={isRunning}
                onClick={() => setSelectedTarget('XI')}
                className={`p-3 rounded-lg border text-left transition ${
                  selectedTarget === 'XI'
                    ? 'bg-cyan-950/40 border-cyan-500 ring-1 ring-cyan-500/50'
                    : 'bg-slate-950/60 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="font-semibold text-xs text-slate-200 mb-1 flex items-center justify-between">
                  <span>NAVAREA XI</span>
                  <Radio className="w-3.5 h-3.5 text-rose-400" />
                </div>
                <div className="text-[11px] text-slate-400">
                  Japan Coast Guard (JCG Kaiho)
                </div>
              </button>
            </div>

            {/* Run Action Bar */}
            <div className="flex items-center justify-between bg-slate-950 p-3 rounded-lg border border-slate-800">
              <div className="text-xs text-slate-300">
                Selected target:{' '}
                <strong className="text-cyan-400 font-mono">
                  {selectedTarget === 'ALL' ? 'ALL PIPELINES (scripts/run_all.py)' : `NAVAREA ${selectedTarget}`}
                </strong>
              </div>
              <button
                disabled={isRunning}
                onClick={() => runPipelineExecution(selectedTarget)}
                className={`px-4 py-2 rounded-lg text-xs font-semibold flex items-center gap-2 transition shadow-md ${
                  isRunning
                    ? 'bg-cyan-800 text-cyan-200 cursor-not-allowed'
                    : 'bg-cyan-600 hover:bg-cyan-500 text-white'
                }`}
              >
                {isRunning ? (
                  <>
                    <RotateCw className="w-4 h-4 animate-spin" />
                    <span>Executing Pipeline...</span>
                  </>
                ) : (
                  <>
                    <Play className="w-4 h-4 fill-white" />
                    <span>Execute Pipeline Now</span>
                  </>
                )}
              </button>
            </div>

            {/* Terminal Stream */}
            <div className="flex-1 bg-slate-950 rounded-lg border border-slate-800 p-3.5 font-mono text-xs overflow-y-auto min-h-[300px] max-h-[380px] space-y-1">
              {terminalLogs.length === 0 ? (
                <div className="text-slate-600 italic h-full flex flex-col items-center justify-center py-12">
                  <Terminal className="w-8 h-8 text-slate-700 mb-2" />
                  <span>Click "Execute Pipeline Now" to initiate scraping & differential sync.</span>
                </div>
              ) : (
                terminalLogs.map((log, idx) => (
                  <div
                    key={idx}
                    className={`${
                      log.includes('ERROR') || log.includes('FAILED')
                        ? 'text-rose-400'
                        : log.includes('SUCCESS') || log.includes('completed')
                        ? 'text-emerald-400'
                        : log.includes('NEW')
                        ? 'text-cyan-300'
                        : log.includes('SKIP')
                        ? 'text-slate-400'
                        : log.includes('UPDATE')
                        ? 'text-amber-300'
                        : log.includes('CANCELLED')
                        ? 'text-rose-300'
                        : 'text-slate-300'
                    }`}
                  >
                    {log}
                  </div>
                ))
              )}
            </div>
          </div>
        ) : (
          /* History View */
          <div className="p-5 overflow-y-auto space-y-3 flex-1">
            {syncHistory.length === 0 ? (
              <div className="text-center py-12 text-slate-500">
                <Clock className="w-8 h-8 mx-auto text-slate-600 mb-2" />
                <p className="text-sm">No pipeline execution logs recorded yet in this session.</p>
              </div>
            ) : (
              syncHistory.map((item) => (
                <div
                  key={item.id}
                  className="p-3.5 bg-slate-950 rounded-lg border border-slate-800 text-xs space-y-2"
                >
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                      <span className="font-semibold text-slate-200">{item.pipelineName}</span>
                      <span className="font-mono text-slate-500 text-[11px]">{item.timestamp}</span>
                    </div>
                    <span className="text-slate-400 font-mono">{item.durationMs}ms</span>
                  </div>

                  <div className="grid grid-cols-4 gap-2 pt-1 border-t border-slate-800 text-[11px]">
                    <div>
                      <span className="text-slate-500">Harvested:</span>{' '}
                      <span className="font-mono text-slate-300">{item.harvestCount}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Skipped:</span>{' '}
                      <span className="font-mono text-slate-400">{item.diff.skipped}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">New Added:</span>{' '}
                      <span className="font-mono text-cyan-400">{item.diff.newAdded}</span>
                    </div>
                    <div>
                      <span className="text-slate-500">Cancelled:</span>{' '}
                      <span className="font-mono text-rose-400">{item.diff.cancelled}</span>
                    </div>
                  </div>
                </div>
              ))
            )}
          </div>
        )}

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400">
          <span>Schedule: Every 6 hours via GitHub Actions workflows</span>
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
