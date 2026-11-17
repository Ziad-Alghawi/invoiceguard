"""Create or reset login users from environment variables (ADR-006, ADR-016). There is no sign-up.

    INVOICEGUARD_SEED_USER_EMAIL=anna@example.com
    INVOICEGUARD_SEED_USER_PASSWORD=...           # at least 12 characters, never committed
    INVOICEGUARD_SEED_USER_NAME="Anna Becker"     # optional
    INVOICEGUARD_SEED_USER_ROLE=reviewer          # optional: reviewer (default) or approver

    # Optional: a second user with the approver role, for the four-eyes override.
    INVOICEGUARD_SEED_APPROVER_EMAIL=ben@example.com
    INVOICEGUARD_SEED_APPROVER_PASSWORD=...
    INVOICEGUARD_SEED_APPROVER_NAME="Ben Wagner"  # optional

Run with `make seed-user` or `uv run invoiceguard-seed-user`. Running it again for the same email
sets the new password, name and role and clears a lockout.
"""

import logging
import os
import sys

from pydantic import Field, SecretStr, ValidationError
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import select
from sqlalchemy.orm import Session

from invoiceguard_api.auth import hash_password, normalise_email
from invoiceguard_api.db import make_engine, make_session_factory
from invoiceguard_api.logging import configure_logging
from invoiceguard_api.models import AuditEvent, User, UserRole
from invoiceguard_api.settings import get_settings

logger = logging.getLogger(__name__)

SEED_ACTOR = "seed"
MIN_PASSWORD_LENGTH = 12
USER_PREFIX = "INVOICEGUARD_SEED_USER_"
APPROVER_PREFIX = "INVOICEGUARD_SEED_APPROVER_"


class _SeedSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix=USER_PREFIX, extra="ignore", env_ignore_empty=True)

    email: str = Field(min_length=3, max_length=255, pattern=r"^[^@\s]+@[^@\s]+$")
    password: SecretStr = Field(min_length=MIN_PASSWORD_LENGTH, max_length=1024)
    name: str = Field(default="Demo Reviewer", min_length=1, max_length=255)


class SeedUserSettings(_SeedSettings):
    role: UserRole = UserRole.REVIEWER


class SeedApproverSettings(_SeedSettings):
    """The optional second user; always an approver."""

    model_config = SettingsConfigDict(
        env_prefix=APPROVER_PREFIX, extra="ignore", env_ignore_empty=True
    )

    name: str = Field(default="Demo Approver", min_length=1, max_length=255)

    @property
    def role(self) -> UserRole:
        return UserRole.APPROVER


SeedSettings = SeedUserSettings | SeedApproverSettings


def upsert_user(
    session: Session,
    email: str,
    display_name: str,
    password: str,
    role: UserRole = UserRole.REVIEWER,
) -> User:
    """Create the user, or set the password, name and role of an existing one and unlock it."""
    email = normalise_email(email)
    user = session.scalar(select(User).where(User.email == email))
    action = "user.updated" if user is not None else "user.created"
    if user is None:
        user = User(email=email, failed_logins=0)
        session.add(user)
    user.display_name = display_name
    user.password_hash = hash_password(password)
    user.role = role
    user.failed_logins = 0
    user.locked_until = None
    session.flush()
    session.add(
        AuditEvent(
            actor=SEED_ACTOR,
            action=action,
            entity_type="user",
            entity_id=str(user.id),
            details={"email": email, "role": role.value},
        )
    )
    return user


def _load[T: _SeedSettings](settings_class: type[T], prefix: str) -> T:
    try:
        return settings_class()
    except ValidationError as error:
        fields = ", ".join(prefix + str(detail["loc"][0]).upper() for detail in error.errors())
        # Never print the input: it may be the password.
        sys.exit(
            f"Set {fields} (password: at least {MIN_PASSWORD_LENGTH} characters; role: reviewer "
            "or approver; see .env.example)."
        )


def seed_users() -> list[SeedSettings]:
    """The users to seed: always the first, and the approver when its email is set."""
    users: list[SeedSettings] = [_load(SeedUserSettings, USER_PREFIX)]
    if os.environ.get(APPROVER_PREFIX + "EMAIL"):
        approver = _load(SeedApproverSettings, APPROVER_PREFIX)
        if normalise_email(approver.email) == normalise_email(users[0].email):
            sys.exit(
                f"{USER_PREFIX}EMAIL and {APPROVER_PREFIX}EMAIL must differ: four eyes need two "
                "people."
            )
        users.append(approver)
    return users


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    users = seed_users()
    engine = make_engine(str(settings.database_url))
    try:
        with make_session_factory(engine)() as session:
            for seed in users:
                upsert_user(
                    session, seed.email, seed.name, seed.password.get_secret_value(), seed.role
                )
            session.commit()
    finally:
        engine.dispose()
    for seed in users:
        logger.info("Seeded %s %s", seed.role.value, normalise_email(seed.email))
