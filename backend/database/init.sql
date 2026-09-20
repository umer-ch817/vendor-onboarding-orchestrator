-- Vendor Onboarding & Risk Orchestrator
-- Postgres bootstrap. Mounted at /docker-entrypoint-initdb.d/init.sql, so it
-- runs once, on an empty data directory, before the backend starts.
--
-- This file deliberately does NOT create the application tables. The tables
-- are owned by the SQLAlchemy models in app/models/__init__.py and created by
-- Base.metadata.create_all() on application startup, so that the schema has
-- exactly one source of truth and cannot drift between a DDL file and the
-- ORM. Duplicating the DDL here would guarantee that drift.
--
-- What belongs here is everything that must be true of the database itself,
-- independent of the application: extensions, timezone, and the privileges
-- the application role needs.

-- gen_random_uuid() for future use, and citext for case-insensitive
-- comparisons if the schema later needs it. Both are shipped with official
-- Postgres images; CREATE EXTENSION IF NOT EXISTS keeps the file re-runnable.
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

-- pg_trgm supplies gin_trgm_ops, the operator class the trigram index on
-- vendors.legal_name requires. Without it, CREATE INDEX ... USING gin
-- (legal_name) fails with "no default operator class for access method gin".
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Timestamps in this system are written as naive UTC by the application
-- (datetime.utcnow). Pinning the database timezone to UTC means a developer
-- querying the tables directly sees the same wall clock the application
-- recorded, rather than a server-local rendering of it.
SET timezone = 'UTC';
ALTER DATABASE vendordb SET timezone TO 'UTC';

-- Default privileges for objects the application role creates later.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO vendoruser;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT ON SEQUENCES TO vendoruser;

-- The application connects as vendoruser, which owns the database created by
-- the postgres image, so it already holds these rights. The grants above make
-- the requirement explicit rather than incidental.

-- Sanity check: fail loudly at bootstrap if the timezone did not take, rather
-- than surfacing it months later as a confusing date offset.
DO $$
BEGIN
    IF current_setting('TimeZone') <> 'UTC' THEN
        RAISE EXCEPTION 'Expected database timezone UTC, got %', current_setting('TimeZone');
    END IF;
END
$$;
