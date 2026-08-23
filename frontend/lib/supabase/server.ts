import "server-only";

import { createClient, type SupabaseClient } from "@supabase/supabase-js";

import { getSupabaseEnvironment } from "@/lib/env";

let cachedClient: SupabaseClient | undefined;

export function getSupabaseServerClient(): SupabaseClient {
  if (cachedClient) return cachedClient;

  const { url, anonKey } = getSupabaseEnvironment();
  cachedClient = createClient(url, anonKey, {
    auth: {
      autoRefreshToken: false,
      detectSessionInUrl: false,
      persistSession: false,
    },
    global: {
      headers: { "X-Client-Info": "crypto-market-reaction-mvp/0.1" },
    },
  });
  return cachedClient;
}
