import { readFile } from "node:fs/promises";
import path from "node:path";

import {
  type APIRequestContext,
  expect,
  type Page,
  request,
} from "@playwright/test";

/**
 * Shared steps of the end-to-end tests. Invoices are uploaded through the API (the UI has no
 * upload page yet), each with an invoice number unique to the run, so the tests can run again
 * on the same stack without hitting the duplicate checks.
 */

export const API_URL = process.env.E2E_API_URL ?? "http://localhost:8000";
const FIXTURES = path.join(__dirname, "..", "..", "api", "tests", "fixtures");
const PROCESSING_TIMEOUT_MS = 60_000;

export type Login = { email: string; password: string };

function env(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(`${name} is not set: run the tests with \`make e2e\``);
  }
  return value;
}

/** The seeded reviewer (`make seed-user`). */
export function reviewerLogin(): Login {
  return {
    email: env("INVOICEGUARD_SEED_USER_EMAIL"),
    password: env("INVOICEGUARD_SEED_USER_PASSWORD"),
  };
}

/** The seeded approver (`make seed-user` with INVOICEGUARD_SEED_APPROVER_*). */
export function approverLogin(): Login {
  return {
    email: env("INVOICEGUARD_SEED_APPROVER_EMAIL"),
    password: env("INVOICEGUARD_SEED_APPROVER_PASSWORD"),
  };
}

/** An API client with the user's session. */
export async function apiAs(login: Login): Promise<APIRequestContext> {
  const api = await request.newContext({ baseURL: API_URL });
  const response = await api.post("/auth/login", { data: login });
  expect(response.status(), await response.text()).toBe(200);
  return api;
}

/** A fixture with another invoice number (BT-1). */
export async function invoiceXml(fixture: string, from: string, to: string) {
  const xml = await readFile(path.join(FIXTURES, fixture), "utf-8");
  const changed = xml.replace(
    `<cbc:ID>${from}</cbc:ID>`,
    `<cbc:ID>${to}</cbc:ID>`,
  );
  expect(changed).not.toBe(xml);
  return Buffer.from(changed, "utf-8");
}

/** Uploads an invoice and waits until processing has finished; returns its status. */
export async function upload(
  api: APIRequestContext,
  name: string,
  xml: Buffer,
) {
  const response = await api.post("/invoices", {
    multipart: { file: { name, mimeType: "application/xml", buffer: xml } },
  });
  expect(response.status(), await response.text()).toBe(202);
  const { id } = (await response.json()) as { id: string };
  let status = "received";
  await expect
    .poll(
      async () => {
        const detail = await api.get(`/invoices/${id}`);
        status = ((await detail.json()) as { status: string }).status;
        return status;
      },
      { timeout: PROCESSING_TIMEOUT_MS },
    )
    .not.toMatch(/^(received|processing)$/);
  return status;
}

/** Logs in through the web form and waits for the queue. */
export async function logIn(page: Page, login: Login) {
  await page.goto("/login");
  await page.getByLabel("Email").fill(login.email);
  await page.getByLabel("Password").fill(login.password);
  await page.getByRole("button", { name: "Log in" }).click();
  await expect(
    page.getByRole("heading", { name: "Invoice queue" }),
  ).toBeVisible();
}
