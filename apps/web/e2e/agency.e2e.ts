import { expect, test } from "@playwright/test";
import { registerAgency } from "./helpers";

test("dashboard: getting-started checklist, New client, and agency settings", async ({ page }) => {
  const { agency } = await registerAgency(page, "agency");

  // First run: the checklist starts with the agency done.
  const checklist = page.getByRole("region", { name: "Getting started" });
  await expect(checklist).toBeVisible();
  await expect(checklist.getByText("1 of 4 done")).toBeVisible();

  // The dashboard's New client button works (it used to be a disabled placeholder).
  await page.getByRole("button", { name: "New client" }).click();
  await page.getByRole("dialog").getByLabel("Name", { exact: true }).fill("Dashboard Co");
  await page.getByRole("button", { name: "Create client" }).click();
  await expect(page.getByRole("heading", { name: "Dashboard Co" })).toBeVisible();

  // Back on the dashboard the checklist has moved on.
  await page.goto("/");
  await expect(page.getByRole("region", { name: "Getting started" }).getByText("2 of 4 done")).toBeVisible();
  await page.getByRole("button", { name: "Dismiss" }).click();
  await expect(page.getByRole("region", { name: "Getting started" })).toHaveCount(0);
  await page.reload();
  await expect(page.getByText("Agency overview")).toBeVisible();
  await expect(page.getByRole("region", { name: "Getting started" })).toHaveCount(0); // stays dismissed

  // Agency settings: rename, and the dashboard heading follows.
  await page.goto("/settings/agency");
  await expect(page.getByLabel("Agency name")).toHaveValue(agency);
  await page.getByLabel("Agency name").fill("Renamed Agency");
  await page.getByRole("button", { name: "Save name" }).click();
  await expect(page.getByRole("button", { name: "Save name" })).toBeDisabled();

  // Branding validates on the client, then persists across a reload.
  await page.getByLabel("Primary color (optional)").fill("green");
  await page.getByRole("button", { name: "Save branding" }).click();
  await expect(page.getByText("Use a hex color like #1f6f43")).toBeVisible();
  await page.getByLabel("Primary color (optional)").fill("#1f6f43");
  await page.getByLabel("Logo URL (optional)").fill("https://cdn.example.com/logo.png");
  await page.getByLabel("Report footer (optional)").fill("Prepared by Renamed Agency");
  await page.getByRole("button", { name: "Save branding" }).click();
  await expect(page.getByRole("button", { name: "Save branding" })).toBeDisabled();
  await page.reload();
  await expect(page.getByLabel("Agency name")).toHaveValue("Renamed Agency");
  await expect(page.getByLabel("Primary color (optional)")).toHaveValue("#1f6f43");
  await expect(page.getByLabel("Report footer (optional)")).toHaveValue("Prepared by Renamed Agency");

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "Renamed Agency" })).toBeVisible();
});
