import { statusLabels } from '@symbio/config';

const UNIT_ABBREV: Record<string, string> = { tonne: 't', m3: 'm³', litre: 'L' };
const PERIOD: Record<string, string> = { DAY: '/day', WEEK: '/week', MONTH: '/month', YEAR: '/year', ONE_TIME: ' (one-time)' };

export function formatNumber(value: number | string | null | undefined, digits = 0): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'string' ? Number(value) : value;
  return Number.isFinite(n) ? n.toLocaleString(undefined, { maximumFractionDigits: digits }) : '—';
}

export function formatQuantity(quantity: number | string, unit: string, frequency?: string): string {
  return `${formatNumber(quantity, 1)} ${UNIT_ABBREV[unit] ?? unit}${frequency ? (PERIOD[frequency] ?? '') : ''}`;
}

export function formatMoney(value: number | string | null | undefined, currency = 'INR'): string {
  if (value === null || value === undefined) return '—';
  const n = Number(value);
  try {
    return n.toLocaleString(undefined, { style: 'currency', currency, maximumFractionDigits: 0 });
  } catch {
    return `${currency} ${formatNumber(n)}`;
  }
}

export const percent = (value: number | null | undefined) => (value === null || value === undefined ? '—' : `${Math.round(value * 100)}%`);

/** Timestamps arrive in UTC; display them in the device's local time. */
export function formatDate(value?: string | null): string {
  if (!value) return 'Open-ended';
  const date = value.length === 10 ? new Date(`${value}T00:00:00`) : new Date(value);
  return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });
}

export function timeAgo(value: string): string {
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (seconds < 60) return 'just now';
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  return formatDate(value);
}

export const statusLabel = (status: string) => statusLabels[status] ?? status.replace(/_/g, ' ').toLowerCase();

export const today = () => new Date().toISOString().slice(0, 10);
export const addDays = (days: number) => new Date(Date.now() + days * 86400000).toISOString().slice(0, 10);

/** RFC 4122 v4-ish id for idempotent message sends (not security sensitive). */
export const clientId = () =>
  'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === 'x' ? r : (r & 0x3) | 0x8).toString(16);
  });
