import type { AuthResponse, MeOut, TokenPair } from '@symbio/shared-types';
import { create } from 'zustand';

import { api, configureApi } from './api';
import { secureStorage } from './secure-storage';

const REFRESH_KEY = 'symbio.refresh_token';
const ORG_KEY = 'symbio.organization_id';

export type ViewMode = 'PROVIDER' | 'DEMANDER';

type AuthState = {
  status: 'loading' | 'signedOut' | 'signedIn';
  accessToken?: string;
  refreshToken?: string;
  me?: MeOut;
  organizationId?: string;
  viewMode: ViewMode;
  bootstrap: () => Promise<void>;
  signIn: (response: AuthResponse) => Promise<void>;
  signOut: () => Promise<void>;
  reloadMe: () => Promise<MeOut | undefined>;
  setOrganization: (organizationId: string) => Promise<void>;
  setViewMode: (mode: ViewMode) => void;
};

/**
 * Session state. The access token stays in memory; the refresh token is kept
 * in the secure store so the session survives app restarts.
 */
export const useAuth = create<AuthState>((set, get) => ({
  status: 'loading',
  viewMode: 'PROVIDER',

  async bootstrap() {
    const refreshToken = await secureStorage.get(REFRESH_KEY);
    const organizationId = (await secureStorage.get(ORG_KEY)) ?? undefined;
    if (!refreshToken) return set({ status: 'signedOut' });
    set({ refreshToken, organizationId });
    try {
      const tokens = await api.post<TokenPair>('/auth/refresh', { refresh_token: refreshToken }, false);
      await storeTokens(tokens);
      await get().reloadMe();
      set({ status: 'signedIn' });
    } catch {
      await get().signOut();
    }
  },

  async signIn(response) {
    await storeTokens(response);
    await get().reloadMe();
    set({ status: 'signedIn' });
  },

  async signOut() {
    const refreshToken = get().refreshToken;
    if (refreshToken) api.post('/auth/logout', { refresh_token: refreshToken }, false).catch(() => undefined);
    await secureStorage.remove(REFRESH_KEY);
    set({ status: 'signedOut', accessToken: undefined, refreshToken: undefined, me: undefined });
  },

  async reloadMe() {
    const me = await api.get<MeOut>('/users/me');
    let organizationId = get().organizationId;
    if (!me.memberships.some((m) => m.organization_id === organizationId)) {
      organizationId = me.memberships[0]?.organization_id;
      if (organizationId) await secureStorage.set(ORG_KEY, organizationId);
    }
    // Single-mode organizations always see their workspace; BOTH keeps the user's last choice.
    const mode = me.memberships.find((m) => m.organization_id === organizationId)?.operating_mode;
    const viewMode: ViewMode = mode === 'PROVIDER' || mode === 'DEMANDER' ? mode : get().viewMode;
    set({ me, organizationId, viewMode });
    return me;
  },

  async setOrganization(organizationId) {
    await secureStorage.set(ORG_KEY, organizationId);
    set({ organizationId });
    await get().reloadMe();
  },

  setViewMode(viewMode) {
    set({ viewMode });
  },
}));

async function storeTokens(tokens: TokenPair) {
  await secureStorage.set(REFRESH_KEY, tokens.refresh_token);
  useAuth.setState({ accessToken: tokens.access_token, refreshToken: tokens.refresh_token });
}

configureApi({
  getAccessToken: () => useAuth.getState().accessToken,
  getRefreshToken: () => useAuth.getState().refreshToken,
  getOrganizationId: () => useAuth.getState().organizationId,
  onTokens: storeTokens,
  onSignedOut: () => useAuth.getState().signOut(),
});

export function useMembership() {
  const { me, organizationId } = useAuth();
  return me?.memberships.find((m) => m.organization_id === organizationId);
}

export function useCan(permission: string) {
  return useMembership()?.permissions.includes(permission) ?? false;
}
