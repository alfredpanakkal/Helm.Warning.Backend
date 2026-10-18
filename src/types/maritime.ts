export type HazardCategory =
  | 'electronic'
  | 'military'
  | 'aton'
  | 'subsea'
  | 'drifting'
  | 'offshore'
  | 'general';

export type SeverityLevel = 'critical' | 'high' | 'moderate' | 'general';

export type VerificationState =
  | 'verified'
  | 'inferred'
  | 'needs_review'
  | 'rejected'
  | 'explicit'
  | 'ambiguous';

export type NavareaCode =
  | 'NA I'
  | 'NA II'
  | 'NA III'
  | 'NA IV'
  | 'NA V'
  | 'NA VI'
  | 'NA VII'
  | 'NA VIII'
  | 'NA IX'
  | 'NA X'
  | 'NA XI'
  | 'NA XII'
  | 'NA XIII'
  | 'NA XIV'
  | 'NA XV'
  | 'NA XVI'
  | 'NA XVII'
  | 'NA XVIII'
  | 'NA XIX'
  | 'NA XX'
  | 'NA XXI'
  | 'Baltic';

export type NavareaRegion = NavareaCode | string;

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

export interface SpatialCircle {
  center: [number, number]; // [lon, lat]
  radius_nm: number;
  label?: string;
}

export interface SpatialCorridor {
  path: [number, number][]; // [lon, lat] sequence
  width_nm: number;
  label?: string;
  polygon?: [number, number][]; // computed closed polygon [lon, lat]
}

export interface DriftVector {
  origin: [number, number]; // [lon, lat]
  bearing_deg: number;
  speed_knots?: number;
  label?: string;
}

export type PlotType = 'point' | 'polygon' | 'circle' | 'line' | 'corridor';

export interface SpatialBundle {
  geometries?: GeoJsonGeometry[];
  circles?: SpatialCircle[];
  corridors?: SpatialCorridor[];
  driftVectors?: DriftVector[];
}

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
  raw_artifact_ref?: string;
}

export interface NavWarning {
  id?: string;
  warning_id: string;
  publisher_id?: string | null;
  source_id: string;
  navarea: NavareaRegion;
  series?: string | null;
  source_warning_id?: string | null;
  warning_number?: number | string | null;
  warning_year?: number | string | null;
  issued_at?: string | null;
  issued_date?: string | null; // YYYY-MM-DD
  issued_text?: string | null;
  valid_from?: string | null;
  valid_to?: string | null;
  status: WarningStatus | 'expired' | 'superseded' | 'rejected' | 'unverified' | 'unknown';
  status_basis?: string | null;
  data_quality?: 'EXPLICIT' | 'INFERRED' | 'AMBIGUOUS' | 'INVALID';
  verification_status?: 'unverified' | 'human_verified';
  triage_tier?: 'A' | 'B' | 'C';
  qa_flags?: string[];
  unplottedReason?:
    | 'no_coordinates'
    | 'parse_failure'
    | 'meta_list'
    | 'text_unavailable'
    | 'empty_stub'
    | 'cancellation_only'
    | 'truncated_clause'
    | 'missing_hemisphere'
    | 'duplicate_of'
    | null;
  proposed_cancel?: boolean;
  resolutionRule?: string;
  resolutionRefs?: string[];
  spanEditList?: Array<[number, number, number, number, string]>;
  area_text?: string | null;
  title: string;
  raw_text: string;
  spatial?: GeoJsonGeometry | SpatialBundle | null;
  coordinates?: string | null;
  latitude: number | null;
  longitude: number | null;
  risk_level?: string | null;
  severity?: SeverityLevel;
  category: HazardCategory;
  is_verified?: boolean;
  verification?: VerificationState;
  verified_at?: string | null;
  cancels_ids?: string[];
  created_at?: string;
}

export interface SourceRegistryRecord {
  source_id: string;
  publisher_name: string;
  navarea: string;
  format: string;
  languages: string[];
  parser_id: string;
  entrypoints: string[];
  poll_interval_sec: number;
  is_active: boolean;
  last_run_at: string | null;
  last_status: string | null;
  active_warnings_count: number;
}

export interface IngestionGenerationRecord {
  generation_id: string;
  source_id: string;
  started_at: string;
  completed_at: string | null;
  status: 'running' | 'success' | 'failed' | 'partial';
  parsed_count: number;
  active_count: number;
  evidence_hash: string | null;
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

export interface SourceFeed {
  id: string;
  name: string;
  region: string;
  navarea: NavareaRegion;
  authority: string;
  url: string;
  schedule: string;
  activeCount: number;
  status: 'operational' | 'degraded' | 'syncing';
  lastPolled: string;
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

export interface SupabaseConfig {
  url: string;
  anonKey: string;
  isConnected: boolean;
  lastChecked: string | null;
  errorMessage: string | null;
  isConnecting: boolean;
}
