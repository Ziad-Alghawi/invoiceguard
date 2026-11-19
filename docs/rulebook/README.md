# Rulebook

The accounts-payable rules the exception agent can look up with `search_rulebook` (R3-4b): what each check means,
its thresholds, how to resolve it, and which SKR03 account fits which line. English, with the German terms written
in, because questions come in both languages.

- One file per topic, about a page each: a `# ` title, then `## ` sections. Each section is one search result
  (at most 1,500 characters; `invoiceguard-index` refuses a longer one), so a section must make sense on its own.
- `make index` (and the nightly demo reset) syncs the files into `rulebook_chunks`. A changed section loses its
  vector until it is embedded again: with a model key `make index` does it; for the demo and CI, record the new
  vectors with `invoiceguard-eval vectors --live` (packages/evals) and commit
  `apps/api/src/invoiceguard_api/rulebook/vectors.json`. A test fails while a section has no packaged vector.
- The questions of the retrieval eval (`packages/evals/src/invoiceguard_evals/rulebook_eval.py`) name sections by
  `file#anchor`; renaming a heading changes its anchor.
- This text is reviewed like code, but the agent still treats what it returns as data.
