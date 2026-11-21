import { execFileSync } from "node:child_process";
import { expect, type Page } from "@playwright/test";

export const PASSWORD = "E2ePassw0rd!";

/** Registers a brand-new agency (unique email) and waits for the signed-in dashboard. */
export async function registerAgency(page: Page, label: string) {
  const id = `${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`;
  const email = `e2e-${label}-${id}@example.com`;
  await page.goto("/register");
  await page.getByLabel("Agency name").fill(`E2E ${label} ${id}`);
  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password", { exact: true }).fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();
  await expect(page.getByText("Agency overview")).toBeVisible();
  return { email, agency: `E2E ${label} ${id}` };
}

// Runs SQL as the DB owner (bypasses RLS) to seed usage. In CI, set E2E_DATABASE_URL to a
// libpq URL; locally it goes through the compose Postgres container.
export function sql(query: string): string {
  const url = process.env.E2E_DATABASE_URL;
  const [cmd, args] = url
    ? ["psql", [url, "-tA", "-c", query]]
    : ["docker", ["exec", "marketpilot-postgres-1", "psql", "-U", "marketpilot", "-d", "marketpilot", "-tA", "-c", query]];
  return execFileSync(cmd as string, args as string[], { encoding: "utf8" }).trim();
}
