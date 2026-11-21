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
