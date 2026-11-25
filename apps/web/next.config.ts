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
  // Headers that cannot break the app: no framing, no MIME sniffing, and a CSP limited to the
  // directives that need no per-request nonce (SRS section 11).
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Content-Security-Policy",
            value: "frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'",
          },
        ],
      },
    ];
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
