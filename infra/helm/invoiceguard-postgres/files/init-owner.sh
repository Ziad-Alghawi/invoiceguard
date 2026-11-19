#!/bin/sh
# Runs once, on an empty data directory, as the superuser (the image's docker-entrypoint-initdb.d).
# Creates the owner that runs the migrations without being a superuser (ADR-023): it may create the
# restricted roles (CREATEROLE; in PostgreSQL 16 it can then manage only the roles it created) and
# owns the database, so it owns its `public` schema. `vector` is not a trusted extension, so the
# superuser creates it here; the migration's CREATE EXTENSION IF NOT EXISTS then finds it.
set -eu

psql --set ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  --set owner="$INVOICEGUARD_DB_OWNER" \
  --set password="$INVOICEGUARD_DB_OWNER_PASSWORD" \
  --set db="$INVOICEGUARD_DB_NAME" <<'SQL'
CREATE ROLE :"owner" WITH LOGIN NOSUPERUSER NOCREATEDB CREATEROLE NOREPLICATION PASSWORD :'password';
CREATE DATABASE :"db" OWNER :"owner";
\connect :db
CREATE EXTENSION vector;
CREATE EXTENSION pg_trgm;
SQL
