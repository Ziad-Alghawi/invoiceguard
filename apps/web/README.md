# apps/web

Next.js (App Router, TypeScript, Tailwind, shadcn/ui, next-intl de/en) review queue UI for approving, rejecting and
editing invoices; filled from R1.

Pages:

| Path             | What it shows                                                                                                                                                                                                                       |
| ---------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `/`              | API health (`ok` / `unreachable`) and a link to the queue                                                                                                                                                                           |
| `/login`         | Login with a seeded user (no sign-up)                                                                                                                                                                                               |
| `/invoices`      | Review queue with status filters (to review, blocked, approved, rejected, processing/failed, all) and paging                                                                                                                        |
| `/invoices/[id]` | Check results with evidence, extracted fields (low-confidence ones highlighted with the printed snippet), download of the original, approve / reject (a blocked invoice needs an override reason and a confirmation), audit history |

The browser talks only to this server ("backend for frontend"): server components and server actions call the API with
the session cookie, which the login action copies from the API's answer into an HttpOnly cookie on this origin
([ADR-011](../../docs/decisions/ADR-011-session-cookie-auth.md)). [src/proxy.ts](src/proxy.ts) redirects to `/login`
when there is no cookie; the API decides whether a session is valid and enforces every decision rule.

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

## Docker

The [Dockerfile](Dockerfile) builds with `output: "standalone"` and copies only the standalone server and static
assets into a `node:24-alpine` image that runs as the non-root `node` user on port 3000. `API_URL` is not needed at
build time; pass it when the container starts. The whole stack (api + web + db) starts with `make dev` from the repo
root; see [infra](../../infra/README.md).
