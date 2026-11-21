# ADR-027: German and English UI with next-intl, language in a cookie

- **Status:** Accepted
- **Date:** 2026-11-22

## Context

The users are accounts-payable staff in German SMEs (PLAN.md §3, "German market first"), so the UI
has to be German. Reviewers of the project read English. Until R5 every text in `apps/web` was
written in English directly in the components.

Three facts shape the choice:

- Every page apart from the login and home pages needs a session, and none is meant to be indexed or
  shared by link. One language per URL brings nothing to an internal tool.
- `cacheComponents` is on. A cookie read in the root layout would make the whole tree request-bound
  and remove the static shell (Next.js docs, "Migrating to Cache Components").
- The API writes check messages, status reasons, error details and the agent's finding in English.
  Translating them means a message code with parameters for each of about 32 check results, which is
  backend work beyond R5.

## Decision

Use **next-intl** (4.15.1, pinned exactly) without locale routing. **German is the default**, and
English is chosen with a DE | EN switch in the header and on the login page. The choice is kept in the
`NEXT_LOCALE` cookie for one year. Paths do not change.

- `src/i18n/request.ts` reads the cookie, and `messages/de.json` and `messages/en.json` hold every UI
  text. Dates are shown in the active language and always in Europe/Berlin time.
- The root layout renders its children inside a Suspense boundary, where the locale is read.
  `<html lang>` starts as `de`, and a small inline script sets it from the cookie before the first
  paint, following the pattern in the Next.js docs. A client effect updates it after the switch.
- The switch is a form with a server action, so it works without JavaScript: it sets the cookie and
  refreshes the page.
- Codes from the API (statuses, check types, roles, audit actions, security event types, field names)
  get a label in both languages. A code the web does not know is shown as it is.
- **Text written by the API stays English** and is marked `lang="en"` where it is shown as a block
  (check messages, the agent's finding). The agent's email draft stays German, as before.

Four checks keep it complete:

- The message keys are typed from `en.json`, so an unknown key fails `tsc`.
- `messages.test.ts` checks that both files have the same keys and no empty text, and that every
  message parses and formats with the arguments of its English text.
- `codes.test.ts` reads the API's Python source and fails when a status, check type, audit action,
  event type or field name has no label in both languages.
- ESLint `react/jsx-no-literals` fails on text written into JSX (the product name and `·` are
  allowed). Attribute strings such as `aria-label` are outside the rule and are checked in review.

## Alternatives

- **Locale in the URL (`/de/…`, `[locale]` segment and middleware):** the next-intl default and right
  for public sites. Here it would change every path, the proxy matcher, the e2e tests and the
  ingress, and buy no SEO for pages behind a login.
- **Negotiate from `Accept-Language`:** a visitor with an English browser would land in English,
  while the demo should open in German. It would also make the default less predictable for tests.
- **Translate the API's messages now:** see Context; it remains a possible later task.
- **A smaller library (`use-intl` alone, or a hand-written dictionary):** next-intl is what PLAN.md
  names and the documented choice for the App Router, with server components, server actions and route
  handlers covered.

## Consequences

- No page has a prerendered shell with text any more: the text depends on the cookie. Before, only
  the login and home pages had one; everything else already waited for the session.
- The UI mixes languages where the API's text appears in the German UI. The README lists this as a
  limitation.
- next-intl pulls in a message extractor (`@swc/core`, `@parcel/watcher`, the `@eloqnt/*` packages)
  that this app does not use. Three `@eloqnt` packages are pinned to older releases in
  `pnpm-workspace.yaml`, because their newest releases were under a week old (the ADR-004 rule
  applied to this dependency too). The overrides can go with the next next-intl upgrade.
- A new UI text needs an entry in both files, and a new API code needs a label: the tests above say
  which one is missing.
