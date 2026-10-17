import { NavWarning, RawMessage, SpatialFeature, SourceFeed } from '../types/maritime';
import { parseBalticWarning } from '../core/parsers/balticParser';
import { parseNavarea1Warning } from '../core/parsers/navarea1Parser';
import { parseNavareaXiWarning } from '../core/parsers/navareaXiParser';

export const OFFICIAL_SOURCES: SourceFeed[] = [
  {
    id: 'ukho-navarea-1',
    name: 'NAVAREA I Coordinator',
    region: 'North Atlantic / UK / North Sea',
    navarea: 'NA I',
    authority: 'United Kingdom Hydrographic Office (UKHO)',
    url: 'https://msi.admiralty.co.uk/RadioNavigationalWarnings',
    schedule: 'Every 6 hours',
    activeCount: 18,
    status: 'operational',
    lastPolled: '12 mins ago'
  },
  {
    id: 'sma-baltic-subarea',
    name: 'Baltic Sea Sub-Area Coordinator',
    region: 'Baltic Sea, Kattegat, Skagerrak',
    navarea: 'Baltic',
    authority: 'Swedish Maritime Administration (Sjöfartsverket)',
    url: 'https://navvarn.sjofartsverket.se/en/Navigationsvarningar/VHF',
    schedule: 'Every 6 hours',
    activeCount: 14,
    status: 'operational',
    lastPolled: '5 mins ago'
  },
  {
    id: 'kaiho-navarea-xi',
    name: 'NAVAREA XI Coordinator',
    region: 'North-West Pacific & East Asia',
    navarea: 'NA XI',
    authority: 'Japan Coast Guard (JCG Kaiho)',
    url: 'https://www1.kaiho.mlit.go.jp/TUHO/keiho/cgi/disp_warnings.cgi',
    schedule: 'Every 6 hours',
    activeCount: 22,
    status: 'operational',
    lastPolled: '18 mins ago'
  },
  {
    id: 'shom-navarea-2',
    name: 'NAVAREA II Coordinator',
    region: 'East Atlantic / Bay of Biscay',
    navarea: 'NA II',
    authority: 'Service Hydrographique et Océanographique (SHOM)',
    url: 'https://www.shom.fr/en/activites/diffusion/diffusions-maritimes',
    schedule: 'Every 6 hours',
    activeCount: 9,
    status: 'operational',
    lastPolled: '30 mins ago'
  },
  {
    id: 'iim-navarea-3',
    name: 'NAVAREA III Coordinator',
    region: 'Mediterranean & Black Sea',
    navarea: 'NA III',
    authority: 'Instituto Hidrográfico de la Marina (IHM Cadiz)',
    url: 'https://armada.defensa.gob.es/ihm/',
    schedule: 'Every 6 hours',
    activeCount: 16,
    status: 'operational',
    lastPolled: '45 mins ago'
  },
  {
    id: 'nga-navarea-4',
    name: 'NAVAREA IV Coordinator',
    region: 'West Atlantic & Caribbean',
    navarea: 'NA IV',
    authority: 'US National Geospatial-Intelligence Agency (NGA)',
    url: 'https://msi.nga.mil/NavWarnings',
    schedule: 'Every 6 hours',
    activeCount: 26,
    status: 'operational',
    lastPolled: '15 mins ago'
  },
  {
    id: 'dhn-navarea-5',
    name: 'NAVAREA V Coordinator',
    region: 'Brazil & South-West Atlantic',
    navarea: 'NA V',
    authority: 'Diretoria de Hidrografia e Navegação (DHN Brazil)',
    url: 'https://www.marinha.mil.br/dhn/',
    schedule: 'Every 6 hours',
    activeCount: 8,
    status: 'operational',
    lastPolled: '1 hour ago'
  },
  {
    id: 'aho-navarea-10',
    name: 'NAVAREA X Coordinator',
    region: 'Australia & South Ocean',
    navarea: 'NA X',
    authority: 'Australian Hydrographic Office (AHO / AMSA)',
    url: 'https://www.hydro.gov.au/prod/warnings/',
    schedule: 'Every 6 hours',
    activeCount: 11,
    status: 'operational',
    lastPolled: '25 mins ago'
  }
];

export const RAW_FEED_BULLETINS = [
  // Baltic Region Bulletins
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 168/26 [Skagerrak]',
    raw: `080056 UTC OCT
SKAGERRAK. LYSEKIL. BONDEN
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS
09 OCT 0600 LT - 14 OCT 2000 LT
PSN:
58-10.2N 011-13.3E
58-13.3N 011-13.3E
58-13.3N 011-17.4E
58-10.2N 011-13.3E
500 MTR CLEARANCE FROM THE AREA IS REQUESTED.`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 167/26 [Kattegat]',
    raw: `080035 UTC OCT
KATTEGAT. MARSTRAND. STORA PÖLSAN.
THE SWEDISH ARMED FORCES WILL PERFORM DETONATIONS.
09 OCT 0600 LT - 14 OCT 2000 LT.
1 M CLEARANCE FROM THE AREA IS REQUESTED.
PSN: 57-47.0N 011-27.9E`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'moderate' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 166/26 [Kattegat]',
    raw: `070800 UTC OCT
KATTEGAT. FALKENBERG HARBOUR ENTRANCE.
DREDGING IN OPERATION. SPAR BUOYS MIGHT HAVE BEEN MOVED.
PSN 56-53.0N 012-28.0E
GREATE CAUTION ADVISED`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 156/26 [Kattegat]',
    raw: `300051 UTC SEP
KATTEGAT. STYRSÖ. DONSÖ
LIGHT 'DONSÖ SVARTSKÅR' IS UNLIT.
PSN 57-35.15N 011-43.33E.`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'BALTIC SEA NAV WARN 026/25 [Western Baltic, Central Baltic]',
    raw: `021100 UTC JUL
SOUTHERN, SOUTHEASTERN, CENTRAL AND NORTHERN BALTIC, GULF OF FINLAND, GULF OF RIGA AND SEA OF AALAND.
GNSS, AIS, RADAR AND DGPS INTERFERENCE OBSERVED IN AREA.
MARINERS ADVISED TO EXERCISE CAUTION
AND BE PREPARED FOR NAVIGATION IMPACTS.`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 123/25 [Gotland]',
    raw: `051200 UTC JUN
GOTLAND. SOUTH OF FARO.
MILITARY EXERCISE WILL TAKE PLACE.
06 JUN 0000 LT - 10 JUN 2359 LT.
PSN: 57-10.0N 018-30.0E
57-20.0N 018-40.0E
57-20.0N 018-30.0E
57-10.0N 018-30.0E
KEEP CLEAR OF THE AREA.`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 045/25 [Skagerrak]',
    raw: `100600 UTC APR
SKAGERRAK.
CONTAINER ADRIFT.
APPROX PSN: 57-50.0N 011-30.0E
ALL SHIPS REQUESTED TO REPORT SIGHTINGS.`
  },
  {
    type: 'baltic' as const,
    navarea: 'Baltic',
    severity: 'moderate' as const,
    verification: 'verified' as const,
    header: 'SWEDISH NAV WARN 001/25 [Western Baltic]',
    raw: `010000 UTC JAN
WESTERN BALTIC.
DRILLING RIG 'OCEAN PRIDE' ON LOCATION.
PSN: 56-00.0N 014-00.0E
SAFETY ZONE OF 500M ESTABLISHED AROUND THE RIG.`
  },

  // NAVAREA I Bulletins (UKHO)
  {
    type: 'navarea_1' as const,
    navarea: 'NA I',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'NAVAREA I 123/26',
    raw: `010000 UTC JAN 2026
NORTH SEA. DOVER STRAIT.
DRIFTING CONTAINER REPORTED.
PSN: 51-00.0N 001-30.0E
ALL SHIPS ADVISED TO NAVIGATE WITH CAUTION.`
  },
  {
    type: 'navarea_1' as const,
    navarea: 'NA I',
    severity: 'moderate' as const,
    verification: 'verified' as const,
    header: 'NAVAREA I 456/26',
    raw: `051200 UTC JUN 2026
ENGLISH CHANNEL.
SUBMARINE CABLE REPAIR OPERATIONS.
PSN: 50-30.0N 000-45.0W TO 50-35.0N 000-40.0W
MARINERS REQUESTED TO KEEP CLEAR.`
  },
  {
    type: 'navarea_1' as const,
    navarea: 'NA I',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'NAVAREA I 789/26',
    raw: `100600 UTC OCT 2026
NORTH ATLANTIC.
NAVAL EXERCISE IN PROGRESS.
GUNNERY AND MISSILE FIRING.
PSN: 55-00.0N 010-00.0W
56-00.0N 010-00.0W
56-00.0N 009-00.0W
55-00.0N 009-00.0W
55-00.0N 010-00.0W
DANGER AREA ACTIVE.`
  },
  {
    type: 'navarea_1' as const,
    navarea: 'NA I',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'NAVAREA I 012/26',
    raw: `150800 UTC AUG 2026
IRISH SEA.
LIGHT BUOY 'ALPHA' EXTINGUISHED.
PSN: 53-20.5N 005-30.2W
MARINERS ADVISED.`
  },
  {
    type: 'navarea_1' as const,
    navarea: 'NA I',
    severity: 'moderate' as const,
    verification: 'needs_review' as const,
    header: 'NAVAREA I 198/26',
    raw: `120930 UTC SEP 2026
NORTHERN NORTH SEA.
SEISMIC SURVEY OPERATIONS CONDUCTED BY M/V GEO EXPLORER.
TOWING 8000 METRE SPREAD CABLES.
PSN: 59-15.0N 001-10.0E TO 59-45.0N 001-50.0E
WIDE BERTH OF 3 NAUTICAL MILES REQUESTED.`
  },

  // NAVAREA XI Bulletins (Japan Coast Guard)
  {
    type: 'navarea_xi' as const,
    navarea: 'NA XI',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'NAVAREA XI NO.26-0451',
    raw: `NO.26-0451       Date:2026/10/09 07 UTC
NORTH PACIFIC, OKINOTORI SHIMA.
HATCH COVER, ABOUT 20 METRE IN SQUARE,
ADRIFT IN
16-54.1N 134-39.5E AT 090625Z OCT.
CANCEL 0450/26.
CANCEL THIS MSG 120625Z OCT.`
  },
  {
    type: 'navarea_xi' as const,
    navarea: 'NA XI',
    severity: 'high' as const,
    verification: 'verified' as const,
    header: 'NAVAREA XI NO.26-0123',
    raw: `NO.26-0123       Date:2026/05/15 10 UTC
NORTH PACIFIC.
DRIFTING OBJECT.
PSN: 24-04.12N 118-46.48E
REPORT SIGHTINGS TO AUTHORITIES.`
  },
  {
    type: 'navarea_xi' as const,
    navarea: 'NA XI',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'NAVAREA XI NO.26-0500',
    raw: `NO.26-0500       Date:2026/06/20 08 UTC
EAST CHINA SEA.
NAVAL EXERCISE WILL BE CONDUCTED.
FIRING AND GUNNERY PRACTICE.
PSN: 30-00.0N 125-00.0E
31-00.0N 125-00.0E
31-00.0N 126-00.0E
30-00.0N 126-00.0E
30-00.0N 125-00.0E
DANGER PERIOD: 22 JUN TO 25 JUN.`
  },
  {
    type: 'navarea_xi' as const,
    navarea: 'NA XI',
    severity: 'critical' as const,
    verification: 'verified' as const,
    header: 'NAVAREA XI NO.26-0750',
    raw: `NO.26-0750       Date:2026/07/01 12 UTC
PHILIPPINE SEA.
GNSS INTERFERENCE OBSERVED.
MARINERS ADVISED TO USE ALTERNATIVE NAVIGATION METHODS.
PSN: 15-00.0N 120-00.0E`
  },
  {
    type: 'navarea_xi' as const,
    navarea: 'NA XI',
    severity: 'moderate' as const,
    verification: 'needs_review' as const,
    header: 'NAVAREA XI NO.26-0620',
    raw: `NO.26-0620       Date:2026/08/11 04 UTC
SEA OF JAPAN.
SUBSEA CABLE INSTALLATION BY C/S OCEAN LINK.
PSN: 37-12.0N 136-40.0E TO 38-05.0N 137-30.0E
1 MILE CLEARANCE REQUESTED.`
  }
];

export function getInitialSeedData(): {
  warnings: NavWarning[];
  messages: RawMessage[];
  spatialFeatures: SpatialFeature[];
} {
  const warnings: NavWarning[] = [];
  const messages: RawMessage[] = [];
  const spatialFeatures: SpatialFeature[] = [];

  for (const item of RAW_FEED_BULLETINS) {
    if (item.type === 'baltic') {
      const { rawMessage, navWarning, spatial } = parseBalticWarning(item.raw, item.header);
      navWarning.navarea = item.navarea;
      navWarning.severity = item.severity;
      navWarning.verification = item.verification;
      warnings.push(navWarning);
      messages.push(rawMessage);
      if (spatial) {
        spatialFeatures.push({
          warning_id: navWarning.warning_id,
          category: navWarning.category,
          geometry: spatial
        });
      }
    } else if (item.type === 'navarea_1') {
      const { rawMessage, navWarning, spatial } = parseNavarea1Warning(item.raw, item.header);
      navWarning.navarea = item.navarea;
      navWarning.severity = item.severity;
      navWarning.verification = item.verification;
      warnings.push(navWarning);
      messages.push(rawMessage);
      if (spatial) {
        spatialFeatures.push({
          warning_id: navWarning.warning_id,
          category: navWarning.category,
          geometry: spatial
        });
      }
    } else if (item.type === 'navarea_xi') {
      const { rawMessage, navWarning, spatial } = parseNavareaXiWarning(item.raw, item.header);
      navWarning.navarea = item.navarea;
      navWarning.severity = item.severity;
      navWarning.verification = item.verification;
      warnings.push(navWarning);
      messages.push(rawMessage);
      if (spatial) {
        spatialFeatures.push({
          warning_id: navWarning.warning_id,
          category: navWarning.category,
          geometry: spatial
        });
      }
    }
  }

  return { warnings, messages, spatialFeatures };
}

export const INITIAL_BULLETINS = RAW_FEED_BULLETINS;
