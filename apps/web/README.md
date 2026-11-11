# apps/web

Next.js (App Router, TypeScript, Tailwind, shadcn/ui, next-intl de/en) review queue UI for approving, rejecting and
editing invoices; filled from R1.

Today it has one page that calls the API's `GET /health` on the server and shows `ok` or `unreachable`.

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

Start the API (`apps/api`) to see `ok`; without it the page shows `unreachable`.

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
