# ADR-020: Booking suggestions by retrieval over pgvector, with Gemini embeddings

- **Status:** Accepted
- **Date:** 2026-11-19

## Context

Every approved invoice still books to one expense account (`datev_expense_account`, SKR03 4900,
ADR-013). Accounts payable clerks choose an account per invoice line, usually the one they chose for
the same kind of line before. PLAN section 9 asks for RAG over approved bookings: suggest an account
per line with the evidence, and let a person decide (PLAN section 3: the agent proposes, humans
decide). R3-4 also brings agent tools that search the history and a rulebook; they are a second PR and
extend this ADR.

Forces:

- **No new database** (PLAN section 4): PostgreSQL 16 with pgvector is already the image we run.
- **Code first** (ADR-002): a suggestion must be explainable and testable; a chat model choosing an
  account would be neither cheap nor easy to check.
- **The demo has no model key** (ADR-010, ADR-014), so nothing a visitor uploads may need a model.
- **Poisoning** (PLAN section 5, ASI06): what enters the index is later shown as evidence and, in the
  second PR, given to the agent.
- **Cost and replay** (ADR-019): CI replays recorded replies; embeddings must be recorded the same way.

## Decision

**Suggestions are retrieval plus a vote, in code. Only the line texts are embedded.**

- **Embedding model:** `gemini/gemini-embedding-001` through LiteLLM (`LLMClient` gained
  `Embedder.embed`), **768 dimensions**, task type `SEMANTIC_SIMILARITY` (a line is compared with
  other lines, not a question with documents). Why:
  - same provider and key as extraction, no second account (ADR-004);
  - multilingual and good at short German texts; it is text only, which is all we need;
  - 768 is one of Google's recommended reduced sizes (Matryoshka training), a quarter of the
    3,072 default at little loss; it stays under pgvector's 2,000-dimension limit for an HNSW index
    should we need one; a packaged vector is 3 KB;
  - $0.15 per million input tokens in the pinned price table; the whole eval embedded 93 texts
    for $0.0002;
  - checked with one live call before writing code: LiteLLM 1.108.1 maps `dimensions` and
    `task_type`, returns usage and a price. The vectors are not normalised at 768, so we compare
    with cosine distance.
- **Storage:** `embeddings` (model, text hash, text, `vector(768)`), one row per normalised text
  (NFC, whitespace collapsed, at most 500 characters) and model, so a line text repeated on many
  invoices is embedded once. `bookings` holds one row per booked line: the account the person
  chose, the top suggestion at that moment, who chose it, supplier, invoice number and date, and
  `searchable`. Imported history (source `import`) uses the same table without an invoice.
- **When:** the lines of a new invoice are embedded in a background task after processing
  (upload and reopen), within the daily budget, logged in `model_calls` (purpose `embedding`). A
  failure changes nothing on the invoice. Approval writes the bookings in the decide node's
  transaction (ADR-015), so an approved invoice is in the index at once.
- **Retrieval:** the 10 bookings closest to the line by cosine similarity, plus 0.1 when the
  booking is from the same supplier (the supplier filter of PLAN section 9, as a preference, so a
  new supplier still gets suggestions). A line without a vector (no key, budget, a failed call) uses
  a trigram text match (`pg_trgm`) with the same bonus, labelled "by text match" in the UI. An exact
  scan: at thousands of rows it takes milliseconds; an HNSW index can come with volume.
- **Vote:** each neighbour weighs exp((score - best) / 0.05); an account's weight is the sum of its
  neighbours' weights, and the top three come with their share and up to three source bookings.
  The first design summed raw similarities; the first eval run showed that the compressed
  similarity range of the model (unrelated item names still score about 0.8) let the account with
  the most neighbours win, even over an exact match. We changed it after seeing the test set, so
  `docs/results.md` reports both designs.
- **A person decides:** `/approve` and `/override/confirm` take an account per line (all lines or
  none, each from a short SKR03 list in `booking/accounts.py`). The web preselects the top
  suggestion and shows its evidence; the reviewer can change it. The audit row lists the choices.
- **Guardrails:** only approved invoices are indexed. An invoice that failed the prompt-injection
  check keeps its bookings as the record of the decision but with `searchable = false`, so its text
  is never retrieved for another invoice. An invoice is never its own evidence. Retrieved text is
  shown escaped in the UI and is untrusted data like invoice text.
- **History and the demo:** `invoiceguard-eval generate` writes a made-up booking history (10
  suppliers, 79 invoices, 159 lines) into the api package; `invoiceguard-eval vectors` writes its
  vectors and those of the demo samples' lines from the recorded embeddings. The demo reset and
  `invoiceguard-index` (`make index`) import both; `make index` also embeds every text without a
  vector when a key is set (after a model change, all of them). On the demo, the samples are
  suggested by vector and visitors' uploads by text match.
- **Eval** (`booking_eval.py`): 62 held-out lines (a booked wording, a held-out wording of the same
  item, a supplier without history), top-1 and top-3 accuracy against the item's account, hit@k
  and MRR for retrieval (relevant: a booking of the same item), the text match, the first design
  and two baselines without retrieval. The CI gate also fails when vector top-1 drops more than 2
  points.

## Alternatives

- **A chat model picks the account from retrieved examples:** more flexible with unseen items, but
  a model call per invoice, a prompt-injection surface, and harder to explain; the vote reached
  98 % top-1 on our set. Possible later for lines with weak evidence, as a new LLM step (ADR-002).
- **`gemini-embedding-2`:** newer and multimodal at $0.20 per million; we embed short texts only.
  A candidate for the R4 model comparison, as are local models through Ollama.
- **OpenAI `text-embedding-3-small`:** cheaper, but a second provider and key.
- **A separate vector database (Qdrant, Chroma):** another service to run and back up, for a few
  thousand rows that PostgreSQL scans in milliseconds.
- **Full-text search only:** no key and no cost, but it matches words, not meaning: on held-out
  wordings it was right in 82 % of lines against 100 % by vector.
- **Embed a whole invoice:** one vector would mix lines with different accounts; accounts are per
  line.

## Consequences

- Reviewers see a suggestion with its sources on every line; the choice is stored next to what was
  suggested, so acceptance can be measured on real use later.
- The DATEV export does not use the chosen accounts yet: it still writes one row per invoice to
  the default account (ADR-013); one row per account and tax rate is a follow-up (issue).
- New dependency in the api: `pgvector` 0.5.1 (the SQLAlchemy `Vector` type; no NumPy). New
  extensions `vector` and `pg_trgm` (both in the pgvector image); the migration needs a user that
  may create extensions.
- Vectors are tied to the model and the column size: another model means a new `make index`
  (old rows stay and are ignored), another size a migration.
- The eval set is generated by the same person who wrote the catalogue, with distinct wordings per
  item and 62 test lines; real bookings are noisier (the same text booked to two accounts, typing
  errors). The numbers show that the mechanism works, not how it does on a real ledger.
- `create_app` takes an `embedder`; a given `llm_client` does not embed, so the fraud and attack
  evals need no embedding recordings.

## Update 2026-11-19: the rulebook and the agent's history tools (R3-4b)

The second PR of R3-4 adds what PLAN section 9 calls the rulebook, and gives the agent the history (ADR-017,
ADR-018).

- **Rulebook:** `docs/rulebook`, 10 short English files with the German terms written in (one per check, the
  review rules, SKR03 guidance), split by `##` heading into 42 sections of at most 1,500 characters; a longer one is
  an error, not cut. `rulebook_chunks` (migration 0013) holds them with their file's SHA-256 as the version, a
  generated `tsvector` (English and German stemmers, GIN index) and a vector.
- **Vectors on the chunks, other task types.** Rulebook search compares a question with passages, not two lines, so
  sections are embedded with `RETRIEVAL_DOCUMENT` and questions with `RETRIEVAL_QUERY` (same model, 768 dimensions);
  the vector sits on `rulebook_chunks` rather than in `embeddings`, whose key (model, text) assumes one task.
  `invoiceguard-index` and the demo reset sync the table (a changed section loses its vector) and load packaged
  vectors written from the eval's recordings, so the demo and CI need no key.
- **Search:** by vector when the api sends the question's vector; otherwise full text, the question's words joined
  by OR (a natural question rarely has all its words in one section) and ranked with `ts_rank`. Measured on 20
  questions: hit@3 90 % by vector in both languages; full text 90 % for English, 50 % for German.
- **The image gets the files** through a named build context (`additional_contexts` in Compose), so the api's
  build context stays `apps/api` and the rulebook has one copy.

Alternatives: the rulebook in the api package (two places to edit, or a copy and a drift test); one vector store for
lines and sections (one key would mix task types); German and English sections (twice the text to keep in step).

Consequences: changing a section means new packaged vectors (`invoiceguard-eval vectors --live`), or the section is
found by full text only; a test fails while a section has none. German questions without a key do noticeably
worse.
