import { expect, test } from "@playwright/test";

import { reviewerLogin } from "./helpers";

/**
 * The language switch (ADR-027): German by default, English on request, kept in a cookie across
 * reloads and the login, and back to German from the header. The paths stay the same.
 */
test("the UI starts in German and switches to English and back", async ({
  page,
}) => {
  await page.goto("/login");
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  await expect(page.getByRole("button", { name: "Anmelden" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Deutsch" })).toHaveAttribute(
    "aria-pressed",
    "true",
  );

  await page.getByRole("button", { name: "English" }).click();
  await expect(page.getByRole("button", { name: "Log in" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  await expect(page).toHaveURL(/\/login$/);

  // A full load reads the cookie: still English, <html lang> set before the first paint.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("lang", "en");
  const login = reviewerLogin();
  await page.getByLabel("Email").fill(login.email);
  await page.getByLabel("Password").fill(login.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(
    page.getByRole("heading", { name: "Invoice queue" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "To review" })).toBeVisible();

  await page.getByRole("button", { name: "Deutsch" }).click();
  await expect(
    page.getByRole("heading", { name: "Rechnungseingang" }),
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "Zu prüfen" })).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("lang", "de");
  await expect(page).toHaveURL(/\/invoices$/);
});
