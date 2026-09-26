import type { ApiErrorBody, TokenPair } from '@symbio/shared-types';

import { API_PREFIX, API_URL } from './config';

/** Error carrying the backend's `{error: {code, message}}` envelope. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly details?: Record<string, unknown>,
  ) {
    super(message);
  }

  get isNetwork() {
    return this.status === 0;
  }
}

type Session = {
  getAccessToken: () => string | undefined;
  getRefreshToken: () => string | undefined;
  getOrganizationId: () => string | undefined;
  onTokens: (tokens: TokenPair) => Promise<void>;
  onSignedOut: () => Promise<void>;
};

let session: Session | null = null;
let refreshing: Promise<boolean> | null = null;

export function configureApi(s: Session) {
  session = s;
}

type Options = {
  body?: unknown;
  query?: Record<string, string | number | boolean | undefined | null | string[]>;
  form?: FormData;
  auth?: boolean;
};

function buildUrl(path: string, query?: Options['query']) {
  const url = new URL(`${API_URL}${API_PREFIX}${path}`);
  Object.entries(query ?? {}).forEach(([key, value]) => {
    if (value === undefined || value === null || value === '') return;
    if (Array.isArray(value)) value.forEach((v) => url.searchParams.append(key, v));
    else url.searchParams.set(key, String(value));
  });
  return url.toString();
}

async function parseError(response: Response): Promise<ApiError> {
  try {
    const body = (await response.json()) as ApiErrorBody;
    return new ApiError(response.status, body.error.code, body.error.message, body.error.details);
  } catch {
    return new ApiError(response.status, 'HTTP_ERROR', 'Something went wrong. Please try again.');
  }
}

/** Single-flight refresh: concurrent 401s share one refresh request. */
async function refreshTokens(): Promise<boolean> {
  const refreshToken = session?.getRefreshToken();
  if (!refreshToken) return false;
  if (!refreshing) {
    refreshing = (async () => {
      try {
        const response = await fetch(buildUrl('/auth/refresh'), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ refresh_token: refreshToken }),
        });
        if (!response.ok) return false;
        await session?.onTokens((await response.json()) as TokenPair);
        return true;
      } catch {
        return false;
      } finally {
        setTimeout(() => (refreshing = null), 0);
      }
    })();
  }
  return refreshing;
}

async function request<T>(method: string, path: string, options: Options = {}, retry = true): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  const token = options.auth === false ? undefined : session?.getAccessToken();
  if (token) headers.Authorization = `Bearer ${token}`;
  const orgId = session?.getOrganizationId();
  if (orgId && options.auth !== false) headers['X-Organization-Id'] = orgId;
  let body: BodyInit | undefined;
  if (options.form) body = options.form;
  else if (options.body !== undefined) {
    headers['Content-Type'] = 'application/json';
    body = JSON.stringify(options.body);
  }

  let response: Response;
  try {
    response = await fetch(buildUrl(path, options.query), { method, headers, body });
  } catch {
    throw new ApiError(0, 'NETWORK_ERROR', "You're offline or the server can't be reached.");
  }

  if (response.status === 401 && retry && options.auth !== false) {
    if (await refreshTokens()) return request<T>(method, path, options, false);
    await session?.onSignedOut();
  }
  if (!response.ok) throw await parseError(response);
  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  get: <T>(path: string, query?: Options['query']) => request<T>('GET', path, { query }),
  post: <T>(path: string, body?: unknown, auth = true) => request<T>('POST', path, { body: body ?? {}, auth }),
  patch: <T>(path: string, body: unknown) => request<T>('PATCH', path, { body }),
  delete: <T>(path: string) => request<T>('DELETE', path),
  upload: <T>(path: string, form: FormData) => request<T>('POST', path, { form }),
};

export function errorMessage(error: unknown): string {
  if (error instanceof ApiError) {
    const fields = (error.details?.fields as { field: string; message: string }[] | undefined) ?? [];
    return fields.length ? `${error.message} ${fields.map((f) => `${f.field}: ${f.message}`).join('; ')}` : error.message;
  }
  return 'Something went wrong. Please try again.';
}
