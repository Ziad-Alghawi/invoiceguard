"""Create or reset one login user from environment variables (ADR-006). There is no sign-up.

    INVOICEGUARD_SEED_USER_EMAIL=anna@example.com
    INVOICEGUARD_SEED_USER_PASSWORD=...           # at least 12 characters, never committed
    INVOICEGUARD_SEED_USER_NAME="Anna Becker"     # optional

Run with `make seed-user` or `uv run invoiceguard-seed-user`; run it once per user. Running it
again for the same email sets the new password and name and clears a lockout.
"""

import logging
import sys

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.auth import hash_password, normalise_email
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.models import AuditEvent, User
from invoiceguard_api.settings import get_settings

logger = logging.getLogger(__name__)

SEED_ACTOR = "seed"
MIN_PASSWORD_LENGTH = 12


class SeedUserSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="INVOICEGUARD_SEED_USER_", extra="ignore", env_ignore_empty=True
    )

    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    name: str = Field(default="Demo Reviewer", min_length=1, max_length=255)


def upsert_user(session: Session, email: str, display_name: str, password: str) -> User:
    """Create the user, or set the password and name of an existing one and unlock it."""
    email = normalise_email(email)
    user = session.scalar(select(User).where(User.email == email))
    action = "user.updated" if user is not None else "user.created"
    if user is None:
        user = User(email=email, failed_logins=0)
        session.add(user)
    user.display_name = display_name
    user.password_hash = hash_password(password)
    user.failed_logins = 0
    user.locked_until = None
    session.flush()
    session.add(
        AuditEvent(
            actor=SEED_ACTOR,
            action=action,
            entity_type="user",
            entity_id=str(user.id),
            details={"email": email},
        )
    )
    return user


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    try:
        seed = SeedUserSettings()
    except ValidationError as error:
        fields = ", ".join(
            "INVOICEGUARD_SEED_USER_" + str(detail["loc"][0]).upper() for detail in error.errors()
        )
        # Never print the input: it may be the password.
        sys.exit(
            f"Set {fields} (password: at least {MIN_PASSWORD_LENGTH} characters; see .env.example)."
        )
    engine = make_engine(str(settings.database_url))
    try:
        with make_session_factory(engine)() as session:
            upsert_user(session, seed.email, seed.name, seed.password.get_secret_value())
            session.commit()
    finally:
        engine.dispose()
    logger.info("Seeded user %s", normalise_email(seed.email))
