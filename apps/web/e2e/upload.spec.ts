import { expect, test } from "@playwright/test";

import { history, invoiceXml, logIn, reviewerLogin } from "./helpers";

/**
 * The upload page (R2-7): a reviewer uploads an XRechnung XML, sees it checked and finds it in
 * the queue; the same file again is refused as a duplicate with a link to the first one.
 */

const run = Date.now().toString();
const file = `e2e-${run}-upload.xml`;

test("upload an XML invoice and find it in the queue", async ({ page }) => {
  const xml = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    `E2E-${run}-UP`,
  );
  await logIn(page, reviewerLogin());

  await page.getByRole("link", { name: "Hochladen", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Rechnung hochladen" }),
  ).toBeVisible();
  const chooser = page.getByLabel("Rechnungsdatei");
  await chooser.setInputFiles({
    name: file,
    mimeType: "application/xml",
    buffer: xml,
  });
  await page.getByRole("button", { name: "Hochladen" }).click();
  await expect(
    page.getByText("Alle Prüfungen bestanden.", { exact: false }),
  ).toBeVisible({
    timeout: 60_000,
  });

  // The same file again: refused, with a link to the invoice it duplicates.
  await chooser.setInputFiles({
    name: file,
    mimeType: "application/xml",
    buffer: xml,
  });
  await page.getByRole("button", { name: "Hochladen" }).click();
  await expect(
    page.getByText("Diese Datei wurde bereits hochgeladen."),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Vorhandene Rechnung öffnen" }),
  ).toBeVisible();

  // The new invoice waits in the review queue.
  await page.getByRole("link", { name: "← Rechnungseingang" }).click();
  await expect(page.getByRole("link", { name: file })).toBeVisible();
  await page.getByRole("link", { name: file }).click();
  await expect(
    history(page).getByText("Eingegangen", { exact: true }),
  ).toBeVisible();
});
