/**
 * Client-side validation for immediate UX feedback. The backend re-validates
 * everything (never trust the client); these rules mirror its Pydantic schemas.
 */
import { z } from 'zod';

export const password = z
  .string()
  .min(10, 'At least 10 characters')
  .max(128)
  .regex(/[A-Za-z]/, 'Include a letter')
  .regex(/\d/, 'Include a number');

export const loginSchema = z.object({
  email: z.string().trim().email('Enter a valid email'),
  password: z.string().min(1, 'Enter your password'),
});
export type LoginForm = z.infer<typeof loginSchema>;

export const registerSchema = z.object({
  first_name: z.string().trim().min(1, 'Required').max(100),
  last_name: z.string().trim().min(1, 'Required').max(100),
  email: z.string().trim().email('Enter a valid email'),
  password,
});
export type RegisterForm = z.infer<typeof registerSchema>;

const optionalNumber = (label: string) =>
  z
    .string()
    .trim()
    .optional()
    .refine((v) => !v || (!Number.isNaN(Number(v)) && Number(v) >= 0), `${label} must be a non-negative number`);

export const organizationSchema = z.object({
  display_name: z.string().trim().min(2, 'At least 2 characters').max(255),
  legal_name: z.string().trim().min(2, 'At least 2 characters').max(255),
  industry_sector: z.string().trim().min(2, 'Choose or type a sector').max(120),
  description: z.string().max(4000).optional(),
  city: z.string().trim().min(1, 'Required'),
  state: z.string().trim().optional(),
  country: z.string().trim().min(2, 'Required'),
  latitude: z
    .string()
    .trim()
    .optional()
    .refine((v) => !v || (Number(v) >= -90 && Number(v) <= 90), 'Latitude must be between -90 and 90'),
  longitude: z
    .string()
    .trim()
    .optional()
    .refine((v) => !v || (Number(v) >= -180 && Number(v) <= 180), 'Longitude must be between -180 and 180'),
});
export type OrganizationForm = z.infer<typeof organizationSchema>;

export const UNITS = ['tonne', 'kg', 'm3', 'litre', 'MWh', 'kWh', 'GJ', 'unit'] as const;
export const FREQUENCIES = ['MONTH', 'WEEK', 'DAY', 'YEAR', 'ONE_TIME'] as const;
export const DISPOSITIONS = ['DISPOSAL', 'STORAGE', 'INTERNAL_USE', 'LOW_VALUE_USE', 'OTHER'] as const;

const isoDate = z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use YYYY-MM-DD');

const listingBase = {
  name: z.string().trim().min(2, 'Give it a clear name').max(200),
  description: z.string().max(4000).optional(),
  material_id: z.string().uuid().nullable().optional(),
  quantity: z
    .string()
    .trim()
    .refine((v) => Number(v) > 0, 'Quantity must be greater than zero'),
  unit: z.enum(UNITS),
  frequency: z.enum(FREQUENCIES),
  facility_id: z.string().uuid('Choose a facility'),
  window_start: isoDate,
  window_end: isoDate.optional().or(z.literal('')),
};

const windowOrder = (d: { window_start: string; window_end?: string }) =>
  !d.window_end || d.window_end >= d.window_start;

export const resourceSchema = z
  .object({
    ...listingBase,
    processing_required: z.boolean(),
    processing_types: z.string().optional(),
    current_disposition: z.enum(DISPOSITIONS),
    disposal_cost_per_unit: optionalNumber('Disposal cost'),
    asking_price_per_unit: optionalNumber('Asking price'),
  })
  .refine(windowOrder, { message: 'End date must be on or after the start date', path: ['window_end'] });
export type ResourceForm = z.infer<typeof resourceSchema>;

export const requirementSchema = z
  .object({
    ...listingBase,
    intended_application_id: z.string().uuid().nullable().optional(),
    max_transport_distance_km: optionalNumber('Maximum distance'),
    processing_capabilities: z.string().optional(),
    virgin_material_price_per_unit: optionalNumber('Current price'),
  })
  .refine(windowOrder, { message: 'End date must be on or after the start date', path: ['window_end'] });
export type RequirementForm = z.infer<typeof requirementSchema>;

export const propertyRowSchema = z.object({
  property_key: z.string().min(1),
  value: z.string().refine((v) => v.trim() !== '' && !Number.isNaN(Number(v)), 'Enter a number'),
});

export const constraintRowSchema = z
  .object({
    property_key: z.string().min(1),
    min: z.string().optional(),
    max: z.string().optional(),
    importance: z.enum(['REQUIRED', 'PREFERRED', 'OPTIONAL']),
  })
  .refine((c) => !!(c.min || c.max), 'Set a minimum or maximum')
  .refine((c) => !c.min || !c.max || Number(c.min) <= Number(c.max), 'Minimum cannot exceed maximum');

export const exchangeSchema = z.object({
  agreed_quantity: z.string().refine((v) => Number(v) > 0, 'Quantity must be greater than zero'),
  unit: z.enum(UNITS),
  agreed_frequency: z.enum(FREQUENCIES),
  agreed_price_per_unit: optionalNumber('Price'),
  start_date: isoDate,
  end_date: isoDate.optional().or(z.literal('')),
  notes: z.string().max(2000).optional(),
});
export type ExchangeForm = z.infer<typeof exchangeSchema>;

/** Split "grinding, drying" into ["grinding", "drying"]. */
export const splitList = (value?: string): string[] =>
  (value ?? '')
    .split(',')
    .map((s) => s.trim().toLowerCase())
    .filter(Boolean);
