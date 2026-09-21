import type { NextConfig } from "next";

const isStaticExport = process.env.STATIC_EXPORT === "true";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  ...(isStaticExport ? { output: "export" as const, trailingSlash: true } : {}),
};

export default nextConfig;
