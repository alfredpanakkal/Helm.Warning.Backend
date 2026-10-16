import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { NavWarning, HazardCategory, NavareaRegion } from '../types/maritime';
import { getCategoryBadgeStyle } from '../core/classification';
import { Layers, Maximize2, RefreshCw, Compass } from 'lucide-react';

interface MaritimeMapProps {
  warnings: NavWarning[];
  selectedWarning: NavWarning | null;
  onSelectWarning: (warning: NavWarning) => void;
  activeNavarea: NavareaRegion | 'ALL';
}

export const MaritimeMap: React.FC<MaritimeMapProps> = ({
  warnings,
  selectedWarning,
  onSelectWarning,
  activeNavarea
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const [mapTileStyle, setMapTileStyle] = useState<'dark' | 'nautical' | 'osm'>('dark');

  // Initialize Map
  useEffect(() => {
    if (!mapContainerRef.current) return;

    if (!mapInstanceRef.current) {
      const map = L.map(mapContainerRef.current, {
        center: [35.0, 30.0],
        zoom: 3,
        zoomControl: false,
        attributionControl: false
      });

      L.control.zoom({ position: 'bottomright' }).addTo(map);

      // Base tile layer (CartoDB Dark Matter)
      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd'
      }).addTo(map);

      const layerGroup = L.layerGroup().addTo(map);
      layerGroupRef.current = layerGroup;
      mapInstanceRef.current = map;
    }

    return () => {
      // Keep map alive or clean up on unmount
    };
  }, []);

  // Update Tile Layer if changed
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map) return;

    map.eachLayer((layer) => {
      if (layer instanceof L.TileLayer) {
        map.removeLayer(layer);
      }
    });

    let url = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    if (mapTileStyle === 'nautical') {
      url = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    } else if (mapTileStyle === 'osm') {
      url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    }

    L.tileLayer(url, {
      maxZoom: 18,
      subdomains: 'abcd'
    }).addTo(map);

    // Re-render geometries
    renderGeometries();
  }, [mapTileStyle]);

  // Render geometries when warnings or filter changes
  const renderGeometries = () => {
    const map = mapInstanceRef.current;
    const group = layerGroupRef.current;
    if (!map || !group) return;

    group.clearLayers();

    const filtered = warnings.filter((w) => {
      if (activeNavarea === 'ALL') return true;
      return w.navarea === activeNavarea;
    });

    const bounds: L.LatLng[] = [];

    filtered.forEach((warning) => {
      const isSelected = selectedWarning?.warning_id === warning.warning_id;
      const badgeStyle = getCategoryBadgeStyle(warning.category);
      const color = badgeStyle.colorHex;

      const popupHtml = `
        <div style="font-family: inherit; font-size: 12px; color: #f8fafc; min-width: 200px;">
          <div style="display: flex; align-items: center; justify-content: space-between; margin-bottom: 6px; border-bottom: 1px solid #334155; padding-bottom: 4px;">
            <span style="font-weight: 700; color: #38bdf8;">${warning.warning_id}</span>
            <span style="font-size: 10px; background: rgba(255,255,255,0.1); padding: 2px 6px; border-radius: 4px;">NAVAREA ${warning.navarea}</span>
          </div>
          <div style="font-weight: 600; margin-bottom: 6px; color: #e2e8f0;">${warning.title}</div>
          <div style="display: inline-block; background: ${color}22; color: ${color}; border: 1px solid ${color}66; border-radius: 4px; padding: 2px 6px; font-size: 10px; margin-bottom: 6px; text-transform: uppercase;">
            ${badgeStyle.label}
          </div>
          ${warning.coordinates ? `<div style="font-family: monospace; font-size: 11px; color: #94a3b8; margin-top: 4px;">${warning.coordinates}</div>` : ''}
          ${warning.issued_text ? `<div style="font-size: 10px; color: #64748b; margin-top: 4px;">Issued: ${warning.issued_text}</div>` : ''}
        </div>
      `;

      if (warning.spatial) {
        if (warning.spatial.type === 'Point') {
          const [lon, lat] = warning.spatial.coordinates;
          const latLng = L.latLng(lat, lon);
          bounds.push(latLng);

          const marker = L.circleMarker(latLng, {
            radius: isSelected ? 11 : 7,
            fillColor: color,
            color: isSelected ? '#ffffff' : '#0f172a',
            weight: isSelected ? 3 : 2,
            opacity: 1,
            fillOpacity: 0.85
          });

          marker.bindPopup(popupHtml);
          marker.on('click', () => onSelectWarning(warning));
          group.addLayer(marker);
        } else if (warning.spatial.type === 'Polygon') {
          const coords = warning.spatial.coordinates[0];
          const latLngs = coords.map((c) => L.latLng(c[1], c[0]));
          latLngs.forEach((ll) => bounds.push(ll));

          const polygon = L.polygon(latLngs, {
            color: color,
            weight: isSelected ? 3 : 2,
            opacity: 0.9,
            fillColor: color,
            fillOpacity: isSelected ? 0.35 : 0.2,
            dashArray: warning.category === 'military' ? '6, 6' : undefined
          });

          polygon.bindPopup(popupHtml);
          polygon.on('click', () => onSelectWarning(warning));
          group.addLayer(polygon);
        } else if (warning.spatial.type === 'LineString') {
          const coords = warning.spatial.coordinates;
          const latLngs = coords.map((c) => L.latLng(c[1], c[0]));
          latLngs.forEach((ll) => bounds.push(ll));

          const line = L.polyline(latLngs, {
            color: color,
            weight: isSelected ? 5 : 3,
            opacity: 0.9,
            dashArray: '5, 5'
          });

          line.bindPopup(popupHtml);
          line.on('click', () => onSelectWarning(warning));
          group.addLayer(line);
        }
      } else if (warning.latitude !== null && warning.longitude !== null) {
        const latLng = L.latLng(warning.latitude, warning.longitude);
        bounds.push(latLng);

        const marker = L.circleMarker(latLng, {
          radius: isSelected ? 11 : 7,
          fillColor: color,
          color: isSelected ? '#ffffff' : '#0f172a',
          weight: isSelected ? 3 : 2,
          opacity: 1,
          fillOpacity: 0.85
        });

        marker.bindPopup(popupHtml);
        marker.on('click', () => onSelectWarning(warning));
        group.addLayer(marker);
      }
    });

    if (bounds.length > 0 && !selectedWarning) {
      try {
        const lBounds = L.latLngBounds(bounds);
        map.fitBounds(lBounds, { padding: [40, 40], maxZoom: 8 });
      } catch (e) {
        // Ignore fitbounds bounds errors
      }
    }
  };

  useEffect(() => {
    renderGeometries();
  }, [warnings, activeNavarea, selectedWarning]);

  // Center on selected warning
  useEffect(() => {
    const map = mapInstanceRef.current;
    if (!map || !selectedWarning) return;

    if (selectedWarning.latitude !== null && selectedWarning.longitude !== null) {
      map.flyTo([selectedWarning.latitude, selectedWarning.longitude], 8, {
        duration: 1.2
      });
    }
  }, [selectedWarning]);

  const handleResetView = () => {
    const map = mapInstanceRef.current;
    if (!map) return;

    if (activeNavarea === 'Baltic') {
      map.flyTo([58.0, 15.0], 5);
    } else if (activeNavarea === 'I') {
      map.flyTo([54.0, 0.0], 5);
    } else if (activeNavarea === 'XI') {
      map.flyTo([25.0, 130.0], 4);
    } else {
      map.flyTo([35.0, 30.0], 3);
    }
  };

  return (
    <div className="relative w-full h-full bg-slate-950 flex flex-col overflow-hidden rounded-xl border border-slate-800">
      {/* Map Header / Controls overlay */}
      <div className="absolute top-3 left-3 z-[1000] flex items-center gap-2">
        <div className="bg-slate-900/90 backdrop-blur-md px-3 py-1.5 rounded-lg border border-slate-700/70 text-xs font-medium text-slate-200 flex items-center gap-2 shadow-lg">
          <Compass className="w-3.5 h-3.5 text-cyan-400 animate-spin" style={{ animationDuration: '20s' }} />
          <span>WGS84 Chart Projection</span>
          <span className="text-slate-500">•</span>
          <span className="text-cyan-400 font-mono">
            {warnings.filter((w) => (activeNavarea === 'ALL' ? true : w.navarea === activeNavarea)).length} plotted hazards
          </span>
        </div>

        {/* Quick Navarea Focus Jump */}
        <div className="bg-slate-900/90 backdrop-blur-md px-1.5 py-1 rounded-lg border border-slate-700/70 flex items-center gap-1 shadow-lg text-xs">
          <button
            onClick={() => mapInstanceRef.current?.flyTo([58.0, 15.0], 5)}
            className="px-2 py-0.5 rounded text-slate-300 hover:text-white hover:bg-slate-800 transition"
            title="Focus Baltic"
          >
            Baltic
          </button>
          <button
            onClick={() => mapInstanceRef.current?.flyTo([54.0, 0.0], 5)}
            className="px-2 py-0.5 rounded text-slate-300 hover:text-white hover:bg-slate-800 transition"
            title="Focus NAVAREA I (UK)"
          >
            NAVAREA I
          </button>
          <button
            onClick={() => mapInstanceRef.current?.flyTo([25.0, 130.0], 4)}
            className="px-2 py-0.5 rounded text-slate-300 hover:text-white hover:bg-slate-800 transition"
            title="Focus NAVAREA XI (Japan)"
          >
            NAVAREA XI
          </button>
        </div>
      </div>

      {/* Top right basemap toggle & reset */}
      <div className="absolute top-3 right-3 z-[1000] flex items-center gap-2">
        <div className="bg-slate-900/90 backdrop-blur-md p-1 rounded-lg border border-slate-700/70 flex items-center gap-1 shadow-lg">
          <button
            onClick={() => setMapTileStyle('dark')}
            className={`px-2 py-1 text-xs rounded transition font-medium ${
              mapTileStyle === 'dark' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Dark Hydro
          </button>
          <button
            onClick={() => setMapTileStyle('nautical')}
            className={`px-2 py-1 text-xs rounded transition font-medium ${
              mapTileStyle === 'nautical' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            Voyager
          </button>
          <button
            onClick={() => setMapTileStyle('osm')}
            className={`px-2 py-1 text-xs rounded transition font-medium ${
              mapTileStyle === 'osm' ? 'bg-cyan-600 text-white' : 'text-slate-400 hover:text-slate-200'
            }`}
          >
            OpenSea
          </button>
        </div>

        <button
          onClick={handleResetView}
          title="Reset Zoom"
          className="p-2 bg-slate-900/90 backdrop-blur-md text-slate-300 hover:text-cyan-400 hover:bg-slate-800 rounded-lg border border-slate-700/70 shadow-lg transition"
        >
          <Maximize2 className="w-3.5 h-3.5" />
        </button>
      </div>

      {/* Leaflet Map Div */}
      <div ref={mapContainerRef} className="w-full h-full z-0" />

      {/* Bottom Map Legend */}
      <div className="absolute bottom-3 left-3 z-[1000] bg-slate-900/95 backdrop-blur-md px-3 py-2 rounded-lg border border-slate-800 text-[11px] shadow-xl max-w-sm hidden sm:block">
        <div className="text-slate-400 font-semibold mb-1.5 flex items-center gap-1.5">
          <Layers className="w-3 h-3 text-cyan-400" />
          <span>MARITIME HAZARD LEGEND</span>
        </div>
        <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-slate-300">
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-rose-500 border border-white/40"></span>
            <span>Military / Detonations</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-400 border border-white/40"></span>
            <span>AtoN (Lights / Buoys)</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 border border-white/40"></span>
            <span>Subsea Cables / ROV</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-purple-400 border border-white/40"></span>
            <span>Electronic / GNSS</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-orange-400 border border-white/40"></span>
            <span>Drifting Debris / Mines</span>
          </div>
          <div className="flex items-center gap-1.5">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-400 border border-white/40"></span>
            <span>Offshore Rig / Jack-up</span>
          </div>
        </div>
      </div>
    </div>
  );
};
