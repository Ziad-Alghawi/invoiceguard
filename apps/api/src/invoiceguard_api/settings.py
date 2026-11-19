"""Application settings, read from environment variables prefixed with INVOICEGUARD_."""

from decimal import Decimal
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, Field, PostgresDsn, SecretStr, UrlConstraints
from pydantic_settings import BaseSettings, SettingsConfigDict

from invoiceguard_api.llm import ReasoningEffort

Environment = Literal["dev", "test", "prod"]
LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR"]

# Only the psycopg 3 driver is installed, so the URL must name it explicitly.
DatabaseUrl = Annotated[PostgresDsn, UrlConstraints(allowed_schemes=["postgresql+psycopg"])]

MIB = 1024 * 1024


class Settings(BaseSettings):
    # An empty variable counts as unset, so Compose can pass `${VAR:-}` for optional settings.
    model_config = SettingsConfigDict(
        env_prefix="INVOICEGUARD_", extra="ignore", env_ignore_empty=True
    )

    env: Environment = "dev"
    log_level: LogLevel = "INFO"
    database_url: DatabaseUrl
    storage_dir: Path = Path("data/uploads")
    max_upload_bytes: int = Field(default=10 * MIB, gt=0)
    # Uploads per user in the last hour, counted from the audit log; more get 429. Unset: no limit.
    upload_max_per_hour: int | None = Field(default=None, gt=0)
    # KoSIT validator service (ADR-009). Unset: the KoSIT check is skipped, nothing else changes.
    validator_url: AnyHttpUrl | None = None
    validator_timeout_seconds: float = Field(default=20.0, gt=0)
    # LLM extraction of plain PDFs (ADR-004, ADR-010). No key: PDFs stay `awaiting_extraction`.
    llm_api_key: SecretStr | None = None
    # A LiteLLM model string; its price must be in LiteLLM's price table (ADR-004).
    extraction_model: str = "gemini/gemini-3.8-flash"
    # Thinking tokens are billed as output; `low` is the lowest level Gemini 3.8 Flash accepts in
    # the pinned LiteLLM version (`minimal` is sent as `low`), see ADR-010.
    extraction_reasoning_effort: ReasoningEffort = "low"
    llm_timeout_seconds: float = Field(default=120.0, gt=0)
    # Fields extracted with a lower confidence get a `low_confidence` check result. 0.9 because the
    # R3-2 eval found most wrong fields at 0.8 to 0.9 (ADR-019).
    extraction_confidence_threshold: Decimal = Field(default=Decimal("0.9"), ge=0, le=1)
    # Spending cap per UTC day in US dollars, summed from `model_calls`. Once reached, PDFs wait in
    # `awaiting_extraction` until a later restart (ADR-014). Unset: no cap.
    llm_daily_budget_usd: Decimal | None = Field(default=None, gt=0)
    # Booking suggestions (ADR-020): a LiteLLM embedding model whose vectors have the size of the
    # `embeddings.vector` column (768). Changing it means running `invoiceguard-index` again.
    embedding_model: str = "gemini/gemini-embedding-001"
    # The rulebook's Markdown files (docs/rulebook), indexed by `invoiceguard-index`; the api
    # image has them at /app/rulebook. Unset: the index leaves the rulebook as it is.
    rulebook_dir: Path | None = None
    # Exception agent (ADR-018): investigates blocked invoices with the read-only MCP servers
    # (ADR-017). It runs only with a model key and the three MCP URLs; otherwise the
    # "Investigate" button shows a recorded run where one exists.
    mcp_erp_url: AnyHttpUrl | None = None
    mcp_registry_url: AnyHttpUrl | None = None
    mcp_history_url: AnyHttpUrl | None = None
    mcp_timeout_seconds: float = Field(default=10.0, gt=0)
    # A LiteLLM model string; unset: the extraction model.
    agent_model: str | None = None
    agent_reasoning_effort: ReasoningEffort = "low"
    # Limits per run; reaching one stops the run cleanly ("stopped" with the reason).
    agent_max_steps: int = Field(default=8, ge=1, le=20)
    agent_max_tool_calls: int = Field(default=12, ge=1, le=50)
    agent_timeout_seconds: float = Field(default=90.0, gt=0)
    # US dollars per invoice, summed over every agent call ever made for it.
    agent_cost_cap_usd: Decimal = Field(default=Decimal("0.05"), gt=0)
    # Investigate every invoice that processing leaves `blocked` (when the agent can run).
    agent_auto_investigate: bool = True
    # Login sessions (ADR-011): fixed lifetime, then log in again.
    session_ttl_minutes: int = Field(default=8 * 60, gt=0)
    # This many failed logins in a row lock the account for `login_lockout_minutes`.
    login_max_failures: int = Field(default=5, gt=0)
    login_lockout_minutes: int = Field(default=15, gt=0)
    # DATEV-style booking export (ADR-013). The defaults are placeholders for a demo client on
    # SKR03; a real export needs the numbers and accounts the tax advisor uses for the client.
    datev_advisor_number: int = Field(default=1001, ge=1001, le=9_999_999)
    datev_client_number: int = Field(default=1, ge=1, le=99_999)
    # First month of the fiscal year; DATEV accepts one fiscal year per file.
    datev_fiscal_year_start_month: int = Field(default=1, ge=1, le=12)
    datev_account_length: int = Field(default=4, ge=4, le=8)
    datev_chart_of_accounts: Literal["03", "04"] = "03"
    # Konto: the creditor (supplier) account. One collective creditor until suppliers get their
    # own creditor numbers.
    datev_creditor_account: str = Field(default="70000", pattern=r"^\d{5,9}$")
    # Gegenkonto: the expense account, not an automatic tax account (the BU key adds the tax).
    # SKR03 4900 "Sonstige betriebliche Aufwendungen". The accounts reviewers choose per line
    # (ADR-020) are not exported yet.
    datev_expense_account: str = Field(default="4900", pattern=r"^\d{4,8}$")
    # Input VAT rate -> BU key (SKR03: 9 = 19 % Vorsteuer, 8 = 7 % Vorsteuer). Set as JSON in
    # the environment, for example {"19": "9", "7": "8"}.
    datev_tax_keys: dict[Decimal, Annotated[str, Field(pattern=r"^\d{1,4}$")]] = {
        Decimal(19): "9",
        Decimal(7): "8",
    }

    # The public demo (ADR-014): allows `invoiceguard-demo-reset`, which deletes every invoice,
    # and refuses PDF uploads without embedded e-invoice XML (no visitor PDF goes to a model).
    demo_mode: bool = False

    @property
    def secure_cookies(self) -> bool:
        """Session cookies only over HTTPS in prod; dev and test run on plain http://localhost."""
        return self.env == "prod"


@lru_cache
def get_settings() -> Settings:
    return Settings()
