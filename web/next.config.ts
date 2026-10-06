import type { NextConfig } from "next";

// In production Caddy routes /api/* to the backend. In `next dev` the same path is proxied here.
const API_ORIGIN = process.env.SUNS_API_ORIGIN ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  poweredByHeader: false,
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [{ source: "/api/:path*", destination: `${API_ORIGIN}/api/:path*` }]
      : [];
  },
};

export default nextConfig;
