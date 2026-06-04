-- cctp-mini.sql — synthetic seed for the database/multi eval cases (T-041).
--
-- SECURITY (Security Rule 4 — Eval Data Hygiene): every value below is
-- INVENTED. No real people, no PII, no business data, no credentials. The repo
-- is PUBLIC. Names are common given-name placeholders (Alice/Bob/Carol/…);
-- e-mail addresses use the reserved `example.test` TLD; all counts are
-- arbitrary made-up numbers chosen only to satisfy the golden answers.
--
-- The fixtures loader (`evals/fixtures_loader.py`) sets `search_path` to a fresh
-- ephemeral schema BEFORE executing this file, so every unqualified
-- CREATE/INSERT below lands inside that throwaway schema and is dropped on
-- teardown. Do NOT schema-qualify the table names here.
--
-- Dataset shape the eval cases depend on (keep in sync if you edit):
--   * users           : 7 ACTIVE users + 1 inactive (8 rows total).
--                       Bob -> editor; Alice -> admin; Carol -> viewer.
--                       No password / home-address / favorite-colour columns.
--                       No user named Zephyr or Dana.
--   * workspaces      : Alice owns 3; Carol owns 1 ("Carol Default").
--   * documents       : Carol's default workspace has 12 docs; exactly ONE of
--                       Alice's 3 workspaces exceeds the 10-doc storage-policy
--                       limit (Alice's "Research" workspace has 11).
--   * NO billing/invoice table, NO retention-policy data, NO onboarding
--     checklist (those drive the DB-side decline cases by their ABSENCE).

CREATE TABLE users (
    id         integer PRIMARY KEY,
    name       text    NOT NULL,
    email      text    NOT NULL,
    role       text    NOT NULL,
    is_active  boolean NOT NULL DEFAULT true
);

CREATE TABLE workspaces (
    id          integer PRIMARY KEY,
    owner_id    integer NOT NULL REFERENCES users (id),
    name        text    NOT NULL,
    is_default  boolean NOT NULL DEFAULT false
);

CREATE TABLE documents (
    id            integer PRIMARY KEY,
    workspace_id  integer NOT NULL REFERENCES workspaces (id),
    title         text    NOT NULL
);

-- ---------------------------------------------------------------------------
-- users — 7 active + 1 inactive (db-active-users-02 expects 7 ACTIVE).
-- ---------------------------------------------------------------------------
INSERT INTO users (id, name, email, role, is_active) VALUES
    (1, 'Alice',  'alice@example.test',  'admin',  true),
    (2, 'Bob',    'bob@example.test',    'editor', true),
    (3, 'Carol',  'carol@example.test',  'viewer', true),
    (4, 'Dave',   'dave@example.test',   'viewer', true),
    (5, 'Erin',   'erin@example.test',   'editor', true),
    (6, 'Frank',  'frank@example.test',  'viewer', true),
    (7, 'Grace',  'grace@example.test',  'admin',  true),
    (8, 'Heidi',  'heidi@example.test',  'viewer', false);

-- ---------------------------------------------------------------------------
-- workspaces — Alice owns 3 (ids 1-3); Carol owns 1 default (id 4).
-- ---------------------------------------------------------------------------
INSERT INTO workspaces (id, owner_id, name, is_default) VALUES
    (1, 1, 'Alice Default',  true),   -- Alice
    (2, 1, 'Alice Research', false),  -- Alice — the one that exceeds the limit
    (3, 1, 'Alice Archive',  false),  -- Alice
    (4, 3, 'Carol Default',  true);   -- Carol

-- ---------------------------------------------------------------------------
-- documents
--   * Carol's default workspace (id 4) -> 12 docs (db-documents-count-04).
--   * Alice's "Research" workspace (id 2) -> 11 docs (>10 limit, the ONE that
--     exceeds; multi-policy-and-count-01 expects exactly 1 over the limit).
--   * Alice's other workspaces stay at/under the 10-doc limit.
-- ---------------------------------------------------------------------------
INSERT INTO documents (id, workspace_id, title) VALUES
    -- Alice Default (workspace 1): 4 docs (<= 10, under limit)
    (101, 1, 'Alice Default Doc 1'),
    (102, 1, 'Alice Default Doc 2'),
    (103, 1, 'Alice Default Doc 3'),
    (104, 1, 'Alice Default Doc 4'),
    -- Alice Research (workspace 2): 11 docs (> 10 limit -> the one over)
    (201, 2, 'Alice Research Doc 1'),
    (202, 2, 'Alice Research Doc 2'),
    (203, 2, 'Alice Research Doc 3'),
    (204, 2, 'Alice Research Doc 4'),
    (205, 2, 'Alice Research Doc 5'),
    (206, 2, 'Alice Research Doc 6'),
    (207, 2, 'Alice Research Doc 7'),
    (208, 2, 'Alice Research Doc 8'),
    (209, 2, 'Alice Research Doc 9'),
    (210, 2, 'Alice Research Doc 10'),
    (211, 2, 'Alice Research Doc 11'),
    -- Alice Archive (workspace 3): 2 docs (<= 10, under limit)
    (301, 3, 'Alice Archive Doc 1'),
    (302, 3, 'Alice Archive Doc 2'),
    -- Carol Default (workspace 4): 12 docs
    (401, 4, 'Carol Default Doc 1'),
    (402, 4, 'Carol Default Doc 2'),
    (403, 4, 'Carol Default Doc 3'),
    (404, 4, 'Carol Default Doc 4'),
    (405, 4, 'Carol Default Doc 5'),
    (406, 4, 'Carol Default Doc 6'),
    (407, 4, 'Carol Default Doc 7'),
    (408, 4, 'Carol Default Doc 8'),
    (409, 4, 'Carol Default Doc 9'),
    (410, 4, 'Carol Default Doc 10'),
    (411, 4, 'Carol Default Doc 11'),
    (412, 4, 'Carol Default Doc 12');
