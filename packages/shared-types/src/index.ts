/**
 * Type-safe API contract shared by the mobile app and admin console.
 * `api.d.ts` is generated from the backend OpenAPI schema: `npm run gen:types`.
 */
import type { components, paths } from './api';

export type { components, paths };
export type Schemas = components['schemas'];

export type MeOut = Schemas['MeOut'];
export type AuthResponse = Schemas['AuthResponse'];
export type TokenPair = Schemas['TokenPair'];
export type OrganizationContext = Schemas['OrganizationContextOut'];
export type OrganizationCreate = Schemas['OrganizationCreate'];
export type OrganizationPublic = Schemas['OrganizationPublic'];
export type Facility = Schemas['FacilityOut'];
export type MaterialSummary = Schemas['MaterialSummary'];
export type PropertyDefinition = Schemas['PropertyDefinitionOut'];
export type ApplicationType = Schemas['ApplicationTypeOut'];
export type Resource = Schemas['ResourceOut'];
export type ResourceCreate = Schemas['ResourceCreate'];
export type Requirement = Schemas['RequirementOut'];
export type RequirementCreate = Schemas['RequirementCreate'];
export type ListingStatus = Resource['status'];
export type MatchSummary = Schemas['MatchSummary'];
export type MatchDetail = Schemas['MatchDetail'];
export type MatchStatus = MatchSummary['status'];
export type Connection = Schemas['ConnectionOut'];
export type Conversation = Schemas['ConversationOut'];
export type Message = Schemas['MessageOut'];
export type Exchange = Schemas['ExchangeOut'];
export type ExchangeCreate = Schemas['ExchangeCreate'];
export type Notification = Schemas['NotificationOut'];
export type DocumentOut = Schemas['DocumentOut'];
export type ClassificationResponse = Schemas['ClassificationResponse'];

/** Error envelope returned by every failing API call. */
export interface ApiErrorBody {
  error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string };
}
export type PathwayReport = Schemas['PathwayReport'];
export type ProcessedPathway = Schemas['ProcessedPathway'];
export type DirectPathway = Schemas['DirectPathway'];
