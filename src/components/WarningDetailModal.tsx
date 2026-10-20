import React, { useState } from 'react';
import { NavWarning, RawMessage, HazardCategory } from '../types/maritime';
import { getCategoryBadgeStyle } from '../core/classification';
import {
  X,
  MapPin,
  Clock,
  Shield,
  FileCode,
  Hash,
  Database,
  Copy,
  Check,
  ExternalLink
} from 'lucide-react';

interface WarningDetailModalProps {
  warning: NavWarning | null;
  rawMessage?: RawMessage;
  onClose: () => void;
}

export const WarningDetailModal: React.FC<WarningDetailModalProps> = ({
  warning,
  rawMessage,
  onClose
}) => {
  const [copiedKey, setCopiedKey] = useState<string | null>(null);

  if (!warning) return null;

  const badge = getCategoryBadgeStyle(warning.category);

  const handleCopy = (text: string, key: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(key);
    setTimeout(() => setCopiedKey(null), 1800);
  };

  const geoJsonSnippet = warning.spatial ? JSON.stringify(warning.spatial, null, 2) : null;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/75 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-3xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/70 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <span className="font-mono font-bold text-lg text-cyan-400">
              {warning.warning_id}
            </span>
            <span className="text-xs px-2 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
              NAVAREA {warning.navarea}
            </span>
            <div className="flex items-center gap-1.5 flex-wrap">
              {((warning.categories && warning.categories.length > 0
                ? warning.categories
                : [warning.category]) as HazardCategory[]).map((cat, idx) => {
                const b = getCategoryBadgeStyle(cat);
                return (
                  <span
                    key={`${warning.warning_id}-modal-cat-${idx}`}
                    className={`text-xs px-2.5 py-0.5 rounded-md border ${b.badgeBg} ${b.badgeText} ${b.borderColor}`}
                  >
                    {b.label}
                  </span>
                );
              })}
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Modal Body */}
        <div className="p-6 overflow-y-auto space-y-6">
          {/* Title & Status */}
          <div>
            <h3 className="text-base font-semibold text-slate-100 mb-1">{warning.title}</h3>
            <div className="flex items-center gap-4 text-xs text-slate-400 flex-wrap">
              <span>
                Source Authority:{' '}
                <strong className="text-slate-300 font-medium">{warning.source_id}</strong>
              </span>
              <span>•</span>
              <span>
                Status:{' '}
                <strong
                  className={`uppercase ${warning.status === 'active' ? 'text-emerald-400' : 'text-rose-400'}`}
                >
                  {warning.status}
                </strong>
              </span>
              {warning.issued_text && (
                <>
                  <span>•</span>
                  <span>
                    Issued: <strong className="text-slate-300">{warning.issued_text}</strong>
                  </span>
                </>
              )}
            </div>
          </div>

          {/* Coordinate & Spatial Breakdown */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div className="p-3.5 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <MapPin className="w-3.5 h-3.5 text-cyan-400" />
                  WGS84 Coordinates
                </span>
                {warning.coordinates && (
                  <button
                    onClick={() => handleCopy(warning.coordinates || '', 'coords')}
                    className="text-[11px] text-slate-400 hover:text-cyan-400 flex items-center gap-1"
                  >
                    {copiedKey === 'coords' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedKey === 'coords' ? 'Copied' : 'Copy'}</span>
                  </button>
                )}
              </div>
              <div className="font-mono text-xs text-slate-300 bg-slate-900 p-2 rounded border border-slate-800 break-all">
                {warning.coordinates || 'No coordinates detected in bulletin'}
              </div>
              <div className="grid grid-cols-2 gap-2 text-xs">
                <div>
                  <span className="text-slate-500">Lat Decimal:</span>{' '}
                  <span className="font-mono text-slate-300">
                    {warning.latitude !== null ? warning.latitude.toFixed(6) : 'N/A'}
                  </span>
                </div>
                <div>
                  <span className="text-slate-500">Lon Decimal:</span>{' '}
                  <span className="font-mono text-slate-300">
                    {warning.longitude !== null ? warning.longitude.toFixed(6) : 'N/A'}
                  </span>
                </div>
              </div>
            </div>

            {/* Audit & Checksum Box */}
            <div className="p-3.5 bg-slate-950 rounded-lg border border-slate-800 space-y-2">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Hash className="w-3.5 h-3.5 text-purple-400" />
                  SHA-256 Audit Integrity
                </span>
                {rawMessage?.checksum_sha256 && (
                  <button
                    onClick={() => handleCopy(rawMessage.checksum_sha256, 'checksum')}
                    className="text-[11px] text-slate-400 hover:text-purple-400 flex items-center gap-1"
                  >
                    {copiedKey === 'checksum' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                    <span>{copiedKey === 'checksum' ? 'Copied' : 'Copy'}</span>
                  </button>
                )}
              </div>
              <div className="font-mono text-[11px] text-slate-400 bg-slate-900 p-2 rounded border border-slate-800 break-all">
                {rawMessage?.checksum_sha256 || 'Calculated deterministically upon parse'}
              </div>
              <div className="text-xs text-slate-500">
                Received Timestamp:{' '}
                <span className="text-slate-300 font-mono">
                  {rawMessage?.received_timestamp || new Date().toISOString()}
                </span>
              </div>
            </div>
          </div>

          {/* Full Raw Message Text */}
          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                <FileCode className="w-3.5 h-3.5 text-cyan-400" />
                Raw Scraped Bulletin Block (raw_messages.full_raw_text)
              </span>
              <button
                onClick={() => handleCopy(warning.raw_text, 'raw')}
                className="text-xs text-slate-400 hover:text-cyan-400 flex items-center gap-1"
              >
                {copiedKey === 'raw' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                <span>{copiedKey === 'raw' ? 'Copied' : 'Copy Text'}</span>
              </button>
            </div>
            <pre className="p-3 bg-slate-950 text-slate-300 font-mono text-xs rounded-lg border border-slate-800 overflow-x-auto whitespace-pre-wrap leading-relaxed">
              {warning.raw_text}
            </pre>
          </div>

          {/* GeoJSON Geometry Object */}
          {geoJsonSnippet && (
            <div className="space-y-1.5">
              <div className="flex items-center justify-between">
                <span className="text-xs font-semibold text-slate-300 flex items-center gap-1.5">
                  <Database className="w-3.5 h-3.5 text-emerald-400" />
                  GeoJSON Geometry (spatial_features)
                </span>
                <button
                  onClick={() => handleCopy(geoJsonSnippet, 'geojson')}
                  className="text-xs text-slate-400 hover:text-emerald-400 flex items-center gap-1"
                >
                  {copiedKey === 'geojson' ? <Check className="w-3 h-3 text-emerald-400" /> : <Copy className="w-3 h-3" />}
                  <span>{copiedKey === 'geojson' ? 'Copied' : 'Copy GeoJSON'}</span>
                </button>
              </div>
              <pre className="p-3 bg-slate-950 text-emerald-400/90 font-mono text-xs rounded-lg border border-slate-800 overflow-x-auto">
                {geoJsonSnippet}
              </pre>
            </div>
          )}
        </div>

        {/* Modal Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/70 flex items-center justify-between">
          <div className="text-xs text-slate-500 font-mono">
            Table: <span className="text-slate-300">nav_warnings</span> & <span className="text-slate-300">raw_messages</span>
          </div>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition"
          >
            Close Inspector
          </button>
        </div>
      </div>
    </div>
  );
};
