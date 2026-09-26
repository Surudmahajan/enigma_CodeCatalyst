/**
 * SYMBIO design tokens. Industrial, technical, trustworthy — deep slate and
 * steel with a circular-economy green accent, not a "recycling app" palette.
 */

export const palette = {
  ink: '#0F1B24',
  slate900: '#15232E',
  slate800: '#1E3140',
  slate700: '#2C4556',
  slate500: '#5B7384',
  slate300: '#A7B6C2',
  slate100: '#E6ECF0',
  slate50: '#F4F7F9',
  white: '#FFFFFF',
  green600: '#138A5E',
  green500: '#1BA672',
  green100: '#DDF4EA',
  amber600: '#B7791F',
  amber100: '#FBEFD5',
  red600: '#C0392B',
  red100: '#F8E0DD',
  blue600: '#2563A8',
  blue100: '#DCE8F6',
  violet600: '#6A4FB3',
  violet100: '#ECE6F8',
} as const;

export type ColorTokens = Record<
  | 'background' | 'surface' | 'surfaceMuted' | 'border' | 'text' | 'textMuted' | 'primary' | 'onPrimary'
  | 'accent' | 'accentSoft' | 'warning' | 'warningSoft' | 'danger' | 'dangerSoft' | 'info' | 'infoSoft'
  | 'hidden' | 'hiddenSoft',
  string
>;

export const lightColors: ColorTokens = {
  background: palette.slate50,
  surface: palette.white,
  surfaceMuted: palette.slate100,
  border: '#D5DEE5',
  text: palette.ink,
  textMuted: palette.slate500,
  primary: palette.slate800,
  onPrimary: palette.white,
  accent: palette.green600,
  accentSoft: palette.green100,
  warning: palette.amber600,
  warningSoft: palette.amber100,
  danger: palette.red600,
  dangerSoft: palette.red100,
  info: palette.blue600,
  infoSoft: palette.blue100,
  hidden: palette.violet600,
  hiddenSoft: palette.violet100,
};

export const darkColors: ColorTokens = {
  background: palette.ink,
  surface: palette.slate900,
  surfaceMuted: palette.slate800,
  border: palette.slate700,
  text: '#EEF3F6',
  textMuted: palette.slate300,
  primary: palette.green500,
  onPrimary: palette.ink,
  accent: palette.green500,
  accentSoft: '#12382B',
  warning: '#E0A43C',
  warningSoft: '#3D2F14',
  danger: '#E4695B',
  dangerSoft: '#3E1D19',
  info: '#6FA3E0',
  infoSoft: '#18293F',
  hidden: '#A78BEA',
  hiddenSoft: '#2A2242',
};

export const spacing = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32 } as const;
export const radius = { sm: 8, md: 12, lg: 16, pill: 999 } as const;
export const fontSize = { xs: 12, sm: 14, md: 16, lg: 18, xl: 22, xxl: 28 } as const;
/** Minimum touch target (Material/Apple guidance ≈ 44–48 dp). */
export const touchTarget = 48;

export const brand = {
  name: 'SYMBIO',
  tagline: 'Turning industrial by-products into industrial resources.',
};

/** Score → label used consistently across clients. Scores are indicators, not guarantees. */
export function scoreLevel(score: number | null | undefined): 'High' | 'Moderate' | 'Low' | 'Not assessed' {
  if (score === null || score === undefined) return 'Not assessed';
  if (score >= 0.75) return 'High';
  if (score >= 0.5) return 'Moderate';
  return 'Low';
}

export const statusLabels: Record<string, string> = {
  DISCOVERED: 'New',
  VIEWED: 'Viewed',
  INTERESTED: 'Interested',
  CONNECTION_REQUESTED: 'Connection requested',
  CONNECTED: 'Connected',
  NEGOTIATING: 'Negotiating',
  ACTIVE_EXCHANGE: 'Active exchange',
  COMPLETED: 'Completed',
  REJECTED: 'Declined',
  EXPIRED: 'No longer active',
  CANCELLED: 'Cancelled',
  DRAFT: 'Draft',
  ACTIVE: 'Active',
  PAUSED: 'Paused',
  FULFILLED: 'Fulfilled',
  ARCHIVED: 'Archived',
  PENDING: 'Pending',
  ACCEPTED: 'Accepted',
  REVOKED: 'Ended',
  PLANNED: 'Planned',
  IN_PROGRESS: 'In progress',
  FAILED: 'Failed',
};
