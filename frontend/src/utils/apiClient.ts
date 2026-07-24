import { createClient } from '@/utils/supabase/client';

interface ApiOptions extends RequestInit {
  data?: any;
}

/**
 * Returns the current Supabase access token, or null when signed out.
 * Shared by apiClient and the streaming fetch in useChat.
 */
export async function getAccessToken(): Promise<string | null> {
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();
  return session?.access_token ?? null;
}

export async function apiClient<T>(
  endpoint: string,
  { data, ...customConfig }: ApiOptions = {},
): Promise<T> {
  // A1: fetch the current Supabase session so every request carries a valid Bearer token.
  // getSession() returns cached data but Supabase refreshes automatically before expiry.
  const supabase = createClient();
  const { data: { session } } = await supabase.auth.getSession();

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(customConfig.headers as Record<string, string>),
  };

  if (session?.access_token) {
    headers['Authorization'] = `Bearer ${session.access_token}`;
  }

  const config: RequestInit = {
    method: data ? 'POST' : 'GET',
    ...customConfig,
    headers,
  };

  if (data) {
    try {
      // Validates data can be cleanly stringified before sending.
      config.body = JSON.stringify(data);
    } catch (err) {
      throw new Error(`Failed to stringify payload for ${endpoint}`);
    }
  }

  const response = await fetch(endpoint, config);

  // Handle empty responses (like 204 No Content).
  if (response.status === 204) return null as unknown as T;

  let responseData;
  try {
    responseData = await response.json();
  } catch (err) {
    throw new Error(`Server returned invalid JSON from ${endpoint}`);
  }

  if (response.ok) {
    return responseData;
  } else {
    // FastAPI surfaces errors under `detail`; fall back to `message` then status.
    const detail = responseData?.detail || responseData?.message;
    return Promise.reject(new Error(detail || `API Error: ${response.status}`));
  }
}
