import { HazardCategory } from '../types/maritime';

/**
 * Classify maritime hazard category based on terminology in the warning text.
 * Exact deterministic mirror of shared/classification.py.
 *
 * Categories (in priority order):
 * 1. electronic - GNSS, DGPS, AIS, radar interference
 * 2. military - Detonations, firing, gunnery, missile, weapons
 * 3. aton - Light, buoy, racón, beacon, unlit, extinguished
 * 4. subsea - Seismic, cable, pipeline, ROV, towing, dredging
 * 5. drifting - Drifting, derelict, mine, container, adrift
 * 6. offshore - Rig, platform, jack-up
 * 7. general - All other warnings
 */
export function classifyHazard(rawText: string): HazardCategory {
  const text = (rawText || '').toUpperCase();

  // 1. Electronic / GNSS interference
  const electronicKeywords = [
    'GNSS',
    'DGPS',
    'AIS INTERFERENCE',
    'RADAR INTERFERENCE',
    'INTERFERENCE OBSERVED',
    'JAMMING',
    'SPOOFING'
  ];
  if (electronicKeywords.some((k) => text.includes(k))) {
    return 'electronic';
  }

  // 2. Military / Naval operations
  const militaryPattern = /\b(DETONATION|DETONATIONS|FIRING|FIRINGS|GUNNERY|MISSILE|WEAPONS?|ARMED FORCES|NAVAL EXERCISE|NAVAL EXERCISES|MILITARY EXERCISE)\b/i;
  if (militaryPattern.test(text)) {
    return 'military';
  }

  // 3. Aids to Navigation (AtoN)
  const atonKeywords = [
    'LIGHT',
    'LIGHTS',
    'BUOY',
    'BUOYS',
    'RACON',
    'BEACON',
    'UNLIT',
    'EXTINGUISHED',
    'OFF AIR'
  ];
  if (atonKeywords.some((k) => text.includes(k))) {
    return 'aton';
  }

  // 4. Subsea / Obstruction
  const subseaKeywords = [
    'SEISMIC',
    'CABLE',
    'PIPELINE',
    'ROV',
    'TOWING',
    'DREDGING',
    'ANCHOR',
    'CHAIN LOST',
    'SUNKEN WRECK'
  ];
  if (subseaKeywords.some((k) => text.includes(k))) {
    return 'subsea';
  }

  // 5. Drifting hazards
  const driftingKeywords = [
    'DRIFTING',
    'DERELICT',
    'MINE',
    'CONTAINER',
    'ADRIFT',
    'SPACE DEBRIS'
  ];
  if (driftingKeywords.some((k) => text.includes(k))) {
    return 'drifting';
  }

  // 6. Offshore operations
  const offshoreKeywords = ['RIG', 'PLATFORM', 'JACK-UP'];
  if (offshoreKeywords.some((k) => text.includes(k))) {
    return 'offshore';
  }

  // 7. General (default)
  return 'general';
}

export function getHazardKeywords(category: HazardCategory): string[] {
  const hazardMap: Record<HazardCategory, string[]> = {
    electronic: [
      'GNSS',
      'DGPS',
      'AIS INTERFERENCE',
      'RADAR INTERFERENCE',
      'INTERFERENCE OBSERVED',
      'JAMMING',
      'SPOOFING'
    ],
    military: [
      'DETONATION',
      'DETONATIONS',
      'FIRING',
      'FIRINGS',
      'GUNNERY',
      'MISSILE',
      'WEAPON',
      'WEAPONS',
      'ARMED FORCES',
      'NAVAL EXERCISE',
      'NAVAL EXERCISES',
      'MILITARY EXERCISE'
    ],
    aton: [
      'LIGHT',
      'LIGHTS',
      'BUOY',
      'BUOYS',
      'RACON',
      'BEACON',
      'UNLIT',
      'EXTINGUISHED',
      'OFF AIR'
    ],
    subsea: [
      'SEISMIC',
      'CABLE',
      'PIPELINE',
      'ROV',
      'TOWING',
      'DREDGING',
      'ANCHOR',
      'CHAIN LOST',
      'SUNKEN WRECK'
    ],
    drifting: [
      'DRIFTING',
      'DERELICT',
      'MINE',
      'CONTAINER',
      'ADRIFT',
      'SPACE DEBRIS'
    ],
    offshore: ['RIG', 'PLATFORM', 'JACK-UP'],
    general: []
  };

  return hazardMap[category] || [];
}

export const ALL_HAZARD_CATEGORIES: HazardCategory[] = [
  'electronic',
  'military',
  'aton',
  'subsea',
  'drifting',
  'offshore',
  'general'
];

export function getCategoryBadgeStyle(category: HazardCategory): {
  label: string;
  badgeBg: string;
  badgeText: string;
  borderColor: string;
  colorHex: string;
} {
  switch (category) {
    case 'electronic':
      return {
        label: 'Electronic / GNSS',
        badgeBg: 'bg-purple-950/80',
        badgeText: 'text-purple-300',
        borderColor: 'border-purple-600/40',
        colorHex: '#c084fc'
      };
    case 'military':
      return {
        label: 'Military Operations',
        badgeBg: 'bg-rose-950/80',
        badgeText: 'text-rose-300',
        borderColor: 'border-rose-600/40',
        colorHex: '#f43f5e'
      };
    case 'aton':
      return {
        label: 'Aids to Navigation (AtoN)',
        badgeBg: 'bg-amber-950/80',
        badgeText: 'text-amber-300',
        borderColor: 'border-amber-600/40',
        colorHex: '#fbbf24'
      };
    case 'subsea':
      return {
        label: 'Subsea / Underwater',
        badgeBg: 'bg-cyan-950/80',
        badgeText: 'text-cyan-300',
        borderColor: 'border-cyan-600/40',
        colorHex: '#22d3ee'
      };
    case 'drifting':
      return {
        label: 'Drifting Hazard',
        badgeBg: 'bg-orange-950/80',
        badgeText: 'text-orange-300',
        borderColor: 'border-orange-600/40',
        colorHex: '#fb923c'
      };
    case 'offshore':
      return {
        label: 'Offshore Rig / Platform',
        badgeBg: 'bg-emerald-950/80',
        badgeText: 'text-emerald-300',
        borderColor: 'border-emerald-600/40',
        colorHex: '#34d399'
      };
    case 'general':
    default:
      return {
        label: 'General Notice',
        badgeBg: 'bg-slate-800/80',
        badgeText: 'text-slate-300',
        borderColor: 'border-slate-600/40',
        colorHex: '#94a3b8'
      };
  }
}

export function determineSeverity(
  category: HazardCategory,
  rawText?: string
): 'critical' | 'high' | 'moderate' | 'general' {
  const text = (rawText || '').toUpperCase();

  // Rule M401 / M402 priority overrides
  if (category === 'military') return 'critical';
  if (category === 'electronic') {
    if (text.includes('SPOOFING') || text.includes('JAMMING') || text.includes('EXTREME CAUTION')) {
      return 'critical';
    }
    return 'high';
  }
  if (category === 'drifting') return 'high';
  if (category === 'subsea') {
    if (text.includes('SUNKEN') || text.includes('UNLIT') || text.includes('EXPLOSIVE')) {
      return 'high';
    }
    return 'moderate';
  }
  if (category === 'offshore') return 'moderate';
  if (category === 'aton') return 'moderate';

  return 'general';
}

