import { defineConfig, devices } from "@playwright/test";

// End-to-end tests run against a real stack: Postgres + Redis (docker compose), the API
// (uvicorn :8000), a Celery worker (document indexing) and the web app (:3000).
// Start them first, then: pnpm e2e
export default defineConfig({
  testDir: "./e2e",
  testMatch: "**/*.e2e.ts", // keeps vitest (which matches *.test / *.spec) from picking these up
  timeout: 90_000,
  expect: { timeout: 20_000 }, // the Next dev server compiles each route on first visit
  workers: 1,
  reporter: [["list"]],
  outputDir: "./test-results",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
