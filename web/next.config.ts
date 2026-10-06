import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Образ Docker собирается из .next/standalone — без полного node_modules.
  output: "standalone",
  poweredByHeader: false,
  // В разработке /api уходит в локальный backend; на сервере /api разводит
  // gateway (infra/gateway.conf) и сюда запросы не доходят.
  async rewrites() {
    return process.env.NODE_ENV === "development"
      ? [{ source: "/api/:path*", destination: "http://127.0.0.1:8000/api/:path*" }]
      : [];
  },
};

export default nextConfig;
