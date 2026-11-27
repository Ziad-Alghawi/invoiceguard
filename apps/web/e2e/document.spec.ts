import { expect, test } from "@playwright/test";

import {
  apiAs,
  invoiceXml,
  logIn,
  reviewerLogin,
  upload,
  uploadFixture,
} from "./helpers";

/**
 * The split view (P1, ADR-029): a ZUGFeRD PDF drawn by pdf.js with the clicked field marked,
 * and an XRechnung shown as the KoSIT visualization with the clicked term marked.
 */

const login = reviewerLogin();
const run = Date.now().toString();
const xml = { number: `E2E-${run}-VIEW`, file: `e2e-${run}-view.xml` };
let pdfId = "";

test.beforeAll(async () => {
  const api = await apiAs(login);
  pdfId = await uploadFixture(
    api,
    "zugferd-buerobedarf.pdf",
    "application/pdf",
  );
  const content = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    xml.number,
  );
  expect(await upload(api, xml.file, content)).toBe("ready");
  await api.dispose();
});

test("click the IBAN of a PDF invoice: its place on the page is marked", async ({
  page,
}) => {
  await logIn(page, login);
  await page.goto(`/invoices/${pdfId}`);
  const pdfPage = page.getByRole("img", { name: "Seite 1 von 1" });
  await expect(pdfPage).toBeVisible();
  await expect(page.getByTestId("pdf-highlight")).toHaveCount(0);

  await page
    .getByRole("button", {
      name: "IBAN des Zahlungsempfängers im Dokument zeigen",
    })
    .click();
  const mark = pdfPage.getByTestId("pdf-highlight");
  await expect(mark).toBeVisible();
  const box = await mark.boundingBox();
  const sheet = await pdfPage.boundingBox();
  expect(box && sheet && box.width > 20 && box.y > sheet.y).toBeTruthy();
});

test("open an XRechnung: the visualization shows it, the clicked term is marked", async ({
  page,
}) => {
  await logIn(page, login);
  await page.getByRole("link", { name: xml.file }).click();
  const frame = page.frameLocator(
    'iframe[title="E-Rechnung in der KoSIT-XRechnung-Visualisierung"]',
  );
  await expect(frame.getByText(xml.number).first()).toBeVisible();
  await expect(frame.locator("#highlight")).toHaveCount(0);

  await page
    .getByRole("button", {
      name: "IBAN des Zahlungsempfängers im Dokument zeigen",
    })
    .click();
  const mark = frame.locator("#highlight");
  await expect(mark).toBeVisible();
  await expect(mark).toHaveClass(/BT-84/);
});
