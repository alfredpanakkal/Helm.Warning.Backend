import React, { useEffect, useRef, useState } from 'react';
import L from 'leaflet';
import { NavWarning, NavareaRegion } from '../types/maritime';
import { getCategoryBadgeStyle } from '../core/classification';
import {
  computeDistanceNm,
  computePolygonAreaSqNm,
  computeLineCorridor,
  formatCoordinateString
} from '../core/coordinates';
import { Layers, Maximize2, Compass } from 'lucide-react';

interface MaritimeMapProps {
  warnings: NavWarning[];
  selectedWarning: NavWarning | null;
  onSelectWarning: (warning: NavWarning) => void;
  activeNavarea: NavareaRegion | 'ALL';
}

type PlotFilter = 'all' | 'polygon' | 'circle' | 'line' | 'point';

export const MaritimeMap: React.FC<MaritimeMapProps> = ({
  warnings,
  selectedWarning,
  onSelectWarning,
  activeNavarea
}) => {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapInstanceRef = useRef<L.Map | null>(null);
  const layerGroupRef = useRef<L.LayerGroup | null>(null);
  const [mapTileStyle, setMapTileStyle] = useState<'voyager' | 'dark' | 'osm'>('voyager');
  const [plotFilter, setPlotFilter] = useState<PlotFilter>('all');

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

      L.tileLayer('https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd'
      }).addTo(map);

      const layerGroup = L.layerGroup().addTo(map);
      layerGroupRef.current = layerGroup;
      mapInstanceRef.current = map;
    }

    const handleResize = () => {
      mapInstanceRef.current?.invalidateSize();
    };
    window.addEventListener('resize', handleResize);
    window.addEventListener('orientationchange', handleResize);
    return () => {
      window.removeEventListener('resize', handleResize);
      window.removeEventListener('orientationchange', handleResize);
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

    let url = 'https://{s}.basemaps.cartocdn.com/rastertiles/voyager/{z}/{x}/{y}{r}.png';
    if (mapTileStyle === 'dark') {
      url = 'https://{s}.basemaps.cartocdn.com/dark_all/{z}/{x}/{y}{r}.png';
    } else if (mapTileStyle === 'osm') {
      url = 'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png';
    }

    L.tileLayer(url, {
      maxZoom: 18,
      subdomains: 'abcd'
    }).addTo(map);

    renderGeometries();
  }, [mapTileStyle]);

  // Render geometries when warnings or filter changes
  const renderGeometries = () => {
    const map = mapInstanceRef.current;
    const group = layerGroupRef.current;
    if (!map || !group) return;

    group.clearLayers();

    const filtered = warnings.filter((w) => {
      if (activeNavarea !== 'ALL' && w.navarea !== activeNavarea) return false;
      return true;
    });

    const bounds: L.LatLng[] = [];

    filtered.forEach((warning) => {
      const isSelected = selectedWarning?.warning_id === warning.warning_id;
      const badgeStyle = getCategoryBadgeStyle(warning.category);
      const color = badgeStyle.colorHex;

      const popupHtml = `
        <div style="font-family:system-ui;font-size:12px;color:var(--text);min-width:210px;line-height:1.4">
          <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:6px;border-bottom:1px solid #e2e8f0;padding-bottom:4px">
            <span style="font-weight:700;color:var(--surface-dark)">${warning.warning_id}</span>
            <span style="font-size:10px;background:#f1f5f9;color:#475569;padding:2px 6px;border-radius:4px;font-weight:600">NAVAREA ${warning.navarea}</span>
          </div>
          <div style="font-weight:600;margin-bottom:6px;color:var(--text)">${warning.title}</div>
          <div style="display:inline-block;background:${color}22;color:${color};border:1px solid ${color}66;border-radius:4px;padding:2px 6px;font-size:10px;margin-bottom:6px;text-transform:uppercase;font-weight:600">
            ${badgeStyle.label}
          </div>
          ${warning.coordinates ? `<div style="font-family:ui-monospace,monospace;font-size:11px;color:var(--text-muted);margin-top:4px">${warning.coordinates}</div>` : ''}
          ${warning.issued_text ? `<div style="font-size:10px;color:var(--text-light);margin-top:4px">Issued: ${warning.issued_text}</div>` : ''}
        </div>
      `;

      const spatialAny = warning.spatial as any;
      const geometries: any[] = spatialAny?.type ? [spatialAny] : spatialAny?.geometries || [];
      const circles: any[] = spatialAny?.circles || [];
      const corridors: any[] = spatialAny?.corridors || [];
      let renderedSpatial = false;

      // 1. Polygons
      if (plotFilter === 'all' || plotFilter === 'polygon') {
        geometries
          .filter((g) => g.type === 'Polygon')
          .forEach((geom) => {
            renderedSpatial = true;
            const rings = geom.coordinates || [];
            if (!rings[0]) return;

            const latLngs = rings[0].map((pt: [number, number]) => L.latLng(pt[1], pt[0]));
            latLngs.forEach((ll: L.LatLng) => bounds.push(ll));

            const areaSqNm = computePolygonAreaSqNm(rings[0]);
            const polygon = L.polygon(latLngs, {
              color: isSelected ? '#0f172a' : color,
              weight: isSelected ? 3 : 2,
              opacity: 0.9,
              fillColor: color,
              fillOpacity: isSelected ? 0.35 : 0.2,
              dashArray: warning.category === 'military' ? '6, 6' : undefined
            });

            polygon.bindPopup(popupHtml);
            polygon.on('click', () => onSelectWarning(warning));
            group.addLayer(polygon);

            // Corner vertex pins
            rings[0].forEach((pt: [number, number], vIdx: number) => {
              if (vIdx === rings[0].length - 1 && rings[0].length > 3) return;
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
              vertexMarker.on('click', () => onSelectWarning(warning));
              group.addLayer(vertexMarker);
            });

            // Centroid metric badge
            const center = polygon.getBounds().getCenter();
            const areaBadge = L.marker(center, {
              icon: L.divIcon({
                className: 'metric-pill-wrapper',
                html: `<div class="metric-pill-marker amber">${warning.warning_id} · ${areaSqNm} sq NM</div>`,
                iconAnchor: [45, 12]
              })
            });
            group.addLayer(areaBadge);
          });
      }

      // 2. Circles & Danger Buffers
      if (plotFilter === 'all' || plotFilter === 'circle') {
        circles.forEach((c) => {
          renderedSpatial = true;
          const centerLatLng = L.latLng(c.center[1], c.center[0]);
          bounds.push(centerLatLng);

          const radiusMeters = c.radius_nm * 1852;
          const circleLayer = L.circle(centerLatLng, {
            color: '#ea580c',
            fillColor: '#f97316',
            fillOpacity: isSelected ? 0.3 : 0.15,
            weight: isSelected ? 3 : 2,
            dashArray: '4, 4',
            radius: radiusMeters
          });
          circleLayer.bindPopup(popupHtml);
          circleLayer.on('click', () => onSelectWarning(warning));
          group.addLayer(circleLayer);

          // Radial measurement line
          const edgeLat = centerLatLng.lat + (c.radius_nm / 60);
          const edgeLatLng = L.latLng(edgeLat, centerLatLng.lng);
          const radiusLine = L.polyline([centerLatLng, edgeLatLng], {
            color: '#ea580c',
            weight: 1.5,
            dashArray: '2, 3'
          });
          group.addLayer(radiusLine);

          const radiusPill = L.marker(L.latLng((centerLatLng.lat + edgeLat) / 2, centerLatLng.lng), {
            icon: L.divIcon({
              className: 'metric-pill-wrapper',
              html: `<div class="metric-pill-marker amber">${c.radius_nm} NM Radius</div>`,
              iconAnchor: [30, 10]
            })
          });
          group.addLayer(radiusPill);
        });
      }

      // 3. LineStrings & Corridors
      if (plotFilter === 'all' || plotFilter === 'line') {
        geometries
          .filter((g) => g.type === 'LineString')
          .forEach((geom) => {
            renderedSpatial = true;
            const coords = geom.coordinates || [];
            if (coords.length < 2) return;

            const latLngs = coords.map((pt: [number, number]) => L.latLng(pt[1], pt[0]));
            latLngs.forEach((ll: L.LatLng) => bounds.push(ll));

            let totalDist = 0;
            for (let i = 0; i < coords.length - 1; i++) {
              totalDist += computeDistanceNm(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0]);
            }

            const line = L.polyline(latLngs, {
              color: '#0284c7',
              weight: isSelected ? 4 : 3,
              opacity: 0.95,
              dashArray: '8, 6'
            });

            line.bindPopup(popupHtml);
            line.on('click', () => onSelectWarning(warning));
            group.addLayer(line);

            // Terminus points
            const startMarker = L.circleMarker(latLngs[0], {
              radius: 5,
              fillColor: '#0284c7',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 1
            }).bindTooltip('Point A');
            const endMarker = L.circleMarker(latLngs[latLngs.length - 1], {
              radius: 5,
              fillColor: '#0284c7',
              color: '#ffffff',
              weight: 2,
              fillOpacity: 1
            }).bindTooltip('Point B');
            group.addLayer(startMarker);
            group.addLayer(endMarker);
          });

        corridors.forEach((corr) => {
          renderedSpatial = true;
          const polyPoints = corr.polygon || computeLineCorridor(corr.path, corr.width_nm);
          const latLngs = polyPoints.map((pt: [number, number]) => L.latLng(pt[1], pt[0]));
          latLngs.forEach((ll: L.LatLng) => bounds.push(ll));

          const corridorPoly = L.polygon(latLngs, {
            color: '#ca8a04',
            weight: 2,
            opacity: 0.85,
            fillColor: '#f59e0b',
            fillOpacity: 0.16,
            dashArray: '5, 5'
          });

          corridorPoly.bindPopup(popupHtml);
          corridorPoly.on('click', () => onSelectWarning(warning));
          group.addLayer(corridorPoly);
        });
      }

      // 4. Point Hazards & Glyphs
      if (plotFilter === 'all' || plotFilter === 'point') {
        if (!renderedSpatial || warning.category === 'aton' || warning.category === 'offshore' || warning.category === 'drifting') {
          if (warning.latitude !== null && warning.longitude !== null) {
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
        }
      }
    });

    if (bounds.length > 0 && !selectedWarning) {
      try {
        const lBounds = L.latLngBounds(bounds);
        map.fitBounds(lBounds, { padding: [40, 40], maxZoom: 8 });
      } catch {
        // Safe catch
      }
    }
  };

  useEffect(() => {
    renderGeometries();
  }, [warnings, activeNavarea, selectedWarning, plotFilter]);

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
    <div className="relative w-full h-full bg-[var(--surface-dark)] flex flex-col overflow-hidden rounded-xl border border-[var(--border)]">
      {/* Map Header / Controls overlay */}
      <div className="absolute top-2 left-2 right-2 z-[1000] flex flex-wrap md:flex-nowrap items-center justify-between gap-2 pointer-events-none">
        <div className="flex flex-wrap sm:flex-nowrap items-center gap-1.5 pointer-events-auto max-w-[calc(100%-110px)] md:max-w-none">
          <div className="hidden sm:inline-flex bg-[var(--surface)] px-2.5 py-1 rounded-lg border border-[var(--border)] text-xs font-medium text-[var(--text)] items-center gap-1.5 shadow-md shrink-0">
            <Compass className="w-3.5 h-3.5 text-[var(--verified)]" />
            <span className="hidden md:inline">WGS84 Chart</span>
            <span className="text-[var(--text-light)]">•</span>
            <span className="text-[var(--verified)] font-mono text-[11px]">
              {warnings.filter((w) => (activeNavarea === 'ALL' ? true : w.navarea === activeNavarea)).length} hazards
            </span>
          </div>

          {/* Plot type filter pills */}
          <div className="bg-[var(--surface)] p-1 rounded-lg border border-[var(--border)] flex items-center gap-1 shadow-md text-xs overflow-x-auto scrollbar-none max-w-full">
            <button
              onClick={() => setPlotFilter('all')}
              className={`px-2 py-0.5 rounded transition font-medium shrink-0 ${plotFilter === 'all' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'}`}
            >
              All
            </button>
            <button
              onClick={() => setPlotFilter('polygon')}
              className={`px-2 py-0.5 rounded transition font-medium shrink-0 ${plotFilter === 'polygon' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'}`}
            >
              ⬡ Poly
            </button>
            <button
              onClick={() => setPlotFilter('circle')}
              className={`px-2 py-0.5 rounded transition font-medium shrink-0 ${plotFilter === 'circle' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'}`}
            >
              ◯ Circle
            </button>
            <button
              onClick={() => setPlotFilter('line')}
              className={`px-2 py-0.5 rounded transition font-medium shrink-0 ${plotFilter === 'line' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'}`}
            >
              〰 Line
            </button>
            <button
              onClick={() => setPlotFilter('point')}
              className={`px-2 py-0.5 rounded transition font-medium shrink-0 ${plotFilter === 'point' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'}`}
            >
              ⚲ Point
            </button>
          </div>
        </div>

        {/* Top right basemap toggle & reset */}
        <div className="flex items-center gap-1.5 pointer-events-auto ml-auto shrink-0">
          <div className="bg-[var(--surface)] p-1 rounded-lg border border-[var(--border)] flex items-center gap-0.5 shadow-md">
            <button
              onClick={() => setMapTileStyle('voyager')}
              className={`px-1.5 py-1 text-xs rounded transition font-medium ${
                mapTileStyle === 'voyager' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'
              }`}
            >
              Voyager
            </button>
            <button
              onClick={() => setMapTileStyle('dark')}
              className={`px-1.5 py-1 text-xs rounded transition font-medium ${
                mapTileStyle === 'dark' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'
              }`}
            >
              Dark
            </button>
            <button
              onClick={() => setMapTileStyle('osm')}
              className={`px-1.5 py-1 text-xs rounded transition font-medium ${
                mapTileStyle === 'osm' ? 'bg-[var(--surface-dark)] text-white' : 'text-[var(--text-muted)]'
              }`}
            >
              OSM
            </button>
          </div>

          <button
            onClick={handleResetView}
            title="Reset Zoom"
            className="p-1.5 bg-[var(--surface)] text-[var(--text)] hover:bg-[var(--bg)] rounded-lg border border-[var(--border)] shadow-md transition"
          >
            <Maximize2 className="w-3.5 h-3.5" />
          </button>
        </div>
      </div>

      {/* Leaflet Map Div */}
      <div ref={mapContainerRef} className="w-full h-full z-0" />
    </div>
  );
};
