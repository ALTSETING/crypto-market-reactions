import "server-only";

export class EnvironmentConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EnvironmentConfigurationError";
  }
}

function isServiceRoleJwt(value: string): boolean {
  if (value.startsWith("sb_secret_")) return true;
  if (!value.startsWith("eyJ")) return false;

  try {
    const payload = value.split(".")[1];
    if (!payload) return false;
    const decoded = JSON.parse(Buffer.from(payload, "base64url").toString("utf8")) as {
      role?: string;
    };
    return decoded.role === "service_role";
  } catch {
    return false;
  }
}

export function getSupabaseEnvironment(): {
  url: string;
  anonKey: string;
} {
  const url = process.env.SUPABASE_URL?.trim();
  const anonKey = process.env.SUPABASE_ANON_KEY?.trim();

  if (!url || !anonKey) {
    throw new EnvironmentConfigurationError(
      "Server configuration is incomplete. SUPABASE_URL and SUPABASE_ANON_KEY are required.",
    );
  }

  let parsed: URL;
  try {
    parsed = new URL(url);
  } catch {
    throw new EnvironmentConfigurationError("SUPABASE_URL is not a valid URL.");
  }

  if (parsed.protocol !== "https:" && parsed.hostname !== "localhost") {
    throw new EnvironmentConfigurationError("SUPABASE_URL must use HTTPS.");
  }
  if (isServiceRoleJwt(anonKey)) {
    throw new EnvironmentConfigurationError(
      "SUPABASE_ANON_KEY must not contain a service-role or secret key.",
    );
  }

  return { url: parsed.toString().replace(/\/$/, ""), anonKey };
}
