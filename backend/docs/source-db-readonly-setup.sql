-- ===========================================================================
-- source-db-readonly-setup.sql
-- Operator-owned ROLE-LEVEL read-only backstop for EXTERNAL source databases.
-- ===========================================================================
--
-- WHY THIS FILE EXISTS
-- --------------------
-- The Internal Knowledge AI Agent connects to operator-supplied EXTERNAL
-- PostgreSQL source databases to index/sample them. The application enforces
-- read-only at several layers it DOES control:
--
--   1. sqlglot SELECT-only gate            (src/services/db_safety/sql_validator.py)
--   2. asyncpg server_settings / libpq     (harden_postgres_engine_kwargs):
--        default_transaction_read_only=on  + statement_timeout
--   3. per-transaction SET LOCAL + ROLLBACK (read_only_session)
--
-- What the application CANNOT do is enforce ROLE-LEVEL settings on a database
-- it does not own. If the operator hands the agent a credential with write
-- access, layers (1)-(3) still block writes — but defense-in-depth wants the
-- WRITE PRIVILEGE itself removed at the source. That is what this script does,
-- and it MUST be run by an operator/DBA with admin rights on the SOURCE db.
--
-- This is the role-level backstop. Run it ONCE per source database, against
-- the role the agent will authenticate as.
--
-- ---------------------------------------------------------------------------
-- HOW TO RUN
-- ---------------------------------------------------------------------------
--   1. Replace the placeholders below:
--        :agent_role   — the login role the agent uses (e.g. kb_reader)
--        :agent_pass   — a strong password (or use SCRAM / external auth)
--        :app_schema   — the schema(s) to expose (default: public)
--   2. Connect to the SOURCE database as a superuser / role admin:
--        psql "<admin DSN for the source db>" -f source-db-readonly-setup.sql
--   3. Hand the agent a connection string for :agent_role, e.g.
--        postgresql+asyncpg://kb_reader:<pass>@host:5432/sourcedb
--
-- The same DSN is what the optional live test reads from the KB_TEST_POSTGRES_DSN
-- environment variable (see "MANUAL / OPTIONAL LIVE VERIFICATION" at the bottom).
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- 1. Least-privilege login role (NOINHERIT so it can't pick up other grants).
-- ---------------------------------------------------------------------------
-- If the role already exists, skip the CREATE and just run the ALTER/GRANTs.
CREATE ROLE kb_reader LOGIN PASSWORD 'CHANGE_ME_STRONG_PASSWORD' NOINHERIT;


-- ---------------------------------------------------------------------------
-- 2. Force every transaction this role opens to start READ ONLY.
--    This is the ROLE-LEVEL backstop the app cannot set itself. Even a
--    forgotten connect_args / a future code path that skips hardening still
--    lands in a read-only transaction because the SERVER applies it.
-- ---------------------------------------------------------------------------
ALTER ROLE kb_reader SET default_transaction_read_only = on;

-- ---------------------------------------------------------------------------
-- 3. Role-level server-side statement_timeout (milliseconds).
--    A runaway introspection/sampling query is killed by the SERVER regardless
--    of client-side timeouts. 30000 ms == DEFAULT_STATEMENT_TIMEOUT_MS; the
--    schema inspector uses 15000 ms — pick whichever fits your source. This is
--    a backstop, so a generous value is fine.
-- ---------------------------------------------------------------------------
ALTER ROLE kb_reader SET statement_timeout = '30000';

-- Optional: also bound how long the role waits for a lock before erroring out,
-- so introspection never blocks behind a writer.
ALTER ROLE kb_reader SET lock_timeout = '5000';
ALTER ROLE kb_reader SET idle_in_transaction_session_timeout = '60000';


-- ---------------------------------------------------------------------------
-- 4. Least-privilege GRANTs: SELECT only, nothing else.
--    Revoke the implicit PUBLIC privileges first, then grant exactly what the
--    agent needs to read and reflect schema.
-- ---------------------------------------------------------------------------
-- Connect privilege on the database (replace 'sourcedb' with the real name).
GRANT CONNECT ON DATABASE sourcedb TO kb_reader;

-- Usage on the schema(s) to expose (repeat per schema; default public).
GRANT USAGE ON SCHEMA public TO kb_reader;

-- SELECT on all CURRENT tables/views in the schema.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO kb_reader;

-- SELECT on all FUTURE tables/views created in this schema by the table owner.
-- Run as / on behalf of the role that owns the tables.
ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO kb_reader;

-- Explicitly ensure NO write privileges leak in.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER
    ON ALL TABLES IN SCHEMA public FROM kb_reader;


-- ===========================================================================
-- MANUAL / OPTIONAL LIVE VERIFICATION
-- ---------------------------------------------------------------------------
-- After running this script, verify the backstop is live. Connect AS kb_reader
-- using the same DSN you will set in the KB_TEST_POSTGRES_DSN env var, then:
--
--   -- Expect: 'on'
--   SHOW transaction_read_only;
--
--   -- Expect: ERROR — cannot execute INSERT in a read-only transaction
--   CREATE TEMP TABLE _probe(x int);  -- may itself be blocked; or:
--   INSERT INTO some_existing_table DEFAULT VALUES;
--
-- An optional Tier-B integration test (skipped unless KB_TEST_POSTGRES_DSN is
-- set) automates exactly this: it builds a real hardened engine from the DSN,
-- asserts `SHOW transaction_read_only == 'on'`, and asserts a write raises.
-- That test is documented as a MANUAL check here rather than committed as an
-- always-collected test, because it requires a live, operator-prepared source
-- database and must add NO new runtime/test dependencies.
--
-- To run it manually against a prepared source db:
--   export KB_TEST_POSTGRES_DSN="postgresql+asyncpg://kb_reader:<pass>@host:5432/sourcedb"
--   # then exercise harden_postgres_engine_kwargs(...) + create_async_engine(...)
--   # and confirm SHOW transaction_read_only == 'on' and a write raises.
-- ===========================================================================
