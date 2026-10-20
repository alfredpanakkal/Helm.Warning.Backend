import React, { useState, useMemo } from 'react';
import { NavWarning, HazardCategory, NavareaRegion } from '../types/maritime';
import { getCategoryBadgeStyle, ALL_HAZARD_CATEGORIES } from '../core/classification';
import {
  Search,
  Filter,
  MapPin,
  Clock,
  Radio,
  FileText,
  Download,
  AlertTriangle,
  ChevronRight,
  ShieldAlert,
  SlidersHorizontal
} from 'lucide-react';

interface WarningListProps {
  warnings: NavWarning[];
  selectedWarning: NavWarning | null;
  onSelectWarning: (warning: NavWarning) => void;
  activeNavarea: NavareaRegion | 'ALL';
  onChangeNavarea: (navarea: NavareaRegion | 'ALL') => void;
  onOpenDetailModal: (warning: NavWarning) => void;
}

export const WarningList: React.FC<WarningListProps> = ({
  warnings,
  selectedWarning,
  onSelectWarning,
  activeNavarea,
  onChangeNavarea,
  onOpenDetailModal
}) => {
  const [searchQuery, setSearchQuery] = useState('');
  const [selectedCategories, setSelectedCategories] = useState<HazardCategory[]>([]);
  const [statusFilter, setStatusFilter] = useState<'ALL' | 'active' | 'cancelled'>('active');

  const toggleCategory = (cat: HazardCategory) => {
    setSelectedCategories((prev) =>
      prev.includes(cat) ? prev.filter((c) => c !== cat) : [...prev, cat]
    );
  };

  const clearCategories = () => {
    setSelectedCategories([]);
  };

  const filteredWarnings = useMemo(() => {
    return warnings.filter((item) => {
      // Region
      if (activeNavarea !== 'ALL' && item.navarea !== activeNavarea) return false;
      // Multi-Category Filter
      if (selectedCategories.length > 0) {
        const itemCats =
          item.categories && item.categories.length > 0
            ? item.categories
            : [item.category];
        const hasOverlap = itemCats.some((c) =>
          selectedCategories.includes(c as HazardCategory)
        );
        if (!hasOverlap) return false;
      }
      // Status
      if (statusFilter !== 'ALL' && item.status !== statusFilter) return false;
      // Search
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matchesId = item.warning_id.toLowerCase().includes(q);
        const matchesTitle = item.title.toLowerCase().includes(q);
        const matchesCoords = (item.coordinates || '').toLowerCase().includes(q);
        const matchesText = item.raw_text.toLowerCase().includes(q);
        if (!matchesId && !matchesTitle && !matchesCoords && !matchesText) {
          return false;
        }
      }
      return true;
    });
  }, [warnings, activeNavarea, selectedCategories, statusFilter, searchQuery]);

  const handleExportGeoJSON = () => {
    const features = filteredWarnings
      .filter((w) => w.spatial)
      .map((w) => ({
        type: 'Feature',
        geometry: w.spatial,
        properties: {
          warning_id: w.warning_id,
          canonical_id: w.canonical_id || w.warning_id,
          source_id: w.source_id,
          navarea: w.navarea,
          title: w.title,
          category: w.category,
          categories: w.categories || [w.category],
          status: w.status,
          issued_text: w.issued_text,
          coordinates: w.coordinates
        }
      }));

    const geoJsonDoc = {
      type: 'FeatureCollection',
      name: 'Helm_Navigational_Warnings',
      crs: { type: 'name', properties: { name: 'urn:ogc:def:crs:OGC:1.3:CRS84' } },
      features
    };

    const blob = new Blob([JSON.stringify(geoJsonDoc, null, 2)], { type: 'application/geo+json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `helm_warnings_${activeNavarea.toLowerCase()}_${new Date().toISOString().slice(0, 10)}.geojson`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleExportJson = () => {
    const blob = new Blob([JSON.stringify(filteredWarnings, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `nav_warnings_table_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-xl overflow-hidden shadow-xl">
      {/* Search and Main Filters */}
      <div className="p-3.5 border-b border-slate-800 bg-slate-900/80 space-y-3">
        {/* Top Search Bar */}
        <div className="relative">
          <Search className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="Search bulletins by ID, coordinates, keyword..."
            className="w-full pl-9 pr-3 py-1.5 bg-slate-950 border border-slate-700 rounded-lg text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:border-cyan-500 focus:ring-1 focus:ring-cyan-500"
          />
          {searchQuery && (
            <button
              onClick={() => setSearchQuery('')}
              className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-slate-400 hover:text-slate-200"
            >
              Clear
            </button>
          )}
        </div>

        {/* NAVAREA Region Pills */}
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1 text-xs">
          <button
            onClick={() => onChangeNavarea('ALL')}
            className={`px-3 py-1 rounded-md font-medium transition shrink-0 ${
              activeNavarea === 'ALL'
                ? 'bg-cyan-600 text-white shadow-sm'
                : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white'
            }`}
          >
            All NAVAREAs ({warnings.length})
          </button>
          <button
            onClick={() => onChangeNavarea('Baltic')}
            className={`px-3 py-1 rounded-md font-medium transition shrink-0 ${
              activeNavarea === 'Baltic'
                ? 'bg-cyan-600 text-white shadow-sm'
                : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white'
            }`}
          >
            Baltic ({warnings.filter((w) => w.navarea === 'Baltic').length})
          </button>
          <button
            onClick={() => onChangeNavarea('I')}
            className={`px-3 py-1 rounded-md font-medium transition shrink-0 ${
              activeNavarea === 'I'
                ? 'bg-cyan-600 text-white shadow-sm'
                : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white'
            }`}
          >
            NAVAREA I ({warnings.filter((w) => w.navarea === 'I').length})
          </button>
          <button
            onClick={() => onChangeNavarea('XI')}
            className={`px-3 py-1 rounded-md font-medium transition shrink-0 ${
              activeNavarea === 'XI'
                ? 'bg-cyan-600 text-white shadow-sm'
                : 'bg-slate-800/80 text-slate-300 hover:bg-slate-700 hover:text-white'
            }`}
          >
            NAVAREA XI ({warnings.filter((w) => w.navarea === 'XI').length})
          </button>
        </div>

        {/* Multi-Select Hazard Category Filter Bar */}
        <div className="space-y-1.5 pt-0.5">
          <div className="flex items-center justify-between text-[11px] text-slate-400">
            <span className="flex items-center gap-1 font-medium text-slate-300">
              <SlidersHorizontal className="w-3.5 h-3.5 text-cyan-400" />
              <span>Filter by Hazard Category</span>
              {selectedCategories.length > 0 && (
                <span className="text-cyan-400 text-[10px]">({selectedCategories.length} selected)</span>
              )}
            </span>
            <div className="flex items-center gap-2">
              {selectedCategories.length > 0 && (
                <button
                  onClick={clearCategories}
                  className="text-cyan-400 hover:text-cyan-300 transition text-[11px] underline"
                >
                  Reset
                </button>
              )}
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value as any)}
                className="bg-slate-950 border border-slate-700 text-slate-200 rounded px-2 py-0.5 text-xs focus:outline-none focus:border-cyan-500"
              >
                <option value="ALL">All Status</option>
                <option value="active">Active Only</option>
                <option value="cancelled">Cancelled</option>
              </select>
            </div>
          </div>

          <div className="flex items-center gap-1.5 flex-wrap">
            <button
              onClick={clearCategories}
              className={`px-2 py-0.5 rounded text-[11px] font-medium transition ${
                selectedCategories.length === 0
                  ? 'bg-cyan-600 text-white shadow-sm'
                  : 'bg-slate-950/80 text-slate-400 hover:text-slate-200 border border-slate-800'
              }`}
            >
              All Categories
            </button>
            {ALL_HAZARD_CATEGORIES.map((cat) => {
              const isSelected = selectedCategories.includes(cat);
              const badge = getCategoryBadgeStyle(cat);
              const count = warnings.filter((w) => {
                const cats = w.categories && w.categories.length > 0 ? w.categories : [w.category];
                return cats.includes(cat);
              }).length;

              return (
                <button
                  key={cat}
                  onClick={() => toggleCategory(cat)}
                  className={`px-2 py-0.5 rounded text-[11px] font-medium transition flex items-center gap-1 border ${
                    isSelected
                      ? `${badge.badgeBg} ${badge.badgeText} ${badge.borderColor} ring-1 ring-cyan-400/50 shadow-sm`
                      : 'bg-slate-950/80 text-slate-400 hover:text-slate-200 border-slate-800'
                  }`}
                >
                  <span>{badge.label}</span>
                  <span className="text-[10px] opacity-75 tabular-nums">({count})</span>
                </button>
              );
            })}
          </div>
        </div>

        {/* Action Row: Export Buttons */}
        <div className="flex items-center justify-between gap-2 pt-1 border-t border-slate-800/60 text-xs text-slate-400">
          <span className="text-[11px]">
            Showing <strong className="text-slate-200 font-semibold">{filteredWarnings.length}</strong> of{' '}
            {warnings.length} warnings
          </span>
          <div className="flex items-center gap-1">
            <button
              onClick={handleExportGeoJSON}
              title="Download filtered items as GeoJSON"
              className="px-2 py-1 rounded hover:bg-slate-800 text-slate-300 hover:text-cyan-400 border border-slate-800 flex items-center gap-1 text-[11px]"
            >
              <Download className="w-3 h-3" />
              <span>GeoJSON</span>
            </button>
            <button
              onClick={handleExportJson}
              title="Download table json"
              className="px-2 py-1 rounded hover:bg-slate-800 text-slate-300 hover:text-cyan-400 border border-slate-800 flex items-center gap-1 text-[11px]"
            >
              <FileText className="w-3 h-3" />
              <span>JSON</span>
            </button>
          </div>
        </div>
      </div>

      {/* Warning Cards List */}
      <div className="flex-1 overflow-y-auto p-2 space-y-2">
        {filteredWarnings.length === 0 ? (
          <div className="p-8 text-center text-slate-500 space-y-2">
            <AlertTriangle className="w-8 h-8 mx-auto text-slate-600" />
            <p className="text-sm font-medium">No navigational warnings match criteria</p>
            <p className="text-xs">Adjust your search term, NAVAREA region, or category filter.</p>
          </div>
        ) : (
          filteredWarnings.map((warning) => {
            const isSelected = selectedWarning?.warning_id === warning.warning_id;
            const itemCats: HazardCategory[] = (
              warning.categories && warning.categories.length > 0
                ? warning.categories
                : [warning.category]
            ) as HazardCategory[];

            return (
              <div
                key={warning.warning_id}
                onClick={() => {
                  onSelectWarning(warning);
                }}
                className={`group p-3 rounded-lg border transition cursor-pointer text-left ${
                  isSelected
                    ? 'bg-slate-800/95 border-cyan-500 shadow-md ring-1 ring-cyan-500/50'
                    : 'bg-slate-950/60 hover:bg-slate-800/50 border-slate-800/80 hover:border-slate-700'
                }`}
              >
                {/* Header: Warning ID + NAVAREA tag + Multi-Badge Categories */}
                <div className="flex items-start justify-between gap-2 mb-1.5 flex-wrap">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="font-mono font-bold text-sm text-cyan-300">
                      {warning.warning_id}
                    </span>
                    <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-slate-800 text-slate-300 border border-slate-700">
                      NAVAREA {warning.navarea}
                    </span>
                    {warning.status === 'cancelled' && (
                      <span className="text-[10px] font-medium px-1.5 py-0.5 rounded bg-rose-950/70 text-rose-300 border border-rose-800/50">
                        CANCELLED
                      </span>
                    )}
                  </div>

                  {/* Multi-Badge Row */}
                  <div className="flex items-center gap-1 flex-wrap justify-end">
                    {itemCats.map((cat, idx) => {
                      const badge = getCategoryBadgeStyle(cat);
                      return (
                        <span
                          key={`${warning.warning_id}-cat-${idx}`}
                          className={`text-[10px] font-medium px-2 py-0.5 rounded-md border ${badge.badgeBg} ${badge.badgeText} ${badge.borderColor}`}
                        >
                          {badge.label}
                        </span>
                      );
                    })}
                  </div>
                </div>

                {/* Title */}
                <div className="text-xs font-semibold text-slate-200 line-clamp-2 mb-2 leading-relaxed">
                  {warning.title}
                </div>

                {/* Details Footer: Coordinates, Issued, Geometry badge, Details btn */}
                <div className="flex items-center justify-between text-[11px] text-slate-400 pt-1.5 border-t border-slate-800/60">
                  <div className="flex items-center gap-3 truncate">
                    {warning.coordinates ? (
                      <span className="flex items-center gap-1 font-mono text-slate-300 truncate">
                        <MapPin className="w-3 h-3 text-cyan-400 shrink-0" />
                        <span className="truncate">{warning.coordinates}</span>
                      </span>
                    ) : (
                      <span className="text-slate-500 italic">No coordinates in text</span>
                    )}

                    {warning.issued_text && (
                      <span className="hidden sm:flex items-center gap-1 text-slate-400 shrink-0">
                        <Clock className="w-3 h-3 text-slate-500" />
                        <span>{warning.issued_text}</span>
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-1 shrink-0 ml-2">
                    {warning.spatial && (
                      <span className="text-[9px] px-1 py-0.2 rounded bg-slate-800 text-slate-400 uppercase font-mono">
                        {(warning.spatial as any)?.type || (warning.spatial as any)?.geometries?.[0]?.type || 'SPATIAL'}
                      </span>
                    )}
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        onOpenDetailModal(warning);
                      }}
                      className="p-1 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition"
                      title="Inspect Bulletin & Audit Record"
                    >
                      <ChevronRight className="w-4 h-4" />
                    </button>
                  </div>
                </div>
              </div>
            );
          })
        )}
      </div>

      {/* Footer Status Bar */}
      <div className="px-3 py-2 bg-slate-950 border-t border-slate-800 text-xs text-slate-400 flex items-center justify-between">
        <span>
          Showing <span className="text-cyan-400 font-mono font-medium">{filteredWarnings.length}</span> of {warnings.length} bulletins
        </span>
        <span className="text-slate-500 text-[11px]">Differential Sync Active</span>
      </div>
    </div>
  );
};
