-- Run this file manually, once, as a PostgreSQL superuser against an existing
-- omniflow database. It does not drop data, schemas, tables, or volumes.
-- Original installations use the existing PostgreSQL administrator `eval`:
-- psql -h 127.0.0.1 -p 8091 -U eval -d omniflow -v ON_ERROR_STOP=1 -f db/migrate_existing_roles.sql
-- If a particular existing volume uses a different administrator, substitute
-- that already-existing role. Changing POSTGRES_USER does not create a role in
-- an existing PostgreSQL data directory.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eval_seed') THEN
        CREATE ROLE eval_seed LOGIN PASSWORD 'eval_seed' CREATEDB;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eval_app') THEN
        CREATE ROLE eval_app LOGIN PASSWORD 'eval_app';
    END IF;
END
$$;

GRANT CONNECT ON DATABASE omniflow TO eval_seed, eval_app;
ALTER DATABASE omniflow OWNER TO eval_seed;
ALTER SCHEMA public OWNER TO eval_seed;
GRANT USAGE ON SCHEMA public TO eval_app;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO eval_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO eval_app;

-- Verify before switching DATABASE_URL: the seed role owns the fixture schema,
-- while the application role can read it but cannot write it.
SELECT current_database() AS database_name,
       has_schema_privilege('eval_app', 'public', 'USAGE') AS app_schema_usage,
       CASE WHEN to_regclass('public.tasks') IS NULL THEN NULL
            ELSE has_table_privilege('eval_app', 'public.tasks', 'SELECT') END
            AS app_can_select_tasks,
       CASE WHEN to_regclass('public.tasks') IS NULL THEN NULL
            ELSE has_table_privilege('eval_app', 'public.tasks', 'INSERT') END
            AS app_can_insert_tasks,
       has_schema_privilege('eval_seed', 'public', 'CREATE') AS seed_can_create;
