import React, { useState, useEffect, useRef, useMemo } from 'react';
import L from 'leaflet';
import { NavWarning, RawMessage, SpatialCircle, SpatialCorridor, DriftVector } from '../../types/maritime';
import {
  computeDistanceNm,
  computePolygonAreaSqNm,
  computeLineCorridor,
  formatCoordinateString
} from '../../core/coordinates';

interface PublicPortalProps {
  warnings: NavWarning[];
  rawMessages: RawMessage[];
  activeTab: 'map' | 'data' | 'sources';
  onSwitchTab: (tab: 'map' | 'data' | 'sources') => void;
  onRefreshData: () => void;
}

type PlotFilterType = 'all' | 'polygon' | 'circle' | 'line' | 'point' | 'corridor';

const NAVAREA_CENTERS: Record<string, { center: [number, number]; zoom: number }> = {
  'NA I': { center: [56.0, 3.0], zoom: 5 },
  'Baltic': { center: [58.5, 18.0], zoom: 5 },
  'NA II': { center: [28.0, -15.0], zoom: 4 },
  'NA III': { center: [36.0, 15.0], zoom: 5 },
  'NA IV': { center: [28.0, -75.0], zoom: 4 },
  'NA V': { center: [-20.0, -35.0], zoom: 4 },
  'NA VI': { center: [-45.0, -55.0], zoom: 4 },
  'NA VII': { center: [-35.0, 25.0], zoom: 4 },
  'NA VIII': { center: [10.0, 75.0], zoom: 4 },
  'NA IX': { center: [23.0, 58.0], zoom: 5 },
  'NA X': { center: [-22.0, 135.0], zoom: 4 },
  'NA XI': { center: [25.0, 130.0], zoom: 4 },
  'NA XII': { center: [20.0, -120.0], zoom: 4 },
  'NA XIII': { center: [50.0, 150.0], zoom: 4 },
  'NA XIV': { center: [-40.0, 175.0], zoom: 4 },
  'NA XV': { center: [-33.0, -80.0], zoom: 4 },
  'NA XVI': { center: [-10.0, -85.0], zoom: 4 },
  'NA XVII': { center: [72.0, -135.0], zoom: 3 },
  'NA XVIII': { center: [72.0, -75.0], zoom: 3 },
  'NA XIX': { center: [70.0, 15.0], zoom: 4 },
  'NA XX': { center: [75.0, 75.0], zoom: 3 },
  'NA XXI': { center: [75.0, 150.0], zoom: 3 }
};

const BASE_MAPS: Record<string, { name: string; url: string; maxZoom: number; attribution: string }> = {
  'carto-voyager': {
    name: 'CARTO Voyager',
    url: 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png',
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors · CARTO · OpenSeaMap'
  },
  'carto-dark': {
    name: 'CARTO Dark Matter',
    url: 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png',
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors · CARTO · OpenSeaMap'
  },
  'carto-positron': {
    name: 'CARTO Positron',
    url: 'https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png',
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors · CARTO · OpenSeaMap'
  },
  'osm': {
    name: 'OpenStreetMap',
    url: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
    maxZoom: 19,
    attribution: '© OpenStreetMap contributors · OpenSeaMap'
  },
  'esri-ocean': {
    name: 'ESRI Ocean Base',
    url: 'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Base/MapServer/tile/{z}/{y}/{x}',
    maxZoom: 13,
    attribution: 'Tiles © Esri — GEBCO, NOAA · OpenSeaMap'
  }
};

const SOURCES_LIST = [
  { region: 'I', name: 'UK Hydrographic Office', url: 'msi.admiralty.co.uk', count: 4, verified: true },
  { region: 'Baltic', name: 'Swedish Maritime Admin', url: 'sjofartsverket.se', count: 2, verified: true },
  { region: 'II', name: 'SHOM (France)', url: 'diffusion.shom.fr', count: 3, verified: true },
  { region: 'III', name: 'IHM (Spain)', url: 'armada.defensa.gob.es', count: 3, verified: true },
  { region: 'IV, XII', name: 'NGA (USA)', url: 'msi.nga.mil', count: 5, verified: true },
  { region: 'V', name: 'CHM (Brazil)', url: 'marinha.mil.br', count: 2, verified: false },
  { region: 'VI', name: 'SHN (Argentina)', url: 'hidro.gov.ar', count: 1, verified: false },
  { region: 'VII', name: 'SANHO (South Africa)', url: 'sanho.co.za', count: 2, verified: true },
  { region: 'VIII', name: 'INHO (India)', url: 'hydrobharat.gov.in', count: 3, verified: true },
  { region: 'IX', name: 'Pakistan Hydro Dept', url: 'hydrography.paknavy.gov.pk', count: 2, verified: true },
  { region: 'X', name: 'AMSA (Australia)', url: 'amsa.gov.au', count: 4, verified: true },
  { region: 'XI', name: 'Japan Coast Guard', url: 'kaiho.mlit.go.jp', count: 3, verified: true },
  { region: 'XIV', name: 'Maritime New Zealand', url: 'maritimenz.govt.nz', count: 2, verified: true },
  { region: 'XV', name: 'SHOA (Chile)', url: 'shoa.cl', count: 2, verified: false }
];

function matchesNavArea(warnArea: string | undefined, targetArea: string): boolean {
  if (!targetArea) return true;
  if (!warnArea) return false;
  const normWarn = String(warnArea).trim().toUpperCase().replace(/^NAVAREA\s+/, '').replace(/^NA\s+/, '');
  const normTarget = String(targetArea).trim().toUpperCase().replace(/^NAVAREA\s+/, '').replace(/^NA\s+/, '');
  return normWarn === normTarget;
}

function formatDate(w: NavWarning): string {
  const val = w.issued_date || w.issued_text || w.created_at;
  if (!val) return 'N/A';
  if (val.includes('T')) {
    try {
      return val.split('T')[0];
    } catch {
      return val;
    }
  }
  return val;
}

// Helper to determine what plot types a warning contains
function detectPlotTypes(warning: NavWarning): PlotFilterType[] {
  const types: PlotFilterType[] = [];
  const spatialAny = warning.spatial as any;
  const geometries: any[] = spatialAny?.type ? [spatialAny] : spatialAny?.geometries || [];
  const circles: any[] = spatialAny?.circles || [];
  const corridors: any[] = spatialAny?.corridors || [];

  if (circles.length > 0) types.push('circle');
  if (corridors.length > 0) types.push('corridor', 'line');

  geometries.forEach((g) => {
    if (g.type === 'Polygon') types.push('polygon');
    else if (g.type === 'LineString') types.push('line');
    else if (g.type === 'Point') types.push('point');
  });

  if (types.length === 0 && warning.latitude !== null && warning.longitude !== null) {
    types.push('point');
  }

  // Also check raw text directives
  const raw = warning.raw_text || '';
  if (/clearance|safety\s+zone|radius\s+of/i.test(raw) && !types.includes('circle')) {
    types.push('circle');
  }
  if (/towing|cable|pipeline|seismic/i.test(raw) && !types.includes('line')) {
    types.push('line');
  }

  return Array.from(new Set(types));
}

export const PublicPortal: React.FC<PublicPortalProps> = ({
  warnings,
  activeTab,
  onSwitchTab,
  onRefreshData
}) => {
  // NavArea Selection
  const [selectedNavArea, setSelectedNavArea] = useState<string>('NA I');

  // Plot Type Filter state
  const [activePlotType, setActivePlotType] = useState<PlotFilterType>('all');

  // Search & Filter
  const [searchQuery, setSearchQuery] = useState('');
  const [showAdvancedFilters, setShowAdvancedFilters] = useState(false);
  const [filterNavArea, setFilterNavArea] = useState<string>('');
  const [filterSeverity, setFilterSeverity] = useState<string>('');
  const [filterCategory, setFilterCategory] = useState<string>('');

  // Map state
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const baseLayerRef = useRef<L.TileLayer | null>(null);
  const seamarksLayerRef = useRef<L.TileLayer | null>(null);
  const soundingsLayerRef = useRef<L.TileLayer | null>(null);

  // Layer groups for various types of plots
  const polygonsLayerRef = useRef<L.LayerGroup | null>(null);
  const circlesLayerRef = useRef<L.LayerGroup | null>(null);
  const linesLayerRef = useRef<L.LayerGroup | null>(null);
  const pointsLayerRef = useRef<L.LayerGroup | null>(null);
  const verticesLayerRef = useRef<L.LayerGroup | null>(null);

  const [baseMapKey, setBaseMapKey] = useState<string>('carto-voyager');
  const [showPolygons, setShowPolygons] = useState(true);
  const [showCircles, setShowCircles] = useState(true);
  const [showLines, setShowLines] = useState(true);
  const [showPoints, setShowPoints] = useState(true);
  const [showVertices, setShowVertices] = useState(true);
  const [showSeamarks, setShowSeamarks] = useState(true);
  const [showSoundings, setShowSoundings] = useState(false);

  // Floating list
  const [isWarningListMinimized, setIsWarningListMinimized] = useState(false);
  const [isWarningListMaximized, setIsWarningListMaximized] = useState(false);
  const [expandedWarningId, setExpandedWarningId] = useState<string | null>(null);

  // Table expanded detail row
  const [expandedTableId, setExpandedTableId] = useState<string | null>(null);

  // Detail Modal
  const [modalWarning, setModalWarning] = useState<NavWarning | null>(null);

  // Filtered warnings for the Map View
  const mapWarnings = useMemo(() => {
    return warnings.filter((w) => {
      if (w.status === 'rejected') return false;
      if (!matchesNavArea(w.navarea, selectedNavArea)) return false;
      if (activePlotType !== 'all') {
        const types = detectPlotTypes(w);
        if (!types.includes(activePlotType)) return false;
      }
      return true;
    });
  }, [warnings, selectedNavArea, activePlotType]);

  // Counts by plot type for active NavArea
  const plotTypeCounts = useMemo(() => {
    const areaWarnings = warnings.filter((w) => w.status !== 'rejected' && matchesNavArea(w.navarea, selectedNavArea));
    let poly = 0;
    let circ = 0;
    let line = 0;
    let pt = 0;

    areaWarnings.forEach((w) => {
      const types = detectPlotTypes(w);
      if (types.includes('polygon')) poly++;
      if (types.includes('circle')) circ++;
      if (types.includes('line') || types.includes('corridor')) line++;
      if (types.includes('point')) pt++;
    });

    return {
      all: areaWarnings.length,
      polygon: poly,
      circle: circ,
      line,
      point: pt
    };
  }, [warnings, selectedNavArea]);

  // Filtered warnings for Data Bank
  const tableWarnings = useMemo(() => {
    return warnings.filter((w) => {
      if (w.status === 'rejected') return false;
      if (filterNavArea && !matchesNavArea(w.navarea, filterNavArea)) return false;
      if (filterSeverity && (w.severity || 'high') !== filterSeverity) return false;
      if (filterCategory && (w.category || 'general') !== filterCategory) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const idMatch = (w.warning_id || '').toLowerCase().includes(q);
        const titleMatch = (w.title || '').toLowerCase().includes(q);
        const navMatch = (w.navarea || '').toLowerCase().includes(q);
        const textMatch = (w.raw_text || '').toLowerCase().includes(q);
        if (!idMatch && !titleMatch && !navMatch && !textMatch) return false;
      }
      return true;
    });
  }, [warnings, filterNavArea, filterSeverity, filterCategory, searchQuery]);

  // Statistics
  const activeCount = warnings.filter((w) => w.status === 'active').length;
  const uniqueNavareas = new Set(warnings.map((w) => w.navarea)).size;
  const highCount = warnings.filter(
    (w) => (w.severity === 'critical' || w.severity === 'high') && w.status !== 'rejected'
  ).length;

  // Initialize Leaflet Map
  useEffect(() => {
    if (!mapContainerRef.current) return;

    if (!mapInstanceRef.current) {
      const isMobile = window.innerWidth <= 768;
      const map = L.map(mapContainerRef.current, {
        center: [30, 0],
        zoom: isMobile ? 2 : 3,
        worldCopyJump: true,
        zoomControl: false,
        attributionControl: false
      });

      const baseDef = BASE_MAPS[baseMapKey] || BASE_MAPS['carto-voyager'];
      const baseLayer = L.tileLayer(baseDef.url, {
        maxZoom: baseDef.maxZoom,
        attribution: baseDef.attribution,
        subdomains: 'abcd'
      }).addTo(map);
      baseLayerRef.current = baseLayer;

      const seamarks = L.tileLayer('https://tiles.openseamap.org/seamark/{z}/{x}/{y}.png', {
        maxZoom: 18,
        opacity: 1.0
      });
      seamarks.on('tileerror', () => {});
      if (showSeamarks) seamarks.addTo(map);
      seamarksLayerRef.current = seamarks;

      // Create separate LayerGroups for different plot types
      polygonsLayerRef.current = L.layerGroup().addTo(map);
      circlesLayerRef.current = L.layerGroup().addTo(map);
      linesLayerRef.current = L.layerGroup().addTo(map);
      pointsLayerRef.current = L.layerGroup().addTo(map);
      verticesLayerRef.current = L.layerGroup().addTo(map);

      mapInstanceRef.current = map;
    }

    const handleResize = () => {
      mapInstanceRef.current?.invalidateSize();
    };
    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);

    const t = setTimeout(() => {
      mapInstanceRef.current?.invalidateSize();
    }, 150);

    return () => {
      clearTimeout(t);
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
    };
  }, []);

  // Invalidate map size on tab switch
  useEffect(() => {
    if (activeTab === 'map') {
      setTimeout(() => {
        mapInstanceRef.current?.invalidateSize();
      }, 100);
    }
  }, [activeTab]);

  // Base map changes
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    const def = BASE_MAPS[baseMapKey] || BASE_MAPS['carto-voyager'];

    if (baseLayerRef.current) {
      map.removeLayer(baseLayerRef.current);
    }
    const newBase = L.tileLayer(def.url, {
      maxZoom: def.maxZoom,
      attribution: def.attribution,
      subdomains: 'abcd'
    }).addTo(map);
    newBase.bringToBack();
    baseLayerRef.current = newBase;
  }, [baseMapKey]);

  // Seamarks overlay
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !seamarksLayerRef.current) return;
    if (showSeamarks) {
      if (!map.hasLayer(seamarksLayerRef.current)) map.addLayer(seamarksLayerRef.current);
    } else {
      if (map.hasLayer(seamarksLayerRef.current)) map.removeLayer(seamarksLayerRef.current);
    }
  }, [showSeamarks]);

  // Soundings overlay
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (showSoundings) {
      if (!soundingsLayerRef.current) {
        soundingsLayerRef.current = L.tileLayer(
          'https://server.arcgisonline.com/ArcGIS/rest/services/Ocean/World_Ocean_Reference/MapServer/tile/{z}/{y}/{x}',
          { maxZoom: 13 }
        );
      }
      soundingsLayerRef.current.addTo(map);
    } else if (soundingsLayerRef.current && map.hasLayer(soundingsLayerRef.current)) {
      map.removeLayer(soundingsLayerRef.current);
    }
  }, [showSoundings]);

  // LayerGroup visibility sync
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (polygonsLayerRef.current) showPolygons ? map.addLayer(polygonsLayerRef.current) : map.removeLayer(polygonsLayerRef.current);
    if (circlesLayerRef.current) showCircles ? map.addLayer(circlesLayerRef.current) : map.removeLayer(circlesLayerRef.current);
    if (linesLayerRef.current) showLines ? map.addLayer(linesLayerRef.current) : map.removeLayer(linesLayerRef.current);
    if (pointsLayerRef.current) showPoints ? map.addLayer(pointsLayerRef.current) : map.removeLayer(pointsLayerRef.current);
    if (verticesLayerRef.current) showVertices ? map.addLayer(verticesLayerRef.current) : map.removeLayer(verticesLayerRef.current);
  }, [showPolygons, showCircles, showLines, showPoints, showVertices]);

  // ═════════════════════════════════════════════════════════════════════
  // ADVANCED MARITIME PLOTTER ENGINE
  // Plots: Polygons, Circles, LineStrings, Corridors, Vertices, and Custom Glyphs
  // ═════════════════════════════════════════════════════════════════════
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    // Clear all plot layers
    polygonsLayerRef.current?.clearLayers();
    circlesLayerRef.current?.clearLayers();
    linesLayerRef.current?.clearLayers();
    pointsLayerRef.current?.clearLayers();
    verticesLayerRef.current?.clearLayers();

    const bounds: L.LatLng[] = [];

    const handleShapeSelect = (warningId: string) => {
      setExpandedWarningId(warningId);
      setIsWarningListMinimized(false);
      setTimeout(() => {
        const el = document.getElementById(`warning-item-${warningId}`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }
      }, 100);
    };

    (window as any).locateOnMapById = (warnId: string) => {
      handleShapeSelect(warnId);
    };

    mapWarnings.forEach((warning) => {
      const isSelected = expandedWarningId === warning.warning_id;
      const isCritical = warning.severity === 'critical';
      const isHigh = warning.severity === 'high';
      const color = isCritical ? '#dc2626' : isHigh ? '#ea580c' : '#0d9488';

      const spatialAny = warning.spatial as any;
      const geometries: any[] = spatialAny?.type ? [spatialAny] : spatialAny?.geometries || [];
      const circles: SpatialCircle[] = spatialAny?.circles || [];
      const corridors: SpatialCorridor[] = spatialAny?.corridors || [];
      const driftVectors: DriftVector[] = spatialAny?.driftVectors || [];

      let hasPlottedShape = false;

      // Popup Content Template
      const createPopupHtml = (plotName: string, plotMetrics?: string) => `
        <div style="font-family:system-ui;font-size:13px;color:var(--text);min-width:210px;line-height:1.4">
          <div style="display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid #e2e8f0;padding-bottom:5px;margin-bottom:6px">
            <span style="font-weight:700;color:var(--surface-dark)">${warning.warning_id}</span>
            <span style="font-size:11px;font-weight:600;padding:1px 6px;border-radius:4px;background:#f1f5f9;color:#475569">${warning.navarea}</span>
          </div>
          <div style="font-weight:600;font-size:12px;margin-bottom:4px;color:var(--text)">${warning.title}</div>
          <div style="font-size:11px;color:var(--text-muted);display:flex;align-items:center;gap:6px;margin-bottom:6px">
            <span style="display:inline-block;width:6px;height:6px;border-radius:50%;background:${color}"></span>
            <span style="font-weight:600;text-transform:uppercase">${plotName}</span>
          </div>
          ${plotMetrics ? `<div style="font-size:11px;color:#0d9488;font-weight:600;font-family:ui-monospace,monospace;margin-bottom:6px">${plotMetrics}</div>` : ''}
          ${warning.coordinates ? `<div style="font-family:ui-monospace,monospace;font-size:11px;background:#fafafa;border:1px solid #e2e8f0;padding:4px 6px;border-radius:4px;color:#334155;margin-bottom:6px">${warning.coordinates}</div>` : ''}
          <div style="display:flex;justify-content:flex-end">
            <button type="button" class="btn btn-sm btn-primary" style="font-size:11px;padding:3px 8px;min-height:26px" onclick="window.locateOnMapById('${encodeURIComponent(warning.warning_id)}')">
              View Full Bulletin
            </button>
          </div>
        </div>
      `;

      // ─── 1. PLOT POLYGONS (Firing Ranges, Military Danger Areas) ───
      geometries
        .filter((g) => g.type === 'Polygon')
        .forEach((geom) => {
          hasPlottedShape = true;
          const rings = geom.coordinates || [];
          if (!rings[0]) return;

          const latLngs = rings[0].map((pt: [number, number]) => L.latLng(pt[1], pt[0]));
          latLngs.forEach((ll: L.LatLng) => bounds.push(ll));

          const areaSqNm = computePolygonAreaSqNm(rings[0]);
          const polygon = L.polygon(latLngs, {
            color: isSelected ? '#0f172a' : color,
            weight: isSelected ? 3 : 2,
            opacity: 0.95,
            fillColor: color,
            fillOpacity: isSelected ? 0.35 : 0.2,
            dashArray: warning.category === 'military' ? '6, 6' : undefined
          });

          polygon.bindPopup(createPopupHtml('Polygon Danger Area', `Area: ~${areaSqNm} sq NM`));
          polygon.on('click', () => handleShapeSelect(warning.warning_id));
          polygonsLayerRef.current?.addLayer(polygon);

          // Plot Interactive Corner Vertex Pins (V1, V2, V3...)
          rings[0].forEach((pt: [number, number], vIdx: number) => {
            if (vIdx === rings[0].length - 1 && rings[0].length > 3) return; // Skip closing duplicate
            const vLatLng = L.latLng(pt[1], pt[0]);
            const vertexMarker = L.marker(vLatLng, {
              icon: L.divIcon({
                className: 'vertex-pin-wrapper',
                html: `<div class="vertex-pin">${vIdx + 1}</div>`,
                iconSize: [20, 20],
                iconAnchor: [10, 10]
              })
            });
            const coordFmt = formatCoordinateString(pt[1], pt[0]);
            vertexMarker.bindTooltip(`Vertex ${vIdx + 1}: ${coordFmt}`);
            vertexMarker.on('click', () => handleShapeSelect(warning.warning_id));
            verticesLayerRef.current?.addLayer(vertexMarker);
          });

          // Plot Centroid Area Badge
          const center = polygon.getBounds().getCenter();
          const areaBadge = L.marker(center, {
            icon: L.divIcon({
              className: 'metric-pill-wrapper',
              html: `<div class="metric-pill-marker ${isCritical ? 'red' : 'amber'}">${warning.warning_id} · ${areaSqNm} sq NM</div>`,
              iconAnchor: [45, 12]
            })
          });
          polygonsLayerRef.current?.addLayer(areaBadge);
        });

      // ─── 2. PLOT CIRCLES & SAFETY CLEARANCE BUFFERS ───
      circles.forEach((c) => {
        hasPlottedShape = true;
        const centerLatLng = L.latLng(c.center[1], c.center[0]);
        bounds.push(centerLatLng);

        const radiusMeters = c.radius_nm * 1852;
        const circleLayer = L.circle(centerLatLng, {
          color: '#ea580c',
          weight: isSelected ? 3 : 2,
          opacity: 0.9,
          fillColor: '#f97316',
          fillOpacity: isSelected ? 0.28 : 0.15,
          dashArray: '5, 5',
          radius: radiusMeters
        });

        circleLayer.bindPopup(
          createPopupHtml('Circular Danger Zone', `Radius: ${c.radius_nm} NM (${Math.round(radiusMeters)}m)`)
        );
        circleLayer.on('click', () => handleShapeSelect(warning.warning_id));
        circlesLayerRef.current?.addLayer(circleLayer);

        // Center crosshair
        const centerMarker = L.circleMarker(centerLatLng, {
          radius: 3,
          color: '#ea580c',
          fillColor: '#ffffff',
          fillOpacity: 1,
          weight: 2
        });
        circlesLayerRef.current?.addLayer(centerMarker);

        // Radial measurement line and radius pill badge
        const edgeLat = centerLatLng.lat + (c.radius_nm / 60);
        const edgeLatLng = L.latLng(edgeLat, centerLatLng.lng);
        const radiusLine = L.polyline([centerLatLng, edgeLatLng], {
          color: '#ea580c',
          weight: 1.5,
          dashArray: '2, 3',
          opacity: 0.85
        });
        circlesLayerRef.current?.addLayer(radiusLine);

        const midRadial = L.latLng((centerLatLng.lat + edgeLat) / 2, centerLatLng.lng);
        const radiusPill = L.marker(midRadial, {
          icon: L.divIcon({
            className: 'metric-pill-wrapper',
            html: `<div class="metric-pill-marker amber">R: ${c.radius_nm} NM</div>`,
            iconAnchor: [30, 10]
          })
        });
        circlesLayerRef.current?.addLayer(radiusPill);
      });

      // ─── 3. PLOT LINESTRINGS & CABLES ───
      geometries
        .filter((g) => g.type === 'LineString')
        .forEach((geom) => {
          hasPlottedShape = true;
          const coords = geom.coordinates || [];
          if (coords.length < 2) return;

          const latLngs = coords.map((pt: [number, number]) => L.latLng(pt[1], pt[0]));
          latLngs.forEach((ll: L.LatLng) => bounds.push(ll));

          let totalDist = 0;
          for (let i = 0; i < coords.length - 1; i++) {
            totalDist += computeDistanceNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
          }

          // Casing glow line
          const glowLine = L.polyline(latLngs, {
            color: '#38bdf8',
            weight: isSelected ? 8 : 6,
            opacity: 0.35
          });
          linesLayerRef.current?.addLayer(glowLine);

          // Primary cable/track line
          const primaryLine = L.polyline(latLngs, {
            color: '#0284c7',
            weight: isSelected ? 4 : 3,
            opacity: 0.95,
            dashArray: '8, 6'
          });

          primaryLine.bindPopup(createPopupHtml('Subsea Cable / Track', `Length: ${Math.round(totalDist * 10) / 10} NM`));
          primaryLine.on('click', () => handleShapeSelect(warning.warning_id));
          linesLayerRef.current?.addLayer(primaryLine);

          // Terminus Endpoints
          const startMarker = L.circleMarker(latLngs[0], {
            radius: 5,
            fillColor: '#0284c7',
            color: '#ffffff',
            weight: 2,
            fillOpacity: 1
          }).bindTooltip('Point A (Terminus)');
          const endMarker = L.circleMarker(latLngs[latLngs.length - 1], {
            radius: 5,
            fillColor: '#0284c7',
            color: '#ffffff',
            weight: 2,
            fillOpacity: 1
          }).bindTooltip('Point B (Terminus)');
          linesLayerRef.current?.addLayer(startMarker);
          linesLayerRef.current?.addLayer(endMarker);
        });

      // ─── 4. PLOT CORRIDORS & WIDE BERTH SWATHS ───
      corridors.forEach((corr) => {
        hasPlottedShape = true;
        const polyPoints = corr.polygon || computeLineCorridor(corr.path, corr.width_nm);
        const latLngs = polyPoints.map((pt) => L.latLng(pt[1], pt[0]));
        latLngs.forEach((ll) => bounds.push(ll));

        const corridorPoly = L.polygon(latLngs, {
          color: '#ca8a04',
          weight: 2,
          opacity: 0.85,
          fillColor: '#f59e0b',
          fillOpacity: 0.16,
          dashArray: '5, 5'
        });

        corridorPoly.bindPopup(createPopupHtml('Survey Corridor', `Swath: ${corr.width_nm} NM Wide Berth`));
        corridorPoly.on('click', () => handleShapeSelect(warning.warning_id));
        linesLayerRef.current?.addLayer(corridorPoly);

        // Center line
        const centerLine = L.polyline(
          corr.path.map((pt) => L.latLng(pt[1], pt[0])),
          {
            color: '#ca8a04',
            weight: 2,
            dashArray: '4, 4',
            opacity: 0.9
          }
        );
        linesLayerRef.current?.addLayer(centerLine);

        // Midpoint badge
        if (corr.path.length >= 2) {
          const midPt = L.latLng(
            (corr.path[0][1] + corr.path[corr.path.length - 1][1]) / 2,
            (corr.path[0][0] + corr.path[corr.path.length - 1][0]) / 2
          );
          const corridorBadge = L.marker(midPt, {
            icon: L.divIcon({
              className: 'metric-pill-wrapper',
              html: `<div class="metric-pill-marker amber">${corr.width_nm} NM Swath</div>`,
              iconAnchor: [40, 10]
            })
          });
          linesLayerRef.current?.addLayer(corridorBadge);
        }
      });

      // ─── 5. PLOT DRIFT VECTORS ───
      driftVectors.forEach((dv) => {
        hasPlottedShape = true;
        const origLatLng = L.latLng(dv.origin[1], dv.origin[0]);
        bounds.push(origLatLng);

        // Project 12 NM drift along bearing
        const rad = (dv.bearing_deg * Math.PI) / 180;
        const distNm = 8;
        const targetLat = dv.origin[1] + (distNm / 60) * Math.cos(rad);
        const targetLon = dv.origin[0] + (distNm / (60 * Math.cos((dv.origin[1] * Math.PI) / 180))) * Math.sin(rad);
        const targetLatLng = L.latLng(targetLat, targetLon);

        const driftLine = L.polyline([origLatLng, targetLatLng], {
          color: '#ea580c',
          weight: 2.5,
          dashArray: '3, 4',
          opacity: 0.95
        });
        linesLayerRef.current?.addLayer(driftLine);

        const vectorHead = L.circleMarker(targetLatLng, {
          radius: 4,
          fillColor: '#ea580c',
          color: '#ffffff',
          weight: 1.5,
          fillOpacity: 1
        }).bindTooltip(`${dv.label || 'Drift Path'} (Heading ${dv.bearing_deg}°)`);
        linesLayerRef.current?.addLayer(vectorHead);
      });

      // ─── 6. PLOT POINT HAZARDS WITH CATEGORY-SPECIFIC NAUTICAL GLYPHS ───
      // If warning has no polygon/line or when point plotting is required
      if (!hasPlottedShape || warning.category === 'aton' || warning.category === 'offshore' || warning.category === 'drifting') {
        const lat = Number(warning.latitude);
        const lng = Number(warning.longitude);
        if (!isNaN(lat) && !isNaN(lng)) {
          const ptLatLng = L.latLng(lat, lng);
          bounds.push(ptLatLng);

          let glyphSvg = '';
          let glyphBg = color;

          if (warning.category === 'military') {
            // Firing target reticle
            glyphBg = '#dc2626';
            glyphSvg = `
              <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:#fff;stroke-width:2.2;fill:none">
                <circle cx="12" cy="12" r="8"/>
                <line x1="12" y1="2" x2="12" y2="7"/>
                <line x1="12" y1="17" x2="12" y2="22"/>
                <line x1="2" y1="12" x2="7" y2="12"/>
                <line x1="17" y1="12" x2="22" y2="12"/>
              </svg>
            `;
          } else if (warning.category === 'aton') {
            // Lighthouse / beacon light
            glyphBg = '#ea580c';
            glyphSvg = `
              <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:#fff;stroke-width:2;fill:none">
                <polygon points="12 2 15 21 9 21 12 2"/>
                <line x1="4" y1="10" x2="20" y2="10"/>
                <line x1="6" y1="15" x2="18" y2="15"/>
              </svg>
            `;
          } else if (warning.category === 'offshore') {
            // Oil platform / rig
            glyphBg = '#0d9488';
            glyphSvg = `
              <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:#fff;stroke-width:2;fill:none">
                <rect x="5" y="14" width="14" height="6" rx="1"/>
                <line x1="8" y1="14" x2="12" y2="4"/>
                <line x1="16" y1="14" x2="12" y2="4"/>
              </svg>
            `;
          } else if (warning.category === 'drifting') {
            // Floating container diamond
            glyphBg = '#f97316';
            glyphSvg = `
              <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:#fff;stroke-width:2;fill:none">
                <rect x="3" y="7" width="18" height="10" rx="2"/>
                <line x1="3" y1="12" x2="21" y2="12"/>
              </svg>
            `;
          } else {
            // Nautical alert point
            glyphBg = '#2563eb';
            glyphSvg = `
              <svg viewBox="0 0 24 24" style="width:16px;height:16px;stroke:#fff;stroke-width:2.5;fill:none">
                <line x1="12" y1="6" x2="12" y2="14"/>
                <circle cx="12" cy="18" r="1.5" fill="#fff"/>
              </svg>
            `;
          }

          const pointMarker = L.marker(ptLatLng, {
            icon: L.divIcon({
              className: 'nautical-marker-wrapper',
              html: `
                <div class="nautical-glyph-marker ${isSelected ? 'pulse' : ''}" style="background:${glyphBg};color:${glyphBg}">
                  ${glyphSvg}
                </div>
              `,
              iconSize: [32, 32],
              iconAnchor: [16, 16]
            })
          });

          pointMarker.bindPopup(createPopupHtml('Point Navigation Hazard'));
          pointMarker.on('click', () => handleShapeSelect(warning.warning_id));
          pointsLayerRef.current?.addLayer(pointMarker);
        }
      }
    });

    // Re-center if single or bounds available
    if (selectedNavArea && NAVAREA_CENTERS[selectedNavArea] && (!bounds.length || activePlotType !== 'all')) {
      const c = NAVAREA_CENTERS[selectedNavArea];
      map.setView(c.center, c.zoom, { animate: true });
    }
  }, [mapWarnings, showPolygons, showCircles, showLines, showPoints, showVertices, expandedWarningId]);

  const handleNavAreaChange = (area: string) => {
    setSelectedNavArea(area);
    const map = mapInstanceRef.current;
    if (map && NAVAREA_CENTERS[area]) {
      const c = NAVAREA_CENTERS[area];
      map.setView(c.center, c.zoom, { animate: true });
    }
  };

  const handleRecenter = () => {
    const map = mapInstanceRef.current;
    if (!map) return;
    if (selectedNavArea && NAVAREA_CENTERS[selectedNavArea]) {
      const c = NAVAREA_CENTERS[selectedNavArea];
      map.setView(c.center, c.zoom, { animate: true });
    } else {
      map.setView([30, 0], window.innerWidth <= 768 ? 2 : 3, { animate: true });
    }
  };

  const locateWarningOnMap = (warning: NavWarning) => {
    onSwitchTab('map');
    if (warning.navarea && !matchesNavArea(warning.navarea, selectedNavArea)) {
      setSelectedNavArea(warning.navarea);
    }
    setExpandedWarningId(warning.warning_id);
    setModalWarning(null);

    setTimeout(() => {
      const map = mapInstanceRef.current;
      if (!map) return;
      const lat = Number(warning.latitude);
      const lng = Number(warning.longitude);
      if (!isNaN(lat) && !isNaN(lng)) {
        map.setView([lat, lng], 8, { animate: true });
      }
    }, 200);
  };

  useEffect(() => {
    (window as any).locateOnMapById = (rawId: string) => {
      const id = decodeURIComponent(rawId);
      const target = warnings.find((w) => w.warning_id === id);
      if (target) {
        locateWarningOnMap(target);
      }
    };
  }, [warnings, selectedNavArea]);

  const getSeverityBadge = (sev: string = 'high') => {
    const s = sev.toLowerCase();
    if (s === 'critical') {
      return (
        <span className="badge-simple badge-critical">
          <span className="dot"></span> CRITICAL
        </span>
      );
    }
    if (s === 'high') {
      return (
        <span className="badge-simple badge-high">
          <span className="dot"></span> HIGH
        </span>
      );
    }
    return (
      <span className="badge-simple badge-moderate">
        <span className="dot"></span> MODERATE
      </span>
    );
  };

  const getStatusBadge = (w: NavWarning) => {
    if (w.status === 'rejected') {
      return (
        <span className="badge-simple badge-neutral">
          <span className="dot"></span> REJECTED
        </span>
      );
    }
    return w.is_verified ? (
      <span className="badge-simple badge-verified">
        <span className="dot"></span> VERIFIED
      </span>
    ) : (
      <span className="badge-simple badge-neutral">
        <span className="dot"></span> UNVERIFIED
      </span>
    );
  };

  return (
    <main id="main" className="main" tabIndex={-1}>
      {/* ═════════════════ TAB: MAP VIEW ═════════════════ */}
      <div
        className={`tab-panel ${activeTab === 'map' ? 'active' : ''}`}
        id="tab-map"
        role="tabpanel"
        aria-labelledby="tab-btn-map"
      >
        <div className="page-header">
          <div>
            <h1>Active Warnings</h1>
            <p className="subtitle" id="mapSubtitle">
              {mapWarnings.length} in-force across {uniqueNavareas} NAVAREAs
            </p>
          </div>
          <div className="actions">
            <div className="navarea-select-wrapper">
              <label htmlFor="mapNavAreaSelect" className="sr-only">
                Select Navigation Area
              </label>
              <select
                id="mapNavAreaSelect"
                className="navarea-select"
                value={selectedNavArea}
                onChange={(e) => handleNavAreaChange(e.target.value)}
                aria-label="Select Navigation Area"
              >
                <option value="NA I">NAVAREA I · North Atlantic / UK</option>
                <option value="Baltic">Baltic Sub-Area · Sjofartsverket</option>
                <option value="NA II">NAVAREA II · East Atlantic</option>
                <option value="NA III">NAVAREA III · Mediterranean</option>
                <option value="NA IV">NAVAREA IV · West Atlantic</option>
                <option value="NA V">NAVAREA V · Brazil / SW Atlantic</option>
                <option value="NA VI">NAVAREA VI · Argentina / SE Atlantic</option>
                <option value="NA VII">NAVAREA VII · South Africa</option>
                <option value="NA VIII">NAVAREA VIII · Indian Ocean</option>
                <option value="NA IX">NAVAREA IX · Red Sea / Persian Gulf</option>
                <option value="NA X">NAVAREA X · Australia</option>
                <option value="NA XI">NAVAREA XI · East Asia / Japan</option>
                <option value="NA XII">NAVAREA XII · East Pacific</option>
                <option value="NA XIII">NAVAREA XIII · NW Pacific / Okhotsk</option>
                <option value="NA XIV">NAVAREA XIV · New Zealand / S. Pacific</option>
                <option value="NA XV">NAVAREA XV · Chile / SE Pacific</option>
                <option value="NA XVI">NAVAREA XVI · Peru / E. South Pacific</option>
                <option value="NA XVII">NAVAREA XVII · Arctic Canada (West)</option>
                <option value="NA XVIII">NAVAREA XVIII · Arctic Canada (East)</option>
                <option value="NA XIX">NAVAREA XIX · Arctic Norway</option>
                <option value="NA XX">NAVAREA XX · Arctic Russia (Kara/Laptev)</option>
                <option value="NA XXI">NAVAREA XXI · Arctic Russia (East Siberian)</option>
              </select>
              <svg className="navarea-select-chevron" viewBox="0 0 24 24" aria-hidden="true">
                <polyline points="6 9 12 15 18 9"></polyline>
              </svg>
            </div>
            <button className="btn btn-primary" onClick={onRefreshData}>
              Refresh Data
            </button>
            <button className="btn btn-secondary" onClick={() => onSwitchTab('data')}>
              Data Bank →
            </button>
          </div>
        </div>

        <div className="map-container">
          <div id="map" ref={mapContainerRef}></div>

          {/* Map Plot Type Filter Toolbar */}
          <div className="map-plot-toolbar" role="toolbar" aria-label="Filter Map Plot Types">
            <button
              type="button"
              className={`plot-chip ${activePlotType === 'all' ? 'active' : ''}`}
              onClick={() => setActivePlotType('all')}
              title="Show all plot types"
            >
              <span>All Plots</span>
              <span className="plot-chip-count">{plotTypeCounts.all}</span>
            </button>
            <button
              type="button"
              className={`plot-chip ${activePlotType === 'polygon' ? 'active' : ''}`}
              onClick={() => setActivePlotType('polygon')}
              title="Filter by Polygons & Firing Ranges"
            >
              <span>⬡ Polygons</span>
              <span className="plot-chip-count">{plotTypeCounts.polygon}</span>
            </button>
            <button
              type="button"
              className={`plot-chip ${activePlotType === 'circle' ? 'active' : ''}`}
              onClick={() => setActivePlotType('circle')}
              title="Filter by Safety & Exclusion Circles"
            >
              <span>◯ Circles</span>
              <span className="plot-chip-count">{plotTypeCounts.circle}</span>
            </button>
            <button
              type="button"
              className={`plot-chip ${activePlotType === 'line' ? 'active' : ''}`}
              onClick={() => setActivePlotType('line')}
              title="Filter by Cables, Lines & Corridors"
            >
              <span>〰 Lines</span>
              <span className="plot-chip-count">{plotTypeCounts.line}</span>
            </button>
            <button
              type="button"
              className={`plot-chip ${activePlotType === 'point' ? 'active' : ''}`}
              onClick={() => setActivePlotType('point')}
              title="Filter by Point Hazards"
            >
              <span>⚲ Points</span>
              <span className="plot-chip-count">{plotTypeCounts.point}</span>
            </button>
          </div>

          {/* Map Overlay Layers Panel */}
          <div className="map-overlay">
            <details className="map-layer-panel">
              <summary>
                <svg className="layer-summary-icon" viewBox="0 0 24 24">
                  <polygon points="12 2 2 7 12 12 22 7 12 2" />
                  <polyline points="2 17 12 22 22 17" />
                  <polyline points="2 12 12 17 22 12" />
                </svg>
                <span>Layers &amp; Plots</span>
                <svg className="layer-summary-chevron" viewBox="0 0 24 24">
                  <polyline points="6 9 12 15 18 9" />
                </svg>
              </summary>

              <div className="map-layer-section-title">Plot Geometry Types</div>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showPolygons}
                  onChange={(e) => setShowPolygons(e.target.checked)}
                />
                ⬡ Polygons &amp; Firing Areas
              </label>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showCircles}
                  onChange={(e) => setShowCircles(e.target.checked)}
                />
                ◯ Safety &amp; Clearance Circles
              </label>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showLines}
                  onChange={(e) => setShowLines(e.target.checked)}
                />
                〰 Subsea Lines &amp; Corridors
              </label>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showPoints}
                  onChange={(e) => setShowPoints(e.target.checked)}
                />
                ⚲ Point Nautical Glyphs
              </label>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showVertices}
                  onChange={(e) => setShowVertices(e.target.checked)}
                />
                🏷 Corner Vertex Pins (1..N)
              </label>

              <div className="map-layer-divider"></div>
              <div className="map-layer-section-title">Base Cartography</div>
              <label className="map-layer-item">
                <input
                  type="radio"
                  name="basemap"
                  value="carto-voyager"
                  checked={baseMapKey === 'carto-voyager'}
                  onChange={() => setBaseMapKey('carto-voyager')}
                />
                CARTO Voyager
              </label>
              <label className="map-layer-item">
                <input
                  type="radio"
                  name="basemap"
                  value="carto-dark"
                  checked={baseMapKey === 'carto-dark'}
                  onChange={() => setBaseMapKey('carto-dark')}
                />
                CARTO Dark Matter
              </label>
              <label className="map-layer-item">
                <input
                  type="radio"
                  name="basemap"
                  value="carto-positron"
                  checked={baseMapKey === 'carto-positron'}
                  onChange={() => setBaseMapKey('carto-positron')}
                />
                CARTO Positron
              </label>
              <label className="map-layer-item">
                <input
                  type="radio"
                  name="basemap"
                  value="osm"
                  checked={baseMapKey === 'osm'}
                  onChange={() => setBaseMapKey('osm')}
                />
                OpenStreetMap
              </label>
              <label className="map-layer-item">
                <input
                  type="radio"
                  name="basemap"
                  value="esri-ocean"
                  checked={baseMapKey === 'esri-ocean'}
                  onChange={() => setBaseMapKey('esri-ocean')}
                />
                ESRI Ocean Base
              </label>

              <div className="map-layer-divider"></div>
              <div className="map-layer-section-title">Nautical Overlays</div>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showSeamarks}
                  onChange={(e) => setShowSeamarks(e.target.checked)}
                />
                OpenSeaMap Seamarks
              </label>
              <label className="map-layer-item">
                <input
                  type="checkbox"
                  checked={showSoundings}
                  onChange={(e) => setShowSoundings(e.target.checked)}
                />
                Ocean Soundings
              </label>
            </details>
          </div>

          {/* Recenter Pill Button */}
          <div className="map-ctrl-topright" role="toolbar" aria-label="Map Navigation Controls">
            <button
              type="button"
              className="map-recenter-pill-btn"
              onClick={handleRecenter}
              title="Re-center / Locate"
              aria-label="Re-center navigation area on map"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                <circle cx="12" cy="12" r="3" />
                <path d="M12 2v3m0 14v3M2 12h3m14 0h3" />
                <circle cx="12" cy="12" r="8" />
              </svg>
              <span>Re-center</span>
            </button>
          </div>

          {/* Floating Warning List */}
          <div
            className={`map-warning-list ${isWarningListMinimized ? 'is-minimized' : ''} ${
              isWarningListMaximized ? 'is-maximized' : ''
            }`}
            id="mapWarningList"
          >
            <div
              className="panel-header"
              onClick={() => {
                if (isWarningListMinimized) {
                  setIsWarningListMinimized(false);
                }
              }}
              style={{ cursor: isWarningListMinimized ? 'pointer' : 'default' }}
            >
              <div className="bottom-sheet-drag-handle" aria-hidden="true" />
              <div className="panel-header-row">
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <h2>Active Warnings</h2>
                  <span className="badge-simple badge-active" id="mapLiveBadge">
                    <span className="dot"></span> {mapWarnings.length} live
                  </span>
                </div>
                <div className="panel-actions" onClick={(e) => e.stopPropagation()}>
                  <button
                    type="button"
                    className="panel-btn"
                    id="btnMinWarningList"
                    onClick={() => setIsWarningListMinimized(!isWarningListMinimized)}
                    title={isWarningListMinimized ? 'Restore' : 'Minimize'}
                    aria-label="Toggle active warnings list"
                  >
                    {isWarningListMinimized ? (
                      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" style={{ width: 14, height: 14, stroke: 'currentColor', strokeWidth: 2, fill: 'none' }}>
                        <polyline points="18 15 12 9 6 15" />
                      </svg>
                    ) : (
                      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false" style={{ width: 14, height: 14, stroke: 'currentColor', strokeWidth: 2, fill: 'none' }}>
                        <line x1="5" y1="12" x2="19" y2="12" />
                      </svg>
                    )}
                  </button>
                  <button
                    type="button"
                    className="panel-btn"
                    id="btnMaxWarningList"
                    onClick={() => {
                      setIsWarningListMinimized(false);
                      setIsWarningListMaximized(!isWarningListMaximized);
                    }}
                    title={isWarningListMaximized ? 'Restore' : 'Maximize'}
                    aria-label="Maximize active warnings list"
                  >
                    <svg id="iconMaxWarningList" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
                      <polyline points="15 3 21 3 21 9" />
                      <polyline points="9 21 3 21 3 15" />
                      <line x1="21" y1="3" x2="14" y2="10" />
                      <line x1="3" y1="21" x2="10" y2="14" />
                    </svg>
                  </button>
                </div>
              </div>
            </div>

            {!isWarningListMinimized && (
              <div>
                {mapWarnings.length === 0 ? (
                  <div
                    style={{
                      padding: '18px 14px',
                      fontSize: '12px',
                      color: 'var(--text-muted)',
                      textAlign: 'center'
                    }}
                  >
                    No active warnings matching selected plot filter in this area.
                  </div>
                ) : (
                  mapWarnings.map((w) => {
                    const isExpanded = expandedWarningId === w.warning_id;
                    const sevColor =
                      w.severity === 'critical'
                        ? 'var(--critical)'
                        : w.severity === 'high'
                        ? 'var(--high)'
                        : 'var(--neutral)';
                    const types = detectPlotTypes(w);

                    return (
                      <div
                        key={w.warning_id}
                        id={`warning-item-${w.warning_id}`}
                        className={`warning-item ${isExpanded ? 'expanded' : ''}`}
                        onClick={() => setExpandedWarningId(isExpanded ? null : w.warning_id)}
                      >
                        <div className="warning-item-header">
                          <span className="severity-dot" style={{ background: sevColor }}></span>
                          <div className="warning-item-title-col">
                            <div className="warning-id">
                              {w.warning_id} · {w.navarea}
                            </div>
                            <div className="warning-meta">{w.title}</div>
                            <div className="warning-meta" style={{ display: 'flex', gap: '4px', marginTop: '3px' }}>
                              {types.map((t) => (
                                <span
                                  key={t}
                                  style={{
                                    fontSize: '10px',
                                    fontWeight: 700,
                                    textTransform: 'uppercase',
                                    padding: '1px 5px',
                                    borderRadius: '4px',
                                    background: '#f1f5f9',
                                    color: '#475569'
                                  }}
                                >
                                  {t === 'polygon' ? '⬡ Poly' : t === 'circle' ? '◯ Circle' : t === 'line' ? '〰 Line' : '⚲ Point'}
                                </span>
                              ))}
                            </div>
                          </div>
                          <svg className="warning-item-chevron" viewBox="0 0 24 24">
                            <polyline points="6 9 12 15 18 9" />
                          </svg>
                        </div>

                        {isExpanded && (
                          <div className="warning-expanded-body" onClick={(e) => e.stopPropagation()}>
                            <div className="warning-expanded-badges">
                              {getSeverityBadge(w.severity)}
                              {getStatusBadge(w)}
                              {w.category && (
                                <span className="badge-simple badge-neutral">
                                  {w.category.toUpperCase()}
                                </span>
                              )}
                            </div>
                            <div className="warning-expanded-meta">
                              <div>
                                <strong>Issued:</strong> {w.issued_text || formatDate(w)}
                              </div>
                              <div>
                                <strong>Coordinates:</strong>{' '}
                                {w.coordinates ||
                                  (w.latitude && w.longitude
                                    ? `${w.latitude.toFixed(2)}, ${w.longitude.toFixed(2)}`
                                    : 'N/A')}
                              </div>
                            </div>
                            <div className="warning-expanded-text">{w.raw_text}</div>
                            <div className="warning-expanded-actions">
                              <button
                                type="button"
                                className="btn btn-sm btn-secondary"
                                onClick={() => locateWarningOnMap(w)}
                              >
                                <span>📍 Focus on Map</span>
                              </button>
                              <button
                                type="button"
                                className="btn btn-sm btn-ghost"
                                onClick={() => setExpandedWarningId(null)}
                              >
                                <span>Collapse</span>
                              </button>
                            </div>
                          </div>
                        )}
                      </div>
                    );
                  })
                )}
              </div>
            )}
          </div>

          {/* Collapsible Plot Legend */}
          <details className="map-plot-legend">
            <summary>
              <svg style={{ width: '13px', height: '13px', stroke: '#0d9488', fill: 'none', strokeWidth: 2 }} viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10"/>
                <line x1="12" y1="16" x2="12" y2="12"/>
                <line x1="12" y1="8" x2="12.01" y2="8"/>
              </svg>
              <span>Maritime Plot Legend</span>
            </summary>
            <div className="map-plot-legend-grid">
              <div className="legend-item">
                <span className="legend-sym" style={{ border: '2px dashed #dc2626', background: 'rgba(220,38,38,0.2)', borderRadius: '2px' }}></span>
                <span>Military Polygon</span>
              </div>
              <div className="legend-item">
                <span className="legend-sym" style={{ border: '2px dashed #ea580c', background: 'rgba(249,115,22,0.2)', borderRadius: '50%' }}></span>
                <span>Safety / Radius Circle</span>
              </div>
              <div className="legend-item">
                <span className="legend-sym" style={{ height: '3px', background: '#0284c7', margin: '5px 0' }}></span>
                <span>Subsea Cable / Track</span>
              </div>
              <div className="legend-item">
                <span className="legend-sym" style={{ border: '1px dashed #ca8a04', background: 'rgba(245,158,11,0.25)', borderRadius: '2px' }}></span>
                <span>Survey Swath Corridor</span>
              </div>
              <div className="legend-item">
                <span className="legend-sym" style={{ width: '10px', height: '10px', borderRadius: '50%', background: '#ea580c', border: '1px solid #fff' }}></span>
                <span>AtoN Light / Buoy</span>
              </div>
              <div className="legend-item">
                <span className="legend-sym" style={{ width: '10px', height: '10px', borderRadius: '2px', background: '#f97316', border: '1px solid #fff' }}></span>
                <span>Drifting Hazard</span>
              </div>
            </div>
          </details>

          <div className="map-attribution">© OpenStreetMap contributors · CARTO · OpenSeaMap</div>
        </div>
      </div>

      {/* ═════════════════ TAB: DATA BANK ═════════════════ */}
      <div
        className={`tab-panel ${activeTab === 'data' ? 'active' : ''}`}
        id="tab-data"
        role="tabpanel"
        aria-labelledby="tab-btn-data"
      >
        <div className="page-header">
          <div>
            <h1>Data Bank</h1>
            <p className="subtitle" id="dataSubtitle">
              {tableWarnings.length} published warnings
            </p>
          </div>
          <div className="actions">
            <button className="btn btn-primary" id="btnRefreshSupabase" onClick={onRefreshData}>
              <svg
                style={{
                  width: '14px',
                  height: '14px',
                  display: 'inline-block',
                  verticalAlign: '-2px',
                  marginRight: '6px'
                }}
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                strokeWidth="2"
                strokeLinecap="round"
                strokeLinejoin="round"
              >
                <path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
                <path d="M3 3v5h5" />
                <path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16" />
                <path d="M16 21h5v-5" />
              </svg>
              <span>Refresh Supabase</span>
            </button>
            <button
              className="btn btn-secondary"
              onClick={() => {
                const blob = new Blob([JSON.stringify(tableWarnings, null, 2)], {
                  type: 'application/json'
                });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `nav_warnings_${new Date().toISOString().slice(0, 10)}.json`;
                a.click();
                URL.revokeObjectURL(url);
              }}
            >
              Export
            </button>
          </div>
        </div>

        {/* 4 Stat Cards */}
        <div className="stat-grid">
          <div className="stat-card">
            <div className="stat-icon active" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="3" fill="currentColor" />
                <path d="M4.93 4.93a10 10 0 0 1 14.14 0M7.76 7.76a6 6 0 0 1 8.48 0" />
              </svg>
            </div>
            <div className="stat-content">
              <div className="stat-label">Active</div>
              <div className="stat-value-row">
                <span className="stat-value" id="statActive">
                  {activeCount}
                </span>
                <span className="stat-sub">In-force</span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon coverage" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <circle cx="12" cy="12" r="10" />
                <path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z" />
              </svg>
            </div>
            <div className="stat-content">
              <div className="stat-label">Coverage</div>
              <div className="stat-value-row">
                <span className="stat-value" id="statCoverage">
                  {uniqueNavareas}/21
                </span>
                <span className="stat-sub" id="statCoverageSub">
                  {Math.round((uniqueNavareas / 21) * 100)}% global
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon high" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3Z" />
                <line x1="12" y1="9" x2="12" y2="13" />
                <line x1="12" y1="17" x2="12.01" y2="17" />
              </svg>
            </div>
            <div className="stat-content">
              <div className="stat-label">Critical / High</div>
              <div className="stat-value-row">
                <span className="stat-value" id="statHigh">
                  {highCount}
                </span>
                <span className="stat-sub" id="statHighSub">
                  {highCount} warnings
                </span>
              </div>
            </div>
          </div>

          <div className="stat-card">
            <div className="stat-icon geo" aria-hidden="true">
              <svg viewBox="0 0 24 24">
                <polygon points="3 11 22 2 13 21 11 13 3 11" />
              </svg>
            </div>
            <div className="stat-content">
              <div className="stat-label">Georeferenced</div>
              <div className="stat-value-row">
                <span className="stat-value" id="statGeo">
                  100%
                </span>
                <span className="stat-sub">GPS Coords</span>
              </div>
            </div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="filter-bar">
          <div className="search">
            <label htmlFor="searchInput" className="sr-only">
              Search warnings
            </label>
            <input
              type="search"
              placeholder="Search warnings..."
              id="searchInput"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              aria-label="Search warnings"
            />
          </div>
          <button
            className="btn btn-ghost"
            id="btnToggleFilters"
            onClick={() => setShowAdvancedFilters(!showAdvancedFilters)}
            aria-expanded={showAdvancedFilters}
            aria-controls="advancedFilters"
          >
            Filters{' '}
            {(filterNavArea || filterSeverity || filterCategory) && (
              <span id="activeFilterCount" className="badge-simple badge-neutral">
                {[filterNavArea, filterSeverity, filterCategory].filter(Boolean).length}
              </span>
            )}
          </button>
        </div>

        {/* Advanced Filters */}
        <div className={`advanced-filters ${showAdvancedFilters ? 'open' : ''}`} id="advancedFilters">
          <div className="filter-grid">
            <div className="filter-group">
              <label htmlFor="filter-navarea">NAVAREA</label>
              <select
                id="filter-navarea"
                value={filterNavArea}
                onChange={(e) => setFilterNavArea(e.target.value)}
                aria-label="Filter by NAVAREA"
              >
                <option value="">All Regions</option>
                <option value="NA I">NA I · North Atlantic / UK</option>
                <option value="Baltic">Baltic Sub-Area</option>
                <option value="NA II">NA II · East Atlantic</option>
                <option value="NA III">NA III · Mediterranean</option>
                <option value="NA IV">NA IV · West Atlantic</option>
                <option value="NA V">NA V · Brazil / SW Atlantic</option>
                <option value="NA VI">NA VI · Argentina / SE Atlantic</option>
                <option value="NA VII">NA VII · South Africa</option>
                <option value="NA VIII">NA VIII · Indian Ocean</option>
                <option value="NA IX">NA IX · Red Sea / Persian Gulf</option>
                <option value="NA X">NA X · Australia</option>
                <option value="NA XI">NA XI · East Asia / Japan</option>
                <option value="NA XII">NA XII · East Pacific</option>
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="filter-severity">Severity</label>
              <select
                id="filter-severity"
                value={filterSeverity}
                onChange={(e) => setFilterSeverity(e.target.value)}
                aria-label="Filter by Severity"
              >
                <option value="">All</option>
                <option value="critical">Critical</option>
                <option value="high">High</option>
                <option value="moderate">Moderate</option>
              </select>
            </div>
            <div className="filter-group">
              <label htmlFor="filter-category">Category</label>
              <select
                id="filter-category"
                value={filterCategory}
                onChange={(e) => setFilterCategory(e.target.value)}
                aria-label="Filter by Category"
              >
                <option value="">All</option>
                <option value="military">Military</option>
                <option value="drifting">Drifting</option>
                <option value="general">General</option>
                <option value="aton">AtoN</option>
                <option value="subsea">Subsea</option>
              </select>
            </div>
          </div>
        </div>

        {/* Data Table */}
        <div className="data-table-container">
          <table className="data-table">
            <caption className="sr-only">Navigational Warnings Data Bank</caption>
            <thead>
              <tr>
                <th scope="col">ID</th>
                <th scope="col">Area</th>
                <th scope="col">Title</th>
                <th scope="col">Severity</th>
                <th scope="col">Issued</th>
                <th scope="col">Coords</th>
                <th scope="col">Status</th>
              </tr>
            </thead>
            <tbody id="tableBody">
              {tableWarnings.map((w) => {
                const isExpanded = expandedTableId === w.warning_id;
                return (
                  <React.Fragment key={w.warning_id}>
                    <tr
                      onClick={() => setExpandedTableId(isExpanded ? null : w.warning_id)}
                      className={isExpanded ? 'table-row-selected' : ''}
                    >
                      <td>
                        <strong>{w.warning_id}</strong>
                        <svg className="row-chevron" viewBox="0 0 24 24">
                          <polyline points="6 9 12 15 18 9" />
                        </svg>
                      </td>
                      <td>{w.navarea}</td>
                      <td>{w.title}</td>
                      <td>{getSeverityBadge(w.severity)}</td>
                      <td>{formatDate(w)}</td>
                      <td>{w.coordinates || 'N/A'}</td>
                      <td>{getStatusBadge(w)}</td>
                    </tr>

                    {isExpanded && (
                      <tr className="table-detail-row">
                        <td colSpan={7}>
                          <div className="table-detail-container" onClick={(e) => e.stopPropagation()}>
                            <div className="table-detail-header">
                              <div className="warning-expanded-badges">
                                {getSeverityBadge(w.severity)}
                                {getStatusBadge(w)}
                                {w.category && (
                                  <span className="badge-simple badge-neutral">
                                    {w.category.toUpperCase()}
                                  </span>
                                )}
                                <span style={{ fontWeight: 600, fontSize: '13px', color: 'var(--text)' }}>
                                  {w.title}
                                </span>
                              </div>
                              <div className="table-detail-actions">
                                <button
                                  type="button"
                                  className="btn btn-sm btn-primary"
                                  onClick={() => locateWarningOnMap(w)}
                                >
                                  <span>📍 View on Map</span>
                                </button>
                                <button
                                  type="button"
                                  className="btn btn-sm btn-ghost"
                                  onClick={() => setExpandedTableId(null)}
                                >
                                  <span>Collapse</span>
                                </button>
                              </div>
                            </div>
                            <div className="table-detail-meta">
                              <div>
                                <strong>NAVAREA:</strong> {w.navarea}
                              </div>
                              <div>
                                <strong>Issued:</strong> {w.issued_text || formatDate(w)}
                              </div>
                              <div>
                                <strong>Coordinates:</strong> {w.coordinates || 'N/A'}
                              </div>
                              {w.source_id && (
                                <div>
                                  <strong>Authority:</strong> {w.source_id}
                                </div>
                              )}
                            </div>
                            <div className="table-detail-text">{w.raw_text}</div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                );
              })}
            </tbody>
          </table>
          <div className="table-footer">
            <span id="tableCount">
              Showing 1–{tableWarnings.length} of {tableWarnings.length}
            </span>
            <span>Rows: {tableWarnings.length}</span>
          </div>
        </div>

        {/* Mobile Card List */}
        <div className="card-list" id="cardList">
          {tableWarnings.map((w) => {
            const isExpanded = expandedTableId === w.warning_id;
            return (
              <div
                key={w.warning_id}
                className={`warning-card ${isExpanded ? 'expanded' : ''}`}
                onClick={() => setExpandedTableId(isExpanded ? null : w.warning_id)}
              >
                <div className="warning-card-header">
                  <span className="warning-card-id">
                    {w.warning_id} · {w.navarea}
                  </span>
                  {getSeverityBadge(w.severity)}
                </div>
                <div className="warning-card-title">{w.title}</div>
                <div className="warning-card-meta">
                  <span>📍 {w.navarea}</span>
                  <span>📅 {formatDate(w)}</span>
                  <span>🎯 {w.coordinates || 'N/A'}</span>
                </div>

                {isExpanded && (
                  <div className="warning-card-expanded-body" onClick={(e) => e.stopPropagation()}>
                    <div className="warning-expanded-badges">
                      {getStatusBadge(w)}
                      {w.category && (
                        <span className="badge-simple badge-neutral">
                          {w.category.toUpperCase()}
                        </span>
                      )}
                    </div>
                    <div className="table-detail-text">{w.raw_text}</div>
                    <div className="warning-expanded-actions">
                      <button
                        type="button"
                        className="btn btn-sm btn-primary"
                        onClick={() => locateWarningOnMap(w)}
                      >
                        <span>📍 View on Map</span>
                      </button>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* ═════════════════ TAB: SOURCES ═════════════════ */}
      <div
        className={`tab-panel ${activeTab === 'sources' ? 'active' : ''}`}
        id="tab-sources"
        role="tabpanel"
        aria-labelledby="tab-btn-sources"
      >
        <div className="page-header">
          <div>
            <h1>Source Registry</h1>
            <p className="subtitle">14 verified feeds across 21 NAVAREAs</p>
          </div>
        </div>
        <div className="sources-grid" id="sourcesGrid">
          {SOURCES_LIST.map((src, idx) => (
            <div key={idx} className="source-card">
              <div className="source-header">
                <div>
                  <div className="source-name">{src.region}</div>
                  <div className="source-region">{src.name}</div>
                </div>
                {src.verified ? (
                  <span className="badge-simple badge-verified">
                    <span className="dot"></span> ✓
                  </span>
                ) : (
                  <span className="badge-simple badge-neutral">
                    <span className="dot"></span> ⋯
                  </span>
                )}
              </div>
              <div className="source-count">{src.count} active warnings</div>
              <a
                href={`https://${src.url}`}
                target="_blank"
                rel="noopener noreferrer"
                className="source-url"
              >
                {src.url}
              </a>
            </div>
          ))}
        </div>
      </div>

      {/* Modal Dialog */}
      {modalWarning && (
        <div
          className="modal-overlay open"
          onClick={() => setModalWarning(null)}
          role="dialog"
          aria-modal="true"
        >
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h2>
                {modalWarning.warning_id} — {modalWarning.navarea}
              </h2>
              <button
                className="modal-close"
                onClick={() => setModalWarning(null)}
                aria-label="Close"
              >
                ✕
              </button>
            </div>
            <div className="modal-body">
              <div className="detail-row">
                <div className="detail-label">Severity</div>
                <div className="detail-value">{getSeverityBadge(modalWarning.severity)}</div>
              </div>
              <div className="detail-row">
                <div className="detail-label">Issued</div>
                <div className="detail-value">{modalWarning.issued_text || formatDate(modalWarning)}</div>
              </div>
              <div className="detail-row">
                <div className="detail-label">Coordinates</div>
                <div className="detail-value">{modalWarning.coordinates || 'N/A'}</div>
              </div>
              <div className="detail-row">
                <div className="detail-label">Status</div>
                <div className="detail-value">{getStatusBadge(modalWarning)}</div>
              </div>
              <div className="warning-text">{modalWarning.raw_text}</div>
            </div>
            <div className="modal-footer">
              <button className="btn btn-ghost" onClick={() => setModalWarning(null)}>
                Close
              </button>
              <button
                className="btn btn-secondary"
                onClick={() => {
                  locateWarningOnMap(modalWarning);
                }}
              >
                Locate on Map
              </button>
            </div>
          </div>
        </div>
      )}
    </main>
  );
};
