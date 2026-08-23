import "server-only";

export class EnvironmentConfigurationError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "EnvironmentConfigurationError";
  }
}

function isElevatedServerKey(value: string): boolean {
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
  serverKey: string;
} {
  const url = process.env.SUPABASE_URL?.trim();
  const serverKey =
    process.env.SUPABASE_SECRET_KEY?.trim() ||
    process.env.SUPABASE_SERVICE_ROLE_KEY?.trim();

  if (!url || !serverKey) {
    throw new EnvironmentConfigurationError(
      "Server configuration is incomplete. SUPABASE_URL and a Supabase server secret are required.",
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
  if (!isElevatedServerKey(serverKey)) {
    throw new EnvironmentConfigurationError(
      "Use SUPABASE_SECRET_KEY (preferred) or a legacy SUPABASE_SERVICE_ROLE_KEY.",
    );
  }

  return { url: parsed.toString().replace(/\/$/, ""), serverKey };
}
