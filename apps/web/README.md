# apps/web

Next.js (App Router, TypeScript, Tailwind, shadcn/ui, next-intl de/en) review queue UI for approving, rejecting and
editing invoices; filled from R1.

Pages:

| Path             | What it shows                                                                                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/`              | API health (`ok` / `unreachable`) and a link to the queue                                                                                                                                                                           |
| `/login`         | Login with a seeded user (no sign-up)                                                                                                                                                                                               |
| `/invoices`      | Review queue with status filters (to review, blocked, approved, rejected, processing/failed, all) and paging; "Export to DATEV" downloads the approved, not yet exported invoices as a booking file (ADR-013)                       |
| `/invoices/[id]` | Check results with evidence, extracted fields (low-confidence ones highlighted with the printed snippet), download of the original, approve / reject (a blocked invoice needs an override reason and a confirmation), audit history |

The browser talks only to this server ("backend for frontend"): server components and server actions call the API with
the session cookie, which the login action copies from the API's answer into an HttpOnly cookie on this origin
([ADR-011](../../docs/decisions/ADR-011-session-cookie-auth.md)). [src/proxy.ts](src/proxy.ts) redirects to `/login`
when there is no cookie; the API decides whether a session is valid and enforces every decision rule.

## Languages

German (default) and English with next-intl ([ADR-027](../../docs/decisions/ADR-027-ui-languages.md)): the DE | EN
switch in the header and on the login page sets the `NEXT_LOCALE` cookie, and the paths stay the same. Every UI text is
in [messages/de.json](messages/de.json) and [messages/en.json](messages/en.json); add a new text to both.
`src/lib/codes.ts` lists the API codes that get a label. The tests fail on a key missing in one file or a code without
a label, `tsc` on an unknown key, and ESLint on text written into JSX. Status reasons written by processing come with a code and are translated (`components/status-reason.tsx`);
other texts written by the API stay English.

## Requirements

- Node.js 24, pnpm 10 (`corepack enable` picks the version from `package.json`)

## Configuration

| Variable  | Example                 | Purpose                                  |
| --------- | ----------------------- | ---------------------------------------- |
| `API_URL` | `http://localhost:8000` | Base URL of `apps/api` (no trailing `/`) |

Next.js reads `.env*` files from this folder, so copy the `apps/web` block of the root `.env.example` into
`apps/web/.env.local`. `API_URL` is server-only and read on every request, not at build time, so one build (or Docker
image) works in every environment: set it where the server runs. Do not use a `NEXT_PUBLIC_` prefix for it; those
values are inlined into the build.

## Run

```sh
pnpm install
pnpm dev            # http://localhost:3000
pnpm build && pnpm start
```

Start the API (`apps/api`) to see `ok`; without it the page shows `unreachable`. To log in, seed a user first
(`make seed-user`, see the root README).

## Check

```sh
pnpm lint           # eslint
pnpm typecheck      # next typegen + tsc --noEmit (strict)
pnpm format:check   # prettier (pnpm format to fix)
pnpm test           # vitest (pnpm test:watch while developing)
pnpm build
```

## End-to-end test

[e2e/review-and-export.spec.ts](e2e/review-and-export.spec.ts) (Playwright, Chromium) runs against the Docker
Compose stack: it uploads a clean and a changed-IBAN XRechnung through the API, then in the browser logs in, rejects
the blocked one with a reason, approves the clean one, exports to DATEV and checks the downloaded file. It calls no
LLM. From the repo root: `make dev && make seed && make seed-user`, then `make e2e` (it reads the seed user from
`.env`). CI runs the same in the `e2e` job.

## Docker

The [Dockerfile](Dockerfile) builds with `output: "standalone"` and copies only the standalone server and static
assets into a `node:24-alpine` image that runs as the non-root `node` user on port 3000. `API_URL` is not needed at
build time; pass it when the container starts. The whole stack (api + web + db) starts with `make dev` from the repo
root; see [infra](../../infra/README.md).
