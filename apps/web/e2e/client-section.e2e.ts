import { expect, test } from "@playwright/test";
import { registerAgency } from "./helpers";

test("client section: create, edit, brand profile, knowledge, archive and restore", async ({ page }) => {
  await registerAgency(page, "clients");
  // Next keeps the previous page mounted but hidden, so scope text checks to the active tab.
  const panel = page.getByRole("tabpanel");

  // Empty clients list -> create a client.
  await page.goto("/clients");
  await expect(page.getByText("No clients yet")).toBeVisible();
  await page.getByRole("button", { name: "New client" }).click();
  await page.getByLabel("Name").fill("Acme Pets");
  await page.getByLabel("Industry (optional)").fill("Pet food");
  await page.getByRole("button", { name: "Create client" }).click();
  await expect(page.getByRole("heading", { name: "Acme Pets" })).toBeVisible();
  await expect(page.getByRole("tab", { name: "Overview" })).toHaveAttribute("aria-selected", "true");
  await expect(panel.getByText("Pet food")).toBeVisible();
  await page.screenshot({ path: "test-results/shots/client-overview.png" });

  // Edit: change industry, add a goal.
  await page.getByRole("button", { name: "Edit client" }).click();
  await page.getByLabel("Industry (optional)").fill("Organic pet treats");
  await page.getByLabel("Goals (one per line)").fill("Grow online sales\nLaunch newsletter");
  await page.getByRole("button", { name: "Save changes" }).click();
  await expect(panel.getByText("Organic pet treats")).toBeVisible();
  await expect(panel.getByText("Launch newsletter")).toBeVisible();

  // Brand profile: starts empty (API 404), save, reload, still there.
  await page.getByRole("tab", { name: "Brand profile" }).click();
  await expect(page.getByLabel("Voice")).toHaveValue("");
  await page.getByLabel("Voice").fill("Warm");
  await page.getByLabel("Tone").fill("Playful");
  await page.getByLabel("Keywords (one per line)").fill("dogs\ntreats");
  await page.getByRole("button", { name: "Save profile" }).click();
  await expect(page.getByRole("button", { name: "Save profile" })).toBeDisabled();
  await page.screenshot({ path: "test-results/shots/brand-profile.png" });
  await page.reload();
  await page.getByRole("tab", { name: "Brand profile" }).click();
  await expect(page.getByLabel("Voice")).toHaveValue("Warm");
  await expect(page.getByLabel("Keywords (one per line)")).toHaveValue("dogs\ntreats");

  // Knowledge: paste text, upload a file, both reach Ready (needs the Celery worker).
  await page.getByRole("tab", { name: "Knowledge" }).click();
  await expect(panel.getByText("No documents yet")).toBeVisible();
  await page.getByLabel("Title").fill("Voice notes");
  await page.getByLabel("Text", { exact: true }).fill("Acme sells organic dog treats made in Portland.");
  await page.getByRole("button", { name: "Add text" }).click();
  await expect(panel.getByText("Voice notes")).toBeVisible();

  await page.getByLabel("Upload file").setInputFiles({
    name: "competitors.txt",
    mimeType: "text/plain",
    buffer: Buffer.from("Competitors include BarkBox and Chewy. Our edge is local peanut butter."),
  });
  await expect(panel.getByText("competitors.txt")).toBeVisible();
  await expect(panel.getByText("Ready")).toHaveCount(2, { timeout: 30_000 });
  await page.screenshot({ path: "test-results/shots/knowledge.png" });

  // Wrong file type is blocked in the browser with a clear message.
  await page.getByLabel("Upload file").setInputFiles({
    name: "photo.png",
    mimeType: "image/png",
    buffer: Buffer.from("not really a png"),
  });
  await expect(panel.getByText("Use a PDF, DOCX, TXT or MD file")).toBeVisible();

  // Re-index and delete (with confirmation).
  await page.getByRole("button", { name: "Re-index Voice notes" }).click();
  await expect(panel.getByText("Ready")).toHaveCount(2, { timeout: 30_000 });
  await page.getByRole("button", { name: "Delete competitors.txt" }).click();
  await page.getByRole("button", { name: "Delete document" }).click();
  await expect(panel.getByText("competitors.txt")).toHaveCount(0);

  // Archive with confirmation, then restore.
  await page.getByRole("tab", { name: "Overview" }).click();
  await page.getByRole("button", { name: "Archive", exact: true }).click();
  await expect(page.getByText(/can be restored/i)).toBeVisible();
  await page.getByRole("button", { name: "Archive client" }).click();
  await expect(page.getByText("Archived", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Restore" }).click();
  await expect(page.getByText("Archived", { exact: true })).toHaveCount(0);

  // The list shows the client and links back to it.
  await page.goto("/clients");
  await page.getByRole("link", { name: /Acme Pets/ }).click();
  await expect(page.getByRole("heading", { name: "Acme Pets" })).toBeVisible();
});
