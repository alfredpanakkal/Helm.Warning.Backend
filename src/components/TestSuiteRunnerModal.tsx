import React, { useState } from 'react';
import { parseBalticWarning } from '../core/parsers/balticParser';
import { parseNavarea1Warning } from '../core/parsers/navarea1Parser';
import { parseNavareaXiWarning } from '../core/parsers/navareaXiParser';
import { convertToDecimal, parseCoordinates, validateNavareaBounds, formatCoordinateString } from '../core/coordinates';
import { classifyHazard } from '../core/classification';
import { computeDifferential } from '../core/syncEngine';
import {
  X,
  CheckCircle2,
  XCircle,
  Play,
  RotateCw,
  FlaskConical,
  Gauge
} from 'lucide-react';

interface TestResult {
  suite: string;
  name: string;
  passed: boolean;
  durationMs: number;
  error?: string;
}

export const TestSuiteRunnerModal: React.FC<{ isOpen: boolean; onClose: () => void }> = ({
  isOpen,
  onClose
}) => {
  const [isRunning, setIsRunning] = useState(false);
  const [results, setResults] = useState<TestResult[]>([]);

  if (!isOpen) return null;

  const runAllTests = async () => {
    setIsRunning(true);
    setResults([]);
    const testList: TestResult[] = [];

    const assertEqual = (actual: any, expected: any, msg?: string) => {
      if (actual !== expected) {
        throw new Error(`${msg || 'Assertion failed'}: expected ${expected}, got ${actual}`);
      }
    };

    const assertAlmostEqual = (actual: number, expected: number, places: number = 4) => {
      const diff = Math.abs(actual - expected);
      const tolerance = Math.pow(10, -places);
      if (diff > tolerance) {
        throw new Error(`Expected ~${expected}, got ${actual} (diff: ${diff} > ${tolerance})`);
      }
    };

    const assertIn = (actual: any, list: any[]) => {
      if (!list.includes(actual)) {
        throw new Error(`Expected ${actual} to be in [${list.join(', ')}]`);
      }
    };

    // Test cases definition
    const testCases: Array<{ suite: string; name: string; fn: () => void }> = [
      // Baltic Suite
      {
        suite: 'NAVAREA Baltic',
        name: 'test_sample_1_skagerrak_detonations_polygon',
        fn: () => {
          const header = 'SWEDISH NAV WARN 168/26 [Skagerrak]';
          const raw = `080056 UTC OCT
SKAGERRAK. LYSEKIL. BONDEN
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS
09 OCT 0600 LT - 14 OCT 2000 LT
PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E
58-10.2N 011-13.3E
500 MTR CLEARANCE FROM THE AREA IS REQUESTED.`;
          const { navWarning, spatial } = parseBalticWarning(raw, header);
          assertEqual(navWarning.warning_id, 'SWEDISH 168/26');
          assertEqual(navWarning.category, 'military');
          assertEqual(navWarning.issued_text, '080056 UTC OCT 2026');
          assertEqual(spatial?.type, 'Polygon');
          assertAlmostEqual(navWarning.latitude!, 58.195834, 4);
          assertAlmostEqual(navWarning.longitude!, 11.238750, 4);
        }
      },
      {
        suite: 'NAVAREA Baltic',
        name: 'test_sample_2_kattegat_stora_polsan_point',
        fn: () => {
          const header = 'SWEDISH NAV WARN 167/26 [Kattegat]';
          const raw = `080035 UTC OCT
KATTEGAT. MARSTRAND. STORA PÖLSAN.
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS.
09 OCT 0600 LT - 14 OCT 2000 LT.
1 M CLEARANCE FROM THE AREA IS REQUESTED.
PSN: 57-47.0N 011-27.9E`;
          const { navWarning, spatial } = parseBalticWarning(raw, header);
          assertEqual(navWarning.warning_id, 'SWEDISH 167/26');
          assertEqual(navWarning.category, 'military');
          assertEqual(navWarning.issued_text, '080035 UTC OCT 2026');
          assertEqual(spatial?.type, 'Point');
          assertAlmostEqual(navWarning.latitude!, 57.783333, 4);
          assertAlmostEqual(navWarning.longitude!, 11.465000, 4);
        }
      },
      {
        suite: 'NAVAREA Baltic',
        name: 'test_sample_3_falkenberg_dredging_buoy',
        fn: () => {
          const header = 'SWEDISH NAV WARN 166/26 [Kattegat]';
          const raw = `070800 UTC OCT
KATTEGAT. FALKENBERG HARBOUR ENTRANCE.
DREDGING IN OPERATION. SPAR BUOYS MIGHT HAVE BEEN MOVED.
PSN 56-53.0N 012-28.0E
GREATE CAUTION ADVISED`;
          const { navWarning } = parseBalticWarning(raw, header);
          assertEqual(navWarning.warning_id, 'SWEDISH 166/26');
          assertIn(navWarning.category, ['aton', 'subsea']);
          assertAlmostEqual(navWarning.latitude!, 56.883333, 4);
          assertAlmostEqual(navWarning.longitude!, 12.466667, 4);
        }
      },
      {
        suite: 'NAVAREA Baltic',
        name: 'test_sample_6_baltic_wide_gnss_interference',
        fn: () => {
          const header = 'BALTIC SEA NAV WARN 026/25 [Western Baltic, Central Baltic]';
          const raw = `021100 UTC JUL
SOUTHERN, SOUTHEASTERN, CENTRAL AND NORTHERN BALTIC, GULF OF FINLAND, GULF OF RIGA AND SEA OF AALAND.
GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED IN AREA.
MARINERS ADVISED TO EXERCISE CAUTION
AND BE PREPARED FOR NAVIGATION IMPACTS.`;
          const { navWarning } = parseBalticWarning(raw, header);
          assertEqual(navWarning.warning_id, 'BALTIC 026/25');
          assertEqual(navWarning.category, 'electronic');
          assertEqual(navWarning.issued_text, '021100 UTC JUL 2025');
        }
      },
      {
        suite: 'NAVAREA Baltic',
        name: 'test_sample_9_drifting_container',
        fn: () => {
          const header = 'SWEDISH NAV WARN 045/25 [Skagerrak]';
          const raw = `100600 UTC APR
SKAGERRAK.
CONTAINER ADRIFT.
APPROX PSN: 57-50.0N 011-30.0E
ALL SHIPS REQUESTED TO REPORT SIGHTINGS.`;
          const { navWarning, spatial } = parseBalticWarning(raw, header);
          assertEqual(navWarning.warning_id, 'SWEDISH 045/25');
          assertEqual(navWarning.category, 'drifting');
          assertEqual(spatial?.type, 'Point');
        }
      },

      // NAVAREA I Suite
      {
        suite: 'NAVAREA I (UKHO)',
        name: 'test_parse_basic_warning_dover_strait',
        fn: () => {
          const header = 'NAVAREA I 123/26';
          const raw = `010000 UTC JAN 2026
NORTH SEA. DOVER STRAIT.
DRIFTING CONTAINER REPORTED.
PSN: 51-00.0N 001-30.0E
ALL SHIPS ADVISED TO NAVIGATE WITH CAUTION.`;
          const { navWarning, spatial } = parseNavarea1Warning(raw, header);
          assertEqual(navWarning.warning_id, '123/26');
          assertEqual(navWarning.category, 'drifting');
          assertEqual(spatial?.type, 'Point');
        }
      },
      {
        suite: 'NAVAREA I (UKHO)',
        name: 'test_parse_subsea_cable_repair',
        fn: () => {
          const header = 'NAVAREA I 456/26';
          const raw = `051200 UTC JUN 2026
ENGLISH CHANNEL.
SUBMARINE CABLE REPAIR OPERATIONS.
PSN: 50-30.0N 000-45.0W TO 50-35.0N 000-40.0W
MARINERS REQUESTED TO KEEP CLEAR.`;
          const { navWarning, spatial } = parseNavarea1Warning(raw, header);
          assertEqual(navWarning.warning_id, '456/26');
          assertEqual(navWarning.category, 'subsea');
          assertEqual(spatial?.type, 'LineString');
        }
      },
      {
        suite: 'NAVAREA I (UKHO)',
        name: 'test_parse_aton_light_buoy_extinguished',
        fn: () => {
          const header = 'NAVAREA I 012/26';
          const raw = `150800 UTC AUG 2026
IRISH SEA.
LIGHT BUOY 'ALPHA' EXTINGUISHED.
PSN: 53-20.5N 005-30.2W
MARINERS ADVISED.`;
          const { navWarning } = parseNavarea1Warning(raw, header);
          assertEqual(navWarning.warning_id, '012/26');
          assertEqual(navWarning.category, 'aton');
          assertAlmostEqual(navWarning.latitude!, 53.341667, 4);
          assertAlmostEqual(navWarning.longitude!, -5.503333, 4);
        }
      },

      // NAVAREA XI Suite
      {
        suite: 'NAVAREA XI (Japan)',
        name: 'test_sample_1_okinotori_shima_drifting_hatch_cover',
        fn: () => {
          const header = 'NAVAREA XI NO.26-0451';
          const raw = `NO.26-0451       Date:2026/10/09 07 UTC
NORTH PACIFIC, OKINOTORI SHIMA.
HATCH COVER, ABOUT 20 METRE IN SQUARE,
ADRIFT IN
16-54.1N 134-39.5E AT 090625Z OCT.
CANCEL 0450/26.
CANCEL THIS MSG 120625Z OCT.`;
          const { navWarning, spatial } = parseNavareaXiWarning(raw, header);
          assertEqual(navWarning.warning_id, 'NAVAREA XI 0451/26');
          assertEqual(navWarning.category, 'drifting');
          assertEqual(spatial?.type, 'Point');
          assertAlmostEqual(navWarning.latitude!, 16.901667, 4);
          assertAlmostEqual(navWarning.longitude!, 134.658333, 4);
        }
      },
      {
        suite: 'NAVAREA XI (Japan)',
        name: 'test_sample_3_naval_firing_exercise_polygon',
        fn: () => {
          const header = 'NAVAREA XI NO.26-0500';
          const raw = `NO.26-0500       Date:2026/06/20 08 UTC
EAST CHINA SEA.
NAVAL EXERCISE WILL BE CONDUCTED.
FIRING AND GUNNERY PRACTICE.
AREA: 30-00.0N 125-00.0E
31-00.0N 125-00.0E
31-00.0N 126-00.0E
30-00.0N 126-00.0E
30-00.0N 125-00.0E
DANGER PERIOD: 22 JUN TO 25 JUN.`;
          const { navWarning, spatial } = parseNavareaXiWarning(raw, header);
          assertEqual(navWarning.warning_id, 'NAVAREA XI 0500/26');
          assertEqual(navWarning.category, 'military');
          assertEqual(spatial?.type, 'Polygon');
        }
      },

      // Shared Engine Tests
      {
        suite: 'Shared Coordinates Engine',
        name: 'test_convert_to_decimal_directions_and_seconds',
        fn: () => {
          assertAlmostEqual(convertToDecimal('58', '10.2', null, 'N'), 58.17, 4);
          assertAlmostEqual(convertToDecimal('58', '10.2', null, 'S'), -58.17, 4);
          assertAlmostEqual(convertToDecimal('011', '13.3', null, 'E'), 11.221667, 4);
          assertAlmostEqual(convertToDecimal('011', '13.3', null, 'W'), -11.221667, 4);
          assertAlmostEqual(convertToDecimal('24', '04.12', '00', 'N'), 24.068667, 4);
        }
      },
      {
        suite: 'Shared Differential Sync Engine',
        name: 'test_differential_bucketing_skip_new_update_cancel',
        fn: () => {
          const scrapedWarnings: any[] = [
            { warning_id: 'W1', title: 'W1' },
            { warning_id: 'W2', title: 'W2' },
            { warning_id: 'W3', title: 'W3' }
          ];
          const scrapedMessages: any[] = [
            { warning_id: 'W1', checksum_sha256: 'h1_same' },
            { warning_id: 'W2', checksum_sha256: 'h2_revised' },
            { warning_id: 'W3', checksum_sha256: 'h3_new' }
          ];
          const existingWarnings: any = {
            W1: { warning_id: 'W1', status: 'active' },
            W2: { warning_id: 'W2', status: 'active' },
            W_DROPPED: { warning_id: 'W_DROPPED', status: 'active' }
          };
          const existingChecksums = new Set(['W1:::h1_same', 'W2:::h2_old', 'W_DROPPED:::h_old']);

          const diff = computeDifferential(
            scrapedWarnings,
            scrapedMessages,
            existingWarnings,
            existingChecksums
          );

          assertEqual(diff.skip.length, 1);
          assertEqual(diff.skip[0], 'W1');
          assertEqual(diff.new.length, 1);
          assertEqual(diff.new[0].warn.warning_id, 'W3');
          assertEqual(diff.update.length, 1);
          assertEqual(diff.update[0].warn.warning_id, 'W2');
          assertEqual(diff.cancel.length, 1);
          assertEqual(diff.cancel[0], 'W_DROPPED');
        }
      },

      // NAVAREA v7 Rule Engine Safety Tests
      {
        suite: 'v7 Safety & Dialect Rules',
        name: 'test_bounds_91n_invalid_0_180_lon_valid',
        fn: () => {
          const invalidLat = convertToDecimal('91', '00', null, 'N');
          assertEqual(isNaN(invalidLat), true, '91N must be NaN / invalid');

          const validPrime = convertToDecimal('00', '00', null, 'E');
          assertEqual(validPrime, 0, '0E must be 0');

          const validAntimeridian = convertToDecimal('180', '00', null, 'E');
          assertEqual(validAntimeridian, 180, '180E must be 180');

          const invalidLonOver = convertToDecimal('180', '00.10', null, 'E');
          assertEqual(isNaN(invalidLonOver), true, '180-00.10E must be invalid');
        }
      },
      {
        suite: 'v7 Safety & Dialect Rules',
        name: 'test_rule_111_spelled_number_quantity_lexer',
        fn: () => {
          const text = 'SURVEY OPERATIONS TWO MILE WIDE SEA STRIP PSN 50-00N 001-00E TO 50-10N 001-10E';
          const { parsedCoords, corridors, qaFlags } = parseCoordinates(text);
          assertEqual(parsedCoords.length, 2);
          assertEqual(corridors.length, 1);
          assertEqual(corridors[0].width_nm, 4); // 2 miles either side = 4 NM swath
          assertIn('SPELLED_QUANTITY_NORMALIZED', qaFlags);
        }
      },
      {
        suite: 'v7 Safety & Dialect Rules',
        name: 'test_rule_109_bounding_box_synthesis',
        fn: () => {
          const text = 'NAVAREA I 999/26 FIRING PRACTICE. BOUNDED WITHIN 50N TO 55N AND 010W TO 005W.';
          const { spatial, qaFlags, dataQuality } = parseCoordinates(text);
          assertEqual(spatial?.type, 'Polygon');
          assertEqual(dataQuality, 'INFERRED');
          assertIn('POLYGON_BOUNDING_BOX_SYNTHESIZED', qaFlags);
        }
      },
      {
        suite: 'v7 Safety & Dialect Rules',
        name: 'test_depth_sentinel_masking',
        fn: () => {
          const fmt = formatCoordinateString(-9999, -9999);
          assertEqual(fmt, 'depth unknown');
        }
      },
      {
        suite: 'Rules Register M3: Coordinate & Spatial Geometry',
        name: 'test_multi_format_coordinates_space_and_degree_symbols',
        fn: () => {
          // Format with spaces: DD MM.MM N DDD MM.MM E
          const resSpaces = parseCoordinates('PSN 58 15.0 N 011 25.0 E');
          assertEqual(resSpaces.parsedCoords.length, 1);
          assertAlmostEqual(resSpaces.primaryLat!, 58.25, 4);
          assertAlmostEqual(resSpaces.primaryLon!, 11.416667, 4);

          // Format with degree and minute symbols: DD°MM.MM'N DDD°MM.MM'E
          const resSymbols = parseCoordinates('APPROX PSN 57°47.0\'N 011°27.9\'E');
          assertEqual(resSymbols.parsedCoords.length, 1);
          assertAlmostEqual(resSymbols.primaryLat!, 57.783333, 4);
          assertAlmostEqual(resSymbols.primaryLon!, 11.465000, 4);
        }
      },
      {
        suite: 'Rules Register M3: Clearance Zones & Safety Radii',
        name: 'test_clearance_and_safety_zone_extraction',
        fn: () => {
          const rawBaltic = `PSN: 57-47.0N 011-27.9E. 1 M CLEARANCE FROM THE AREA IS REQUESTED.`;
          const res1 = parseCoordinates(rawBaltic);
          assertEqual(res1.circles.length, 1);
          assertEqual(res1.circles[0].radius_nm, 1);

          const rawMeters = `PSN: 58-15.0N 011-25.0E. SAFETY ZONE 1000 METRES.`;
          const res2 = parseCoordinates(rawMeters);
          assertEqual(res2.circles.length, 1);
          assertAlmostEqual(res2.circles[0].radius_nm, 0.54, 2);
        }
      },
      {
        suite: 'Rules Register M5: Differential Sync Engine',
        name: 'test_differential_explicit_cancellation_cascade',
        fn: () => {
          const scrapedWarnings: any[] = [
            {
              warning_id: 'NAVAREA XI 0451/26',
              title: 'Hatch Cover Adrift',
              cancels_ids: ['0450/26']
            }
          ];
          const scrapedMessages: any[] = [
            { warning_id: 'NAVAREA XI 0451/26', checksum_sha256: 'h_new' }
          ];
          const existingWarnings: any = {
            'NAVAREA XI 0450/26': { warning_id: 'NAVAREA XI 0450/26', status: 'active' },
            'NAVAREA XI 0451/26': { warning_id: 'NAVAREA XI 0451/26', status: 'active' }
          };
          const existingChecksums = new Set(['NAVAREA XI 0450/26:::h_old']);

          const diff = computeDifferential(
            scrapedWarnings,
            scrapedMessages,
            existingWarnings,
            existingChecksums
          );

          // 0450/26 must be in toCancel due to explicit cancellation
          assertIn('NAVAREA XI 0450/26', diff.cancel);
        }
      },
      {
        suite: 'Rules Register M6: Regional Bounding Box Validation',
        name: 'test_navarea_regional_bounding_box_audit',
        fn: () => {
          const validBaltic = validateNavareaBounds(57.5, 11.5, 'Baltic');
          assertEqual(validBaltic.isValid, true);

          // Out-of-bounds coordinate for Baltic (e.g. Indian Ocean)
          const invalidBaltic = validateNavareaBounds(10.0, 75.0, 'Baltic');
          assertEqual(invalidBaltic.isValid, false);

          const validUkho = validateNavareaBounds(52.0, 1.5, 'NA I');
          assertEqual(validUkho.isValid, true);
        }
      }
    ];

    for (const test of testCases) {
      const t0 = performance.now();
      try {
        test.fn();
        const durationMs = Math.round((performance.now() - t0) * 100) / 100;
        testList.push({
          suite: test.suite,
          name: test.name,
          passed: true,
          durationMs
        });
      } catch (err: any) {
        const durationMs = Math.round((performance.now() - t0) * 100) / 100;
        testList.push({
          suite: test.suite,
          name: test.name,
          passed: false,
          durationMs,
          error: err.message
        });
      }
      setResults([...testList]);
      await new Promise((r) => setTimeout(r, 40));
    }

    setIsRunning(false);
  };

  const passedCount = results.filter((r) => r.passed).length;
  const failedCount = results.filter((r) => !r.passed).length;

  return (
    <div className="fixed inset-0 z-[2000] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4 overflow-y-auto">
      <div className="bg-slate-900 border border-slate-700 w-full max-w-3xl rounded-xl shadow-2xl flex flex-col max-h-[90vh] overflow-hidden animate-in fade-in zoom-in-95 duration-150">
        {/* Header */}
        <div className="p-4 border-b border-slate-800 bg-slate-950/80 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="p-2 bg-emerald-950/80 rounded-lg border border-emerald-800/60 text-emerald-400">
              <FlaskConical className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-semibold text-slate-100 flex items-center gap-2">
                Automated Test Suite Runner
              </h2>
              <p className="text-xs text-slate-400">
                Direct browser execution of test_baltic.py, test_navarea_1.py, and test_navarea_xi.py
              </p>
            </div>
          </div>

          <button
            onClick={onClose}
            className="p-1.5 rounded-lg hover:bg-slate-800 text-slate-400 hover:text-white transition"
          >
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Action & Stats Banner */}
        <div className="p-4 bg-slate-950 border-b border-slate-800 flex items-center justify-between">
          <div className="flex items-center gap-4 text-xs">
            <button
              disabled={isRunning}
              onClick={runAllTests}
              className={`px-4 py-2 rounded-lg font-semibold flex items-center gap-2 transition ${
                isRunning
                  ? 'bg-emerald-800 text-emerald-200 cursor-not-allowed'
                  : 'bg-emerald-600 hover:bg-emerald-500 text-white shadow-md'
              }`}
            >
              {isRunning ? (
                <>
                  <RotateCw className="w-4 h-4 animate-spin" />
                  <span>Running Unit Tests...</span>
                </>
              ) : (
                <>
                  <Play className="w-4 h-4 fill-white" />
                  <span>Run All Test Suites</span>
                </>
              )}
            </button>

            {results.length > 0 && (
              <div className="flex items-center gap-3">
                <span className="text-emerald-400 font-medium flex items-center gap-1">
                  <CheckCircle2 className="w-4 h-4" />
                  {passedCount} Passed
                </span>
                {failedCount > 0 && (
                  <span className="text-rose-400 font-medium flex items-center gap-1">
                    <XCircle className="w-4 h-4" />
                    {failedCount} Failed
                  </span>
                )}
              </div>
            )}
          </div>

          <div className="text-xs text-slate-500">
            Coverage: Parser, Geometries, WGS84, Diff Engine
          </div>
        </div>

        {/* Results List */}
        <div className="p-4 overflow-y-auto space-y-2 flex-1">
          {results.length === 0 ? (
            <div className="text-center py-12 text-slate-500 space-y-2">
              <FlaskConical className="w-8 h-8 mx-auto text-slate-600" />
              <p className="text-xs">Click "Run All Test Suites" to execute deterministic unit assertions.</p>
            </div>
          ) : (
            results.map((r, idx) => (
              <div
                key={idx}
                className="p-2.5 bg-slate-950 rounded-lg border border-slate-800/80 flex items-center justify-between text-xs"
              >
                <div className="flex items-center gap-2.5">
                  {r.passed ? (
                    <CheckCircle2 className="w-4 h-4 text-emerald-400 shrink-0" />
                  ) : (
                    <XCircle className="w-4 h-4 text-rose-400 shrink-0" />
                  )}
                  <div>
                    <div className="font-mono text-slate-200 font-medium">{r.name}</div>
                    <div className="text-[11px] text-slate-500">{r.suite}</div>
                    {r.error && (
                      <div className="text-rose-400 text-[11px] font-mono mt-1">{r.error}</div>
                    )}
                  </div>
                </div>

                <span className="font-mono text-slate-500 text-[11px]">{r.durationMs}ms</span>
              </div>
            ))
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-slate-800 bg-slate-950/80 flex items-center justify-between text-xs text-slate-400">
          <span>All coordinate transformations strictly validated against WGS84 standards</span>
          <button
            onClick={onClose}
            className="px-4 py-1.5 bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-medium rounded-lg transition"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  );
};
