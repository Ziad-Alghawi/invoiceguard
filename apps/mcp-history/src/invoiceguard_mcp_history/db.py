"""Read-only database access for the MCP server (ADR-017).

The server logs in as its own PostgreSQL role, which has SELECT on the history views, the
rulebook and the embeddings' vectors only (migration 0013 in apps/api). Every transaction is
also READ ONLY, a second guard should a grant ever be too wide. Queries are fixed SQL with
parameters; no tool takes SQL.

One short connection per tool call: the agent makes a handful of calls per invoice, so a pool
would add a dependency for no measurable gain.
"""

from dataclasses import dataclass
from typing import Any

import psycopg
from psycopg.rows import dict_row

CONNECT_TIMEOUT_SECONDS = 3


@dataclass(frozen=True)
class Database:
    # A libpq connection string or URL (postgresql://...), with the server's own role.
    conninfo: str

    def rows(self, query: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        with psycopg.connect(
            self.conninfo, connect_timeout=CONNECT_TIMEOUT_SECONDS, row_factory=dict_row
        ) as connection:
            connection.read_only = True
            return connection.execute(query, params).fetchall()
