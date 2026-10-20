import { createClient, SupabaseClient } from '@supabase/supabase-js';
import {
  NavWarning,
  RawMessage,
  SourceRegistryRecord,
  IngestionGenerationRecord
} from '../types/maritime';

const STORAGE_KEY_URL = 'HELM_SUPABASE_URL';
const STORAGE_KEY_KEY = 'HELM_SUPABASE_KEY';

// Environment Variable Fallback Ladder matching frontend specification:
// URL: VITE_SUPABASE_URL || SUPABASE_URL
// Key: VITE_SUPABASE_ANON_KEY || SUPABASE_ANON_KEY || SUPABASE_KEY || SUPABASE_PUBLISHABLE_KEY
const env = ((typeof import.meta !== 'undefined' && (import.meta as any).env) || {}) as Record<string, string | undefined>;

const DEFAULT_URL = env.VITE_SUPABASE_URL || env.SUPABASE_URL || '';
const DEFAULT_KEY =
  env.VITE_SUPABASE_ANON_KEY ||
  env.SUPABASE_ANON_KEY ||
  env.SUPABASE_KEY ||
  env.SUPABASE_PUBLISHABLE_KEY ||
  '';

let cachedClient: SupabaseClient | null = null;
let currentUrl = '';
let currentKey = '';

export function getStoredSupabaseCredentials(): { url: string; key: string } {
  const url = localStorage.getItem(STORAGE_KEY_URL) || DEFAULT_URL;
  const key = localStorage.getItem(STORAGE_KEY_KEY) || DEFAULT_KEY;
  return { url, key };
}

export function saveStoredSupabaseCredentials(url: string, key: string) {
  localStorage.setItem(STORAGE_KEY_URL, url);
  localStorage.setItem(STORAGE_KEY_KEY, key);
  cachedClient = null; // force re-instantiation
}

export function getSupabaseClient(): SupabaseClient | null {
  const { url, key } = getStoredSupabaseCredentials();
  if (!url || !key || url.includes('mock-') || !url.startsWith('http')) return null;

  if (!cachedClient || currentUrl !== url || currentKey !== key) {
    try {
      cachedClient = createClient(url, key, {
        auth: {
          persistSession: true,
          autoRefreshToken: true
        }
      });
      currentUrl = url;
      currentKey = key;
    } catch (e) {
      console.error('Failed to create Supabase client:', e);
      return null;
    }
  }
  return cachedClient;
}

export interface SupabaseHealthCheck {
  success: boolean;
  message: string;
  latencyMs: number;
}

export async function testSupabaseConnection(): Promise<SupabaseHealthCheck> {
  const client = getSupabaseClient();
  if (!client) {
    return {
      success: false,
      message: 'Standalone operational mode (configure Supabase credentials in System)',
      latencyMs: 0
    };
  }

  const start = performance.now();
  try {
    const { error } = await client
      .from('nav_warnings')
      .select('count', { count: 'exact', head: true });

    const latencyMs = Math.round(performance.now() - start);

    if (error) {
      return {
        success: false,
        message: `Response from host: ${error.message}`,
        latencyMs
      };
    }

    return {
      success: true,
      message: `Connected to Supabase PostgreSQL (${latencyMs}ms)`,
      latencyMs
    };
  } catch (err: any) {
    const latencyMs = Math.round(performance.now() - start);
    return {
      success: false,
      message: err?.message || 'Network error reaching Supabase endpoint',
      latencyMs
    };
  }
}

/**
 * Fetch active Navigational Warnings matching frontend query schema:
 * .select('id, warning_id, publisher_id, source_id, navarea, series, source_warning_id, warning_number, warning_year, issued_at, issued_date, issued_text, valid_from, valid_to, status, status_basis, area_text, raw_text, spatial, coordinates, latitude, longitude, risk_level, severity, category, is_verified, verified_at, created_at')
 * .eq('status', 'active')
 * .order('created_at', { ascending: false })
 */
export async function fetchLiveNavWarnings(): Promise<{
  data: NavWarning[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    // PRIMARY SOURCE: the spatial view is authoritative
    // (INNER JOIN master + geometries; filters status='active' AND triage_tier='A')
    const { data: viewData, error: viewError } = await client
      .from('nav_warnings_active_spatial')
      .select('*');

    let rows: any[] = [];
    if (!viewError && Array.isArray(viewData) && viewData.length > 0) {
      rows = viewData;
    } else {
      // FALLBACK: base-table path for deployments predating the spatial view
      if (viewError) {
        console.warn('Spatial view unavailable, falling back to nav_warnings:', viewError.message);
      }
      const { data: baseData, error: baseError } = await client
        .from('nav_warnings')
        .select('*')
        .eq('status', 'active')
        .order('created_at', { ascending: false });
      if (baseError) {
        return { data: null, error: baseError.message };
      }
      rows = (baseData as any[]) || [];
    }

    const normalized = rows.map((w) => {
      const canonical = w.canonical_id || w.warning_id;

      // View rows carry geojson_blob (jsonb produced by ST_AsGeoJSON)
      const blob = w.geojson_blob ?? w.spatial;
      let spatial = blob;
      let lat: number | null = w.latitude ?? null;
      let lon: number | null = w.longitude ?? null;

      if (blob && blob.type === 'Point' && Array.isArray(blob.coordinates)) {
        lon = blob.coordinates[0];
        lat = blob.coordinates[1];
      } else if (blob && blob.type === 'Polygon' && blob.coordinates?.[0]?.[0]) {
        lon = blob.coordinates[0][0][0];
        lat = blob.coordinates[0][0][1];
      }

      const categories =
        Array.isArray(w.categories) && w.categories.length > 0
          ? w.categories
          : w.category
          ? [w.category]
          : ['general'];

      return {
        ...w,
        warning_id: canonical || w.warning_id,
        canonical_id: canonical,
        title: w.title || canonical,
        area_text: w.area_text || w.title,
        spatial,
        latitude: lat,
        longitude: lon,
        categories,
        category: categories[0] || 'general',
        triage_tier: w.triage_tier || 'A',
        status: w.status || 'active'
      };
    });

    return { data: normalized as NavWarning[], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch live warnings' };
  }
}


/**
 * Fetch PostGIS-rendered active spatial warnings from the new spatial view
 */
export async function fetchActiveSpatialWarnings(): Promise<{
  data: any[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    const { data, error } = await client
      .from('nav_warnings_active_spatial')
      .select('*');

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: data || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch spatial view' };
  }
}

/**
 * Fetch warnings requiring human triage from the new review queue view
 */
export async function fetchReviewQueueWarnings(): Promise<{
  data: any[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    const { data, error } = await client
      .from('nav_warnings_review_queue')
      .select('*');

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: data || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch review queue' };
  }
}

/**
 * Fetch sources registry matching frontend contract
 */
export async function fetchLiveSourcesRegistry(): Promise<{
  data: SourceRegistryRecord[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    const { data, error } = await client
      .from('sources_registry')
      .select(
        'source_id, publisher_name, navarea, format, languages, parser_id, entrypoints, poll_interval_sec, is_active, last_run_at, last_status, active_warnings_count'
      )
      .order('source_id', { ascending: true });

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: (data as SourceRegistryRecord[]) || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch sources registry' };
  }
}

export async function fetchLiveIngestionGenerations(): Promise<{
  data: IngestionGenerationRecord[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    const { data, error } = await client
      .from('ingestion_generations')
      .select(
        'generation_id, source_id, started_at, completed_at, status, parsed_count, active_count, evidence_hash'
      )
      .order('started_at', { ascending: false });

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: (data as IngestionGenerationRecord[]) || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch ingestion generations' };
  }
}

export async function fetchLiveRawMessages(): Promise<{
  data: RawMessage[] | null;
  error: string | null;
}> {
  const client = getSupabaseClient();
  if (!client) {
    return { data: null, error: 'No client initialized' };
  }

  try {
    const { data, error } = await client
      .from('raw_messages')
      .select('*')
      .order('received_timestamp', { ascending: false });

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: (data as RawMessage[]) || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch raw messages' };
  }
}

/**
 * Upsert warnings into public.nav_warnings adhering to the shared schema
 */
export async function upsertNavWarnings(
  warnings: NavWarning[]
): Promise<{ success: boolean; count: number; error: string | null }> {
  const client = getSupabaseClient();
  if (!client) {
    return { success: false, count: 0, error: 'No client initialized' };
  }

  try {
    // Build schema-compliant payloads for the atomic upsert_nav_warning RPC.
    // Writes only columns that exist in the 20261019/20261020 schema
    // (no severity/latitude/longitude/spatial/issued_text/category).
    const payloads = warnings.map((w) => ({
      master: {
        canonical_id: w.canonical_id || w.warning_id,
        navarea: w.navarea || '',
        title: w.title || w.warning_id,
        area_text: w.area_text || w.title || null,
        categories: w.categories || (w.category ? [w.category] : []),
        status: w.status || 'active',
        triage_tier: w.triage_tier || 'C',
        data_quality: w.data_quality || 'EXPLICIT',
        parsing_method: 'RULE',
        qa_flags: [],
        valid_from: w.valid_from || null,
        valid_to: w.valid_to || null,
        raw_text: w.raw_text || '',
        source_id: w.source_id || 'frontend-manual',
        unplotted_reason: null
      },
      geometries: [] // manual frontend entries carry no geometry unless drawn
    }));

    for (const p of payloads) {
      const { error } = await client.rpc('upsert_nav_warning', { p_payload: p });
      if (error) {
        return { success: false, count: 0, error: error.message };
      }
    }

    return { success: true, count: payloads.length, error: null };
  } catch (e: any) {
    return { success: false, count: 0, error: e?.message || 'Upsert failed' };
  }
}

/**
 * Subscribe to realtime changes on nav_warnings and nav_warning_geometries base tables.
 * Dispatches callback when records are inserted, updated, or deleted.
 * Returns unsubscribe cleanup function.
 */
export function subscribeToNavWarningChanges(onChange: () => void): () => void {
  const client = getSupabaseClient();
  if (!client) return () => {};

  try {
    const channel = client
      .channel('nav_warnings_realtime_dual')
      .on(
        'postgres_changes' as any,
        { event: '*', schema: 'public', table: 'nav_warnings' },
        () => {
          onChange();
        }
      )
      .on(
        'postgres_changes' as any,
        { event: '*', schema: 'public', table: 'nav_warning_geometries' },
        () => {
          onChange();
        }
      )
      .subscribe();

    return () => {
      try {
        client.removeChannel(channel);
      } catch {
        // channel teardown
      }
    };
  } catch {
    return () => {};
  }
}

