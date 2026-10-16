import React, { useState } from 'react';
import { NavWarning, RawMessage, HazardCategory } from '../types/maritime';
import { parseBalticWarning } from '../core/parsers/balticParser';
import { parseNavarea1Warning } from '../core/parsers/navarea1Parser';
import { parseNavareaXiWarning } from '../core/parsers/navareaXiParser';
import { getCategoryBadgeStyle, getHazardKeywords } from '../core/classification';
import {
  X,
  Sparkles,
  MapPin,
  Clock,
  Shield,
  Hash,
  Database,
  PlusCircle,
  FileText,
  Copy,
  Check
} from 'lucide-react';

interface BulletinParserStudioProps {
  isOpen: boolean;
  onClose: () => void;
  onAddParsedWarning: (warn: NavWarning, msg: RawMessage) => void;
}

const SAMPLE_TEMPLATES = [
  {
    name: 'Baltic Detonations (Polygon)',
    engine: 'baltic' as const,
    header: 'SWEDISH NAV WARN 199/26 [Skagerrak]',
    text: `150830 UTC OCT
SKAGERRAK. GULLMARNFJORDEN.
THE SWEDISH NAVY WILL CONDUCT LIVE DETONATIONS.
16 OCT 0800 LT - 18 OCT 1800 LT.
PSN:
58-15.0N 011-25.0E
58-18.0N 011-25.0E
58-18.0N 011-30.0E
58-15.0N 011-30.0E
SAFETY ZONE 1000 METRES.`
  },
  {
    name: 'NAVAREA I Cable Repair (LineString)',
    engine: 'navarea_1' as const,
    header: 'NAVAREA I 512/26',
    text: `121400 UTC OCT 2026
DOVER STRAIT.
SUBMARINE CABLE REPAIR BY C.S. SOVEREIGN.
PSN: 51-10.0N 001-40.0E TO 51-15.0N 001-55.0E
GUARD VESSELS PRESENT. PASS WITH SLOW SPEED.`
  },
  {
    name: 'NAVAREA XI Adrift Hazard (Point)',
    engine: 'navarea_xi' as const,
    header: 'NAVAREA XI NO.26-0812',
    text: `NO.26-0812       Date:2026/10/14 11 UTC
SOUTH CHINA SEA.
UNMANNED DRIFTING BARGE REPORTED.
PSN: 18-24.5N 114-12.8E
DANGEROUS TO NAVIGATION.`
  },
  {
    name: 'GNSS Jamming / Spoofing',
    engine: 'baltic' as const,
    header: 'BALTIC SEA NAV WARN 099/26 [Central Baltic]',
    text: `140900 UTC OCT
CENTRAL BALTIC.
GNSS, AIS AND RADAR INTERFERENCE OBSERVED IN AREA.
MARINERS ADVISED TO EXERCISE EXTREME CAUTION.`
  }
];

export const BulletinParserStudio: React.FC<BulletinParserStudioProps> = ({
  isOpen,
  onClose,
  onAddParsedWarning
}) => {
  const [engine, setEngine] = useState<'auto' | 'baltic' | 'navarea_1' | 'navarea_xi'>('auto');
  const [headerInput, setHeaderInput] = useState(SAMPLE_TEMPLATES[0].header);
  const [textInput, setTextInput] = useState(SAMPLE_TEMPLATES[0].text);
  const [copied, setCopied] = useState(false);
  const [addedSuccess, setAddedSuccess] = useState(false);

  if (!isOpen) return null;

  // Detect engine if auto
  const effectiveEngine =
    engine !== 'auto'
      ? engine
      : headerInput.includes('BALTIC') || headerInput.includes('SWEDISH')
      ? 'baltic'
      : headerInput.includes('NAVAREA I')
      ? 'navarea_1'
      : 'navarea_xi';

  // Execute parsing
  let parsedResult: {
    rawMessage: RawMessage;
    navWarning: NavWarning;
    spatial: any;
  } | null = null;

  try {
    if (effectiveEngine === 'baltic') {
      parsedResult = parseBalticWarning(textInput, headerInput);
    } else if (effectiveEngine === 'navarea_1') {
      parsedResult = parseNavarea1Warning(textInput, headerInput);
    } else {
      parsedResult = parseNavareaXiWarning(textInput, headerInput);
    }
  } catch (err) {
    parsedResult = null;
  }

  const handleApplyTemplate = (tpl: (typeof SAMPLE_TEMPLATES)[0]) => {
    setEngine(tpl.engine);
    setHeaderInput(tpl.header);
    setTextInput(tpl.text);
    setAddedSuccess(false);
  };

  const handleAddToMap = () => {
    if (!parsedResult) return;
    onAddParsedWarning(parsedResult.navWarning, parsedResult.rawMessage);
    setAddedSuccess(true);
    setTimeout(() => setAddedSuccess(false), 2500);
  };

  const badge = parsedResult ? getCategoryBadgeStyle(parsedResult.navWarning.category) : null;
  const keywords = parsedResult ? getHazardKeywords(parsedResult.navWarning.category) : [];

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-4xl rounded-xl shadow-2xl flex flex-col max-h-[92vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-purple-950/80 rounded-lg border border-purple-800/60 text-purple-400">
              <Sparkles className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100">
                Bulletin Parser & Coordinate Extractor Studio
              </h2>
              <p className="text-xs text-slate-400">
                Test deterministic parsing, coordinate extraction, and hazard classification on custom bulletins
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

        {/* Body */}
        <div className="p-5 overflow-y-auto grid grid-cols-1 lg:grid-cols-2 gap-5 flex-1">
          {/* Left Column: Input */}
          <div className="space-y-4 flex flex-col">
            {/* Quick Templates */}
            <div>
              <label className="text-xs font-semibold text-slate-300 block mb-1.5">
                Load Sample Maritime Bulletin:
              </label>
              <div className="flex flex-wrap gap-1.5">
                {SAMPLE_TEMPLATES.map((tpl) => (
                  <button
                    key={tpl.name}
                    onClick={() => handleApplyTemplate(tpl)}
                    className="px-2.5 py-1 text-xs rounded-md bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
                  >
                    {tpl.name}
                  </button>
                ))}
              </div>
            </div>

            {/* Parser Engine Selector */}
            <div className="flex items-center gap-3">
              <label className="text-xs font-semibold text-slate-300 shrink-0">Parser Algorithm:</label>
              <select
                value={engine}
                onChange={(e) => setEngine(e.target.value as any)}
                className="bg-slate-950 border border-slate-700 text-slate-200 rounded px-2.5 py-1.5 text-xs focus:outline-none focus:border-cyan-500 w-full"
              >
                <option value="auto">Auto-detect from Header / Text</option>
                <option value="baltic">Baltic Subarea (Swedish Maritime Admin)</option>
                <option value="navarea_1">NAVAREA I (UK Hydrographic Office)</option>
                <option value="navarea_xi">NAVAREA XI (Japan Coast Guard)</option>
              </select>
            </div>

            {/* Header Input */}
            <div>
              <label className="text-xs font-semibold text-slate-300 block mb-1">
                Reference Subject Header:
              </label>
              <input
                type="text"
                value={headerInput}
                onChange={(e) => setHeaderInput(e.target.value)}
                className="w-full px-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-cyan-300 focus:outline-none focus:border-cyan-500"
                placeholder="e.g. SWEDISH NAV WARN 168/26 [Skagerrak] or NAVAREA I 123/26"
              />
            </div>

            {/* Raw Block Textarea */}
            <div className="flex-1 flex flex-col">
              <label className="text-xs font-semibold text-slate-300 block mb-1">
                Raw Navigational Bulletin Text:
              </label>
              <textarea
                value={textInput}
                onChange={(e) => setTextInput(e.target.value)}
                rows={9}
                className="w-full flex-1 p-3 bg-slate-950 border border-slate-700 rounded-lg text-xs font-mono text-slate-200 focus:outline-none focus:border-cyan-500 leading-relaxed resize-none"
                placeholder="Paste raw bulletin content with coordinates (e.g. 58-10.2N 011-13.3E)..."
              />
            </div>
          </div>

          {/* Right Column: Output */}
          <div className="space-y-4 flex flex-col">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-300">
                Parsed Normalized Output:
              </span>
              {parsedResult && badge && (
                <span
                  className={`text-xs px-2.5 py-0.5 rounded-full border ${badge.badgeBg} ${badge.badgeText} ${badge.borderColor}`}
                >
                  {badge.label}
                </span>
              )}
            </div>

            {parsedResult ? (
              <div className="space-y-3 flex-1 flex flex-col">
                {/* ID & Title */}
                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 space-y-1">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 text-[11px]">Normalized Warning ID:</span>
                    <span className="font-mono text-cyan-400 font-bold text-xs">
                      {parsedResult.navWarning.warning_id}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 text-[11px]">Target NAVAREA:</span>
                    <span className="text-slate-300 text-xs font-medium">
                      NAVAREA {parsedResult.navWarning.navarea}
                    </span>
                  </div>
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 text-[11px]">Issued Timestamp:</span>
                    <span className="text-slate-300 text-xs font-mono">
                      {parsedResult.navWarning.issued_text || 'None detected'}
                    </span>
                  </div>
                  <div className="pt-1 border-t border-slate-800/60">
                    <span className="text-slate-500 text-[11px] block">Extracted Title:</span>
                    <span className="text-slate-200 text-xs font-medium line-clamp-2">
                      {parsedResult.navWarning.title}
                    </span>
                  </div>
                </div>

                {/* Coordinates & Geometry */}
                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
                  <div className="flex items-center justify-between text-xs">
                    <span className="text-slate-300 font-semibold flex items-center gap-1.5">
                      <MapPin className="w-3.5 h-3.5 text-cyan-400" />
                      Extracted Coordinates:
                    </span>
                    {parsedResult.spatial && (
                      <span className="px-1.5 py-0.5 rounded bg-slate-800 text-[10px] font-mono text-cyan-300 uppercase">
                        GeoJSON {parsedResult.spatial.type}
                      </span>
                    )}
                  </div>

                  <div className="font-mono text-xs text-slate-300 bg-slate-900 p-2 rounded border border-slate-800 break-all">
                    {parsedResult.navWarning.coordinates || 'No coordinates found in text'}
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-xs">
                    <div>
                      <span className="text-slate-500">Centroid Lat:</span>{' '}
                      <span className="font-mono text-slate-300">
                        {parsedResult.navWarning.latitude !== null
                          ? parsedResult.navWarning.latitude.toFixed(6)
                          : 'N/A'}
                      </span>
                    </div>
                    <div>
                      <span className="text-slate-500">Centroid Lon:</span>{' '}
                      <span className="font-mono text-slate-300">
                        {parsedResult.navWarning.longitude !== null
                          ? parsedResult.navWarning.longitude.toFixed(6)
                          : 'N/A'}
                      </span>
                    </div>
                  </div>
                </div>

                {/* Audit Checksum & Keywords */}
                <div className="p-3 bg-slate-950 rounded-lg border border-slate-800 space-y-1.5 text-xs">
                  <div className="flex items-center justify-between">
                    <span className="text-slate-500 flex items-center gap-1">
                      <Hash className="w-3 h-3 text-purple-400" />
                      SHA-256 Checksum:
                    </span>
                    <span className="font-mono text-[10px] text-purple-300 truncate max-w-[200px]">
                      {parsedResult.rawMessage.checksum_sha256}
                    </span>
                  </div>
                  <div>
                    <span className="text-slate-500">Trigger Keywords:</span>{' '}
                    <span className="text-slate-300 italic">
                      {keywords.length > 0 ? keywords.slice(0, 5).join(', ') : 'Default general fallback'}
                    </span>
                  </div>
                </div>

                {/* Add to Map Button */}
                <div className="pt-2">
                  <button
                    onClick={handleAddToMap}
                    className={`w-full py-2.5 px-4 rounded-lg text-xs font-semibold flex items-center justify-center gap-2 transition shadow-md ${
                      addedSuccess
                        ? 'bg-emerald-600 text-white'
                        : 'bg-cyan-600 hover:bg-cyan-500 text-white'
                    }`}
                  >
                    {addedSuccess ? (
                      <>
                        <Check className="w-4 h-4" />
                        <span>Added to Active Map & Database!</span>
                      </>
                    ) : (
                      <>
                        <PlusCircle className="w-4 h-4" />
                        <span>Add This Warning to Active Map & DB</span>
                      </>
                    )}
                  </button>
                </div>
              </div>
            ) : (
              <div className="p-8 text-center text-slate-500 flex-1 flex flex-col items-center justify-center bg-slate-950 rounded-lg border border-slate-800">
                <FileText className="w-8 h-8 text-slate-600 mb-2" />
                <p className="text-xs">Enter bulletin text to see real-time parsing.</p>
              </div>
            )}
          </div>
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400">
          <span>Deterministic parser adheres to IMO/IHO NAVAREA standardization guidelines</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition"
          >
            Close Studio
          </button>
        </div>
      </div>
    </div>
  );
};
