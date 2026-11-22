# Security policy

InvoiceGuard is a portfolio project with a public demo. It holds made-up sample data only, and it has no
tool that pays, posts bookings or writes to an ERP or a registry. Security reports are still welcome:
safety is the point of the project.

## Supported versions

| Version | Supported |
| --- | --- |
| 1.0.x (the `main` branch and the demo) | yes |
| older commits | no |

## Reporting a vulnerability

Please report privately through GitHub: **Security → Report a vulnerability** on this repository. Do not open a
public issue for a vulnerability.

Include what you found, the steps to reproduce it, and what an attacker could do with it. You will get an
answer within a week. A confirmed problem is fixed in a pull request that names the report (after the fix is
released, unless you prefer not to be named).

## Scope

In scope:

- the code in this repository (api, web, MCP servers, eval harness, Helm charts, CI workflows);
- the demo at https://invoiceguard.ziadalghawi.com, within the limits below;
- ways to make the agent or a model act on invoice text, to reach data a component's database role should not
  see, or to approve an invoice without the four-eyes rule.

Out of scope:

- locking the shared demo accounts with wrong passwords (a known limitation, reset nightly);
- volume tests, denial of service and automated scans against the demo (it runs on one small server);
- findings in dependencies without a way to use them here (Dependabot and Trivy track those).

When you test the demo, use made-up data only and do not try to reach other services on the server.

## How the project defends itself

The design is in the README ([Safety design](README.md#safety-design)) and the ADRs: untrusted invoice text as
data, read-only tools with one database role each, an approval gate that the API enforces, append-only audit and
security logs, pinned and scanned dependencies and images, and an eval gate with an attack set in CI.
