import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Missing event slugs must produce an HTTP 404, not a streamed soft-404.
  htmlLimitedBots: /.*/,
  poweredByHeader: false,
};

export default nextConfig;
