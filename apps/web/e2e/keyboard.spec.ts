import { expect, test } from "@playwright/test";

import {
  apiAs,
  history,
  invoiceXml,
  logIn,
  reviewerLogin,
  upload,
} from "./helpers";

/**
 * Keyboard only (P1): j/k in the queue, Enter opens, a approves after the confirmation, ? shows
 * the keys, Esc goes back to the queue.
 */

const login = reviewerLogin();
const run = Date.now().toString();
const invoice = { number: `E2E-${run}-KEYS`, file: `e2e-${run}-keys.xml` };

test.beforeAll(async () => {
  const api = await apiAs(login);
  const xml = await invoiceXml(
    "ubl_xrechnung.xml",
    "2026-IT-0815",
    invoice.number,
  );
  expect(await upload(api, invoice.file, xml)).toBe("ready");
  await api.dispose();
});

test("approve a ready invoice by keyboard", async ({ page }) => {
  await logIn(page, login);
  const link = page.getByRole("link", { name: invoice.file });
  await expect(link).toBeVisible();

  // j moves through the queue until the invoice has the focus; Enter opens it.
  for (let step = 0; step < 25; step += 1) {
    await page.keyboard.press("j");
    if (await link.evaluate((element) => element === document.activeElement)) {
      break;
    }
  }
  await expect(link).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.getByRole("heading", { name: invoice.file })).toBeVisible();

  // ? lists the keys; Esc closes the list, not the invoice.
  await page.keyboard.press("?");
  const help = page.getByRole("dialog", { name: "Tastenkürzel" });
  await expect(help).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(help).toBeHidden();
  await expect(page.getByRole("heading", { name: invoice.file })).toBeVisible();

  // a asks first; Enter confirms (the confirm button has the focus).
  await page.keyboard.press("a");
  const confirm = page.getByRole("dialog", {
    name: "Diese Rechnung freigeben?",
  });
  await expect(confirm).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(
    page.getByText(
      "Keine Entscheidung möglich, solange die Rechnung freigegeben ist.",
    ),
  ).toBeVisible();

  // Esc goes back to the queue.
  await page.keyboard.press("Escape");
  await expect(
    page.getByRole("heading", { name: "Rechnungseingang" }),
  ).toBeVisible();
});
