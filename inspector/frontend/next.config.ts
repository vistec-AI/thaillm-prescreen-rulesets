import type { NextConfig } from "next";

const isProd = process.env.NODE_ENV === "production";

const nextConfig: NextConfig = {
  // Static export for production — FastAPI serves the files
  ...(isProd ? { output: "export" } : {}),

  // Proxy API and asset requests to the FastAPI backend during development
  ...(!isProd
    ? {
        async rewrites() {
          return [
            { source: "/api/:path*", destination: "http://localhost:8000/api/:path*" },
            { source: "/assets/:path*", destination: "http://localhost:8000/assets/:path*" },
          ];
        },
      }
    : {}),

  // next/image doesn't work with static export — use unoptimized images
  images: { unoptimized: true },
};

export default nextConfig;
