export type HazardCategory =
  | 'electronic'
  | 'military'
  | 'aton'
  | 'subsea'
  | 'drifting'
  | 'offshore'
  | 'general';

export type NavareaRegion = 'Baltic' | 'I' | 'XI';

export type WarningStatus = 'active' | 'cancelled';

export interface RawCoordinate {
  latDeg: string;
  latMin: string;
  latSec?: string;
  latDir: string;
  lonDeg: string;
  lonMin: string;
  lonSec?: string;
  lonDir: string;
  rawString: string;
  latDecimal: number;
  lonDecimal: number;
}

export type GeoJsonGeometry =
  | { type: 'Point'; coordinates: [number, number] } // [lon, lat]
  | { type: 'LineString'; coordinates: [number, number][] }
  | { type: 'Polygon'; coordinates: [number, number][][] };

export interface SpatialFeature {
  warning_id: string;
  category: HazardCategory;
  geometry: GeoJsonGeometry;
}

export interface RawMessage {
  warning_id: string;
  source_id: string;
  subject_header: string;
  full_raw_text: string;
  received_timestamp: string;
  checksum_sha256: string;
}

export interface NavWarning {
  warning_id: string;
  source_id: string;
  navarea: NavareaRegion | string;
  title: string;
  issued_text: string | null;
  coordinates: string | null;
  latitude: number | null;
  longitude: number | null;
  category: HazardCategory;
  status: WarningStatus;
  raw_text: string;
  spatial?: GeoJsonGeometry | null;
}

export interface ParsedData {
  raw_messages: RawMessage[];
  nav_warnings: NavWarning[];
  spatial_features: SpatialFeature[];
}

export interface DifferentialResult {
  skip: string[];
  new: Array<{ warn: NavWarning; msg: RawMessage }>;
  update: Array<{ warn: NavWarning; msg: RawMessage }>;
  cancel: string[];
}

export interface PipelineInfo {
  id: string;
  name: string;
  navarea: NavareaRegion;
  sourceId: string;
  sourceAuthority: string;
  sourceUrl: string;
  schedule: string;
  description: string;
}

export interface PipelineExecutionLog {
  id: string;
  timestamp: string;
  pipelineId: string;
  pipelineName: string;
  status: 'running' | 'success' | 'failed';
  harvestCount: number;
  diff: {
    skipped: number;
    newAdded: number;
    updated: number;
    cancelled: number;
  };
  durationMs: number;
  outputMessages: string[];
}
