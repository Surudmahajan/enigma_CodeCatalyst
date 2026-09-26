/**
 * Server state via TanStack Query. Screens call these hooks; no screen talks
 * to `fetch` directly, and business rules stay on the backend.
 */
import type {
  ApplicationType,
  ClassificationResponse,
  Connection,
  Conversation,
  DocumentOut,
  Exchange,
  ExchangeCreate,
  Facility,
  MatchDetail,
  MatchSummary,
  MaterialSummary,
  Message,
  Notification,
  OrganizationContext,
  OrganizationCreate,
  PathwayReport,
  PropertyDefinition,
  Requirement,
  RequirementCreate,
  Resource,
  ResourceCreate,
} from '@symbio/shared-types';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { api } from './api';
import { useAuth } from './auth-store';

export const keys = {
  org: ['org'] as const,
  facilities: ['facilities'] as const,
  dashboard: ['dashboard'] as const,
  impact: ['impact'] as const,
  materials: (q: string) => ['materials', q] as const,
  properties: ['properties'] as const,
  applications: ['applications'] as const,
  resources: ['resources'] as const,
  resource: (id: string) => ['resources', id] as const,
  requirements: ['requirements'] as const,
  requirement: (id: string) => ['requirements', id] as const,
  matches: (filter: Record<string, unknown>) => ['matches', filter] as const,
  match: (id: string) => ['match', id] as const,
  connections: ['connections'] as const,
  conversations: ['conversations'] as const,
  messages: (id: string) => ['messages', id] as const,
  exchanges: ['exchanges'] as const,
  exchange: (id: string) => ['exchange', id] as const,
  notifications: ['notifications'] as const,
  unread: ['unread'] as const,
  documents: (filter: Record<string, unknown>) => ['documents', filter] as const,
  appSuggestions: (id: string) => ['app-suggestions', id] as const,
  pathways: (id: string) => ['pathways', id] as const,
};

/** Org-scoped queries include the active organization so switching orgs never shows stale data. */
function useOrgKey() {
  return useAuth((s) => s.organizationId);
}

export function useOrganization() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.org, org], queryFn: () => api.get<OrganizationContext>('/organizations/me'),
    enabled: !!org });
}

export function useFacilities() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.facilities, org], queryFn: () => api.get<Facility[]>('/organizations/me/facilities'),
    enabled: !!org });
}

export function useDashboard() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.dashboard, org], queryFn: () => api.get<DashboardData>('/dashboard'), enabled: !!org });
}

export function useImpact() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.impact, org], queryFn: () => api.get<ImpactData>('/impact/dashboard'), enabled: !!org });
}

export function useMaterials(q: string) {
  return useQuery({ queryKey: keys.materials(q), queryFn: () => api.get<MaterialSummary[]>('/materials', { q }),
    staleTime: 10 * 60_000 });
}

export function useProperties() {
  return useQuery({ queryKey: keys.properties, queryFn: () => api.get<PropertyDefinition[]>('/properties'),
    staleTime: 60 * 60_000 });
}

export function useApplications() {
  return useQuery({ queryKey: keys.applications, queryFn: () => api.get<ApplicationType[]>('/applications'),
    staleTime: 60 * 60_000 });
}

export function useResources() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.resources, org], queryFn: () => api.get<Resource[]>('/resources'), enabled: !!org });
}

export function useResource(id: string) {
  return useQuery({ queryKey: keys.resource(id), queryFn: () => api.get<Resource>(`/resources/${id}`) });
}

export function useRequirements() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.requirements, org], queryFn: () => api.get<Requirement[]>('/requirements'),
    enabled: !!org });
}

export function useRequirement(id: string) {
  return useQuery({ queryKey: keys.requirement(id), queryFn: () => api.get<Requirement>(`/requirements/${id}`) });
}

export type MatchFilter = { side?: 'provider' | 'demander'; resource_id?: string; requirement_id?: string;
  include_closed?: boolean };

export function useMatches(filter: MatchFilter = {}) {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.matches(filter), org],
    queryFn: () => api.get<MatchSummary[]>('/matches', filter), enabled: !!org });
}

export function useMatch(id: string) {
  return useQuery({ queryKey: keys.match(id), queryFn: () => api.get<MatchDetail>(`/matches/${id}`) });
}

export function useConnections() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.connections, org], queryFn: () => api.get<Connection[]>('/connections'),
    enabled: !!org });
}

export function useConversations() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.conversations, org], queryFn: () => api.get<Conversation[]>('/conversations'),
    enabled: !!org, refetchInterval: 30_000 });
}

export function useConversation(id: string) {
  return useQuery({ queryKey: ['conversation', id], queryFn: () => api.get<Conversation>(`/conversations/${id}`) });
}

export function useMessages(conversationId: string) {
  return useQuery({ queryKey: keys.messages(conversationId),
    queryFn: () => api.get<Message[]>(`/conversations/${conversationId}/messages`, { limit: 100 }) });
}

export function useExchanges() {
  const org = useOrgKey();
  return useQuery({ queryKey: [...keys.exchanges, org], queryFn: () => api.get<Exchange[]>('/exchanges'), enabled: !!org });
}

export function useExchange(id: string) {
  return useQuery({ queryKey: keys.exchange(id), queryFn: () => api.get<Exchange>(`/exchanges/${id}`) });
}

export function useNotifications() {
  return useQuery({ queryKey: keys.notifications, queryFn: () => api.get<Notification[]>('/notifications') });
}

export function useUnreadCount() {
  return useQuery({ queryKey: keys.unread, queryFn: () => api.get<{ unread: number }>('/notifications/unread-count'),
    refetchInterval: 60_000 });
}

export function useDocuments(filter: { resource_id?: string; conversation_id?: string }) {
  return useQuery({ queryKey: keys.documents(filter), queryFn: () => api.get<DocumentOut[]>('/documents', filter) });
}

export function useApplicationSuggestions(resourceId: string) {
  return useQuery({ queryKey: keys.appSuggestions(resourceId),
    queryFn: () => api.get<AppSuggestions>(`/resources/${resourceId}/application-suggestions`) });
}

/** Direct vs processed pathways for one of your resources (computed by the backend). */
export function usePathways(resourceId: string) {
  return useQuery({ queryKey: keys.pathways(resourceId),
    queryFn: () => api.get<PathwayReport>(`/resources/${resourceId}/processing-pathways`) });
}

// --- Mutations -----------------------------------------------------------------------------

/** After any change that can create/expire matches, refresh the views that depend on them. */
function useInvalidateAll() {
  const client = useQueryClient();
  return () => client.invalidateQueries();
}

export function useCreateOrganization() {
  return useMutation({ mutationFn: (body: OrganizationCreate) => api.post<OrganizationContext>('/organizations', body) });
}

export function useCreateResource() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (body: ResourceCreate) => api.post<Resource>('/resources', body), onSuccess: invalidate });
}

export function useCreateRequirement() {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (body: RequirementCreate) => api.post<Requirement>('/requirements', body),
    onSuccess: invalidate });
}

export function useListingStatus(kind: 'resources' | 'requirements') {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, status }: { id: string; status: string }) => api.post(`/${kind}/${id}/status`, { status }),
    onSuccess: invalidate,
  });
}

export function useConfirmProperty(resourceId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ valueId, accept }: { valueId: string; accept: boolean }) =>
      api.post(`/resources/${resourceId}/properties/${valueId}/confirm`, { accept }),
    onSuccess: invalidate,
  });
}

export function useMatchAction(matchId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ action, body }: { action: 'interest' | 'reject' | 'refresh' | 'connection-request'; body?: unknown }) =>
      api.post(`/matches/${matchId}/${action}`, body ?? {}),
    onSuccess: invalidate,
  });
}

export function useConnectionAction() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ id, action, note }: { id: string; action: 'accept' | 'reject' | 'withdraw' | 'revoke'; note?: string }) =>
      api.post<Connection>(`/connections/${id}/${action}`, action === 'accept' || action === 'withdraw' ? {} : { note }),
    onSuccess: invalidate,
  });
}

export function useSendMessage(conversationId: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { text: string; client_id: string }) =>
      api.post<Message>(`/conversations/${conversationId}/messages`, body),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.messages(conversationId) }),
  });
}

export function useCreateExchange(matchId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({ mutationFn: (body: ExchangeCreate) => api.post<Exchange>(`/matches/${matchId}/exchange`, body),
    onSuccess: invalidate });
}

export function useExchangeAction(exchangeId: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: ({ action, body }: { action: 'start' | 'pause' | 'complete' | 'cancel' | 'fail'; body?: unknown }) =>
      api.post<Exchange>(`/exchanges/${exchangeId}/${action}`, body ?? {}),
    onSuccess: invalidate,
  });
}

export function useClassify() {
  return useMutation({ mutationFn: (text: string) => api.post<ClassificationResponse>('/materials/classify', { text }) });
}

// --- Response shapes of untyped (dict) endpoints ----------------------------------------------

export type DashboardData = {
  organization: { id: string; name: string; operating_mode: string; verification_status: string };
  provider: { active_resources: number; potential_matches: number; new_matches: number; connection_requests: number;
    active_exchanges: number; impact: { potential_waste_divertable_t_per_month: number; realized_waste_diverted_t: number } };
  demander: { active_requirements: number; potential_providers: number; new_matches: number; connection_requests: number;
    active_exchanges: number; resource_savings: { potential_virgin_substitutable_t_per_month: number;
      realized_virgin_material_avoided_t: number } };
  top_opportunity_ids: string[];
  unread_messages: number;
  unread_notifications: number;
};

type Potential = { opportunities: number; waste_divertable_t_per_month?: number; virgin_substitutable_t_per_month?: number;
  net_co2e_kg_per_month?: number; economic_value_per_month_connected?: number; with_co2e_estimate: number;
  uses_demo_factors: boolean; label: string };
type RealizedMetric = { unit: string; total: number; by_source: Record<string, number>; uses_demo_factors: boolean };

export type ImpactData = {
  potential: { as_provider: Potential; as_demander: Potential };
  realized: { completed_exchanges: number; as_provider: Record<string, RealizedMetric>;
    as_demander: Record<string, RealizedMetric> };
  methodology: { economic: string; environmental: string; note: string };
};

export type AppSuggestion = { application_key: string; application: string; status: string; evidence: string[];
  source: string; source_note?: string | null };
export type AppSuggestions = { curated: AppSuggestion[]; related: AppSuggestion[]; ai_ideas: AppSuggestion[] };
