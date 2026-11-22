import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

import de from "../../messages/de.json";
import en from "../../messages/en.json";
import {
  AGENT_RUN_STATUSES,
  AUDIT_ACTIONS,
  CHECK_STATUSES,
  CHECK_TYPES,
  FIELD_NAMES,
  INVOICE_STATUSES,
  REASON_CODES,
  ROLES,
  SECURITY_EVENT_TYPES,
  SEVERITIES,
} from "@/lib/codes";

/**
 * The API is the source of the codes: these tests read its Python source, so a new status,
 * check, action or event type there fails here until the web has a label for it in both
 * languages (messages/*.json, "Codes").
 */

const API = path.join(
  __dirname,
  "..",
  "..",
  "..",
  "api",
  "src",
  "invoiceguard_api",
);

function source(...parts: string[]): string {
  return readFileSync(path.join(API, ...parts), "utf-8");
}

function sorted(values: Iterable<string>): string[] {
  return [...new Set(values)].sort();
}

/** The values of a Python StrEnum class in models.py. */
function enumValues(name: string): string[] {
  const models = source("models.py");
  const body = models
    .split(`class ${name}(enum.StrEnum):`)[1]
    ?.split(/\nclass |\ndef /)[0];
  expect(body, `class ${name} in models.py`).toBeDefined();
  return sorted(
    [...body!.matchAll(/^\s+[A-Z_]+ = "([a-z_]+)"$/gm)].map((m) => m[1]),
  );
}

function pythonFiles(directory: string): string[] {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const full = path.join(directory, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "__pycache__" ? [] : pythonFiles(full);
    }
    return entry.name.endsWith(".py") ? [full] : [];
  });
}

describe("codes match the API", () => {
  it.each([
    ["InvoiceStatus", INVOICE_STATUSES],
    ["CheckStatus", CHECK_STATUSES],
    ["UserRole", ROLES],
    ["SecuritySeverity", SEVERITIES],
    ["AgentRunStatus", AGENT_RUN_STATUSES],
  ])("%s", (name, codes) => {
    expect(sorted(codes)).toEqual(enumValues(name));
  });

  it("check types (CHECK_TYPE of each check module)", () => {
    const types = pythonFiles(path.join(API, "checks")).flatMap((file) =>
      [
        ...readFileSync(file, "utf-8").matchAll(/^CHECK_TYPE = "([a-z_]+)"$/gm),
      ].map((m) => m[1]),
    );
    expect(sorted(CHECK_TYPES)).toEqual(sorted(types));
  });

  it("security event types (security.py)", () => {
    const types = [
      ...source("security.py").matchAll(/^[A-Z_]+ = "([a-z_]+)"$/gm),
    ].map((m) => m[1]);
    expect(sorted(SECURITY_EVENT_TYPES)).toEqual(sorted(types));
  });

  it("audit actions (every 'auth.', 'invoice.', 'demo.' and 'user.' string)", () => {
    const actions = pythonFiles(API).flatMap((file) =>
      [
        ...readFileSync(file, "utf-8").matchAll(
          /"((?:auth|invoice|demo|user)\.[a-z_]+)"/g,
        ),
      ].map((m) => m[1]),
    );
    expect(sorted(AUDIT_ACTIONS)).toEqual(sorted(actions));
  });

  it("status reason codes (ReasonCode in status_reasons.py)", () => {
    const literal = source("status_reasons.py").match(
      /ReasonCode = Literal\[([^\]]*)\]/,
    );
    expect(literal, "ReasonCode in status_reasons.py").not.toBeNull();
    const codes = [...literal![1].matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
    expect(sorted(REASON_CODES)).toEqual(sorted(codes));
  });

  it("field names (parsing/fields.py)", () => {
    const names = [
      ...source("parsing", "fields.py").matchAll(
        /^\s+"([a-z_]+)": "BT-\d+",$/gm,
      ),
    ].map((m) => m[1]);
    expect(sorted(FIELD_NAMES)).toEqual(sorted(names));
  });
});

type Tree = { [key: string]: string | Tree };

function label(messages: Tree, group: string, code: string): unknown {
  return [group, ...code.split(".")].reduce<unknown>(
    (node, key) =>
      typeof node === "object" && node !== null
        ? (node as Tree)[key]
        : undefined,
    messages.Codes,
  );
}

describe("every code has a label", () => {
  const groups: [string, readonly string[]][] = [
    ["invoiceStatus", INVOICE_STATUSES],
    ["checkStatus", CHECK_STATUSES],
    ["role", ROLES],
    ["severity", SEVERITIES],
    ["runStatus", AGENT_RUN_STATUSES],
    ["checkType", CHECK_TYPES],
    ["auditAction", AUDIT_ACTIONS],
    ["securityEvent", SECURITY_EVENT_TYPES],
    ["field", FIELD_NAMES],
    ["reason", REASON_CODES],
  ];

  it.each([
    ["de", de],
    ["en", en],
  ])("in %s", (_locale, messages) => {
    const missing = groups.flatMap(([group, codes]) =>
      codes
        .filter(
          (code) => typeof label(messages as Tree, group, code) !== "string",
        )
        .map((code) => `${group}.${code}`),
    );
    expect(missing).toEqual([]);
  });
});
