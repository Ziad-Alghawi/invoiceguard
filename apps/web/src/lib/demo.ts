import type { Role } from "@/lib/invoices";

export type DemoLogin = { role: Role; email: string; password: string };

const VARIABLES: [Role, string, string][] = [
  ["reviewer", "DEMO_LOGIN_EMAIL", "DEMO_LOGIN_PASSWORD"],
  ["approver", "DEMO_APPROVER_EMAIL", "DEMO_APPROVER_PASSWORD"],
];

/**
 * The shared demo accounts (ADR-006, ADR-014, ADR-016): a reviewer from the server-only
 * `DEMO_LOGIN_EMAIL` and `DEMO_LOGIN_PASSWORD`, and an approver from `DEMO_APPROVER_EMAIL` and
 * `DEMO_APPROVER_PASSWORD`, read per request. An account shows only when both of its variables
 * are set; outside the public demo none are, and the login page shows no credentials.
 */
export function getDemoLogins(): DemoLogin[] {
  const logins: DemoLogin[] = [];
  for (const [role, emailVariable, passwordVariable] of VARIABLES) {
    const email = process.env[emailVariable];
    const password = process.env[passwordVariable];
    if (email && password) {
      logins.push({ role, email, password });
    }
  }
  return logins;
}
