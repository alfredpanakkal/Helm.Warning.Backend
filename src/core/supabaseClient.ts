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
    const { data, error } = await client
      .from('nav_warnings')
      .select(
        'id, warning_id, publisher_id, source_id, navarea, series, source_warning_id, warning_number, warning_year, issued_at, issued_date, issued_text, valid_from, valid_to, status, status_basis, area_text, raw_text, spatial, coordinates, latitude, longitude, risk_level, severity, category, is_verified, verified_at, created_at'
      )
      .eq('status', 'active')
      .order('created_at', { ascending: false });

    if (error) {
      return { data: null, error: error.message };
    }
    return { data: (data as NavWarning[]) || [], error: null };
  } catch (e: any) {
    return { data: null, error: e?.message || 'Failed to fetch live warnings' };
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

/**
 * Fetch ingestion audit generations matching frontend contract
 */
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
    const records = warnings.map((w) => ({
      warning_id: w.warning_id,
      publisher_id: w.publisher_id || null,
      source_id: w.source_id,
      navarea: w.navarea,
      series: w.series || null,
      source_warning_id: w.source_warning_id || w.warning_id,
      warning_number: w.warning_number || null,
      warning_year: w.warning_year || null,
      issued_at: w.issued_at || (w.issued_date ? `${w.issued_date}T00:00:00Z` : null),
      issued_date: w.issued_date || null,
      issued_text: w.issued_text || null,
      valid_from: w.valid_from || null,
      valid_to: w.valid_to || null,
      status: w.status || 'active',
      status_basis: w.status_basis || 'official_notice',
      area_text: w.area_text || w.title || null,
      raw_text: w.raw_text,
      spatial: w.spatial || null,
      coordinates: w.coordinates || null,
      latitude: w.latitude,
      longitude: w.longitude,
      risk_level: w.risk_level || w.severity || 'moderate',
      severity: w.severity || 'moderate',
      category: w.category || 'general',
      is_verified: w.is_verified ?? true,
      verified_at: w.verified_at || new Date().toISOString(),
      created_at: w.created_at || new Date().toISOString()
    }));

    const { error } = await client
      .from('nav_warnings')
      .upsert(records, { onConflict: 'warning_id' });

    if (error) {
      return { success: false, count: 0, error: error.message };
    }

    return { success: true, count: records.length, error: null };
  } catch (e: any) {
    return { success: false, count: 0, error: e?.message || 'Upsert failed' };
  }
}
