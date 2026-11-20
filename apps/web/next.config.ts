import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  cacheComponents: true,
  partialPrefetching: true,
  // Route handlers under app/api/auth win over this (afterFiles); everything
  // else under /api is proxied to FastAPI so the browser stays same-origin.
  async rewrites() {
    const apiUrl = process.env.API_URL ?? "http://localhost:8000/api/v1";
    return {
      beforeFiles: [],
      afterFiles: [{ source: "/api/:path*", destination: `${apiUrl}/:path*` }],
      fallback: [],
    };
  },
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
