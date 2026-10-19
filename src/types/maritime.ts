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

export type TriageTier = 'A' | 'B' | 'C';
export type DataQuality = 'EXPLICIT' | 'INFERRED' | 'AMBIGUOUS' | 'INVALID';
export type ParsingMethod = 'RULE' | 'AI';
export type SyncMode = 'live_feed' | 'static_corpus';

export interface TriageFields {
  data_quality: DataQuality;
  parsing_method: ParsingMethod;
  triage_tier: TriageTier;
  qa_flags: string[];
  unplotted_reason: string | null;
  duplicate_of_id: string | null;
}

export const TRIAGE_COLORS: Record<TriageTier, string> = {
  A: '#22c55e', // green — auto-plotted
  B: '#f59e0b', // amber — review queue
  C: '#ef4444' // red — blocked
};

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

export interface CoordinateProvenance {
  rawText: string;
  parser: 'rule' | 'ai_proposal';
  hemisphereExplicit: boolean;
  confidence?: number;
  reviewRequired: boolean;
  validationFlags: string[];
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
  canonical_id?: string;
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
  categories?: string[];
  is_verified?: boolean;
  verification?: VerificationState;
  verified_at?: string | null;
  cancels_ids?: string[];
  radio_frequencies?: string[];
  radio_communications?: Array<{
    band?: string;
    channel?: string;
    frequency?: number;
    unit?: string;
    service?: string;
  }>;
  space_launch_mission?: string | null;
  altitude_ceiling_fl?: number | null;
  shoal_depth_m?: number | null;
  is_depth_unknown?: boolean;
  tow_length_m?: number | null;
  tow_speed_kts?: number | null;
  applicable_vessel_filter?: string | null;
  created_at?: string;
}

export interface NavWarningGeometry {
  geom_id?: string;
  warning_id: string; // UUID FK
  zone_label?: string | null;
  feature_type: 'POINT' | 'LINE' | 'POLYGON' | 'CORRIDOR' | 'SWEEP_ARC' | 'BOUNDING_BOX';
  geom_postgis?: string; // WKT or geography representation
  buffer_nm: number;
  corridor_half_width_nm?: number | null;
  altitude_floor_m?: number;
  altitude_ceiling_fl?: number | null;
  sweep_start_azimuth?: number | null;
  sweep_end_azimuth?: number | null;
  sweep_radius_nm?: number | null;
  snapping_rule?: 'NONE' | 'COASTAL_CONTOUR';
  created_at?: string;
}

export interface NavWarningEntity {
  entity_id?: string;
  warning_id: string; // UUID FK
  entity_type: 'VESSEL' | 'OFFSHORE_RIG' | 'BUOY' | 'CABLE' | 'PIPELINE' | 'WRECK' | 'OBSTRUCTION';
  entity_name: string;
  role: 'PRIMARY' | 'LEAD_TUG' | 'BRAKE_TUG' | 'CHASE_BOAT' | 'GUARD_VESSEL' | 'CASUALTY' | 'STANDBY' | 'ATTENDANT';
  callsign?: string | null;
  mmsi?: string | null;
  tow_length_m?: number | null;
  tow_speed_kts?: number | null;
  streamer_count?: number | null;
  streamer_length_m?: number | null;
  streamer_breadth_m?: number | null;
  streamer_depth_m?: number | null;
  clearance_requested_nm?: number | null;
  depth_m?: number | null;
  depth_status?: 'MEASURED' | 'UNKNOWN' | 'APPROXIMATE' | 'DRYING' | null;
  datum_ref?: string;
  radio_channels?: Array<Record<string, unknown>>;
  created_at?: string;
}

export interface NavWarningChart {
  chart_id?: string;
  warning_id: string; // UUID FK
  authority?: string | null;
  chart_number: string;
  int_equivalent?: string | null;
  is_international: boolean;
  raw_citation?: string | null;
  created_at?: string;
}

export interface NavWarningSchedule {
  schedule_id?: string;
  warning_id: string; // UUID FK
  window_start: string;
  window_end: string;
  is_alternate: boolean;
  recurrence_rule?: string | null;
  days_of_week?: number[] | null;
  created_at?: string;
}

export interface NavWarningCancellation {
  id?: string;
  cancelling_warning_id: string; // UUID FK
  target_canonical_id: string;
  target_warning_id?: string | null;
  cancellation_type: 'EXPLICIT_NOTICE' | 'IN_FORCE_OMISSION' | 'PARAGRAPH_SELF_CANCEL';
  paragraph_ref?: string | null;
  created_at?: string;
}

export interface NavWarningAudit {
  audit_id?: string;
  warning_id: string; // UUID FK
  operator_id: string;
  previous_tier: string;
  new_tier: string;
  action: string;
  reason?: string | null;
  signature_hash: string;
  diff_patch?: Record<string, unknown>;
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
