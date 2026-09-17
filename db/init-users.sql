-- Mounted into the stock Postgres image's init directory.
CREATE ROLE eval_seed LOGIN PASSWORD 'eval_seed' CREATEDB;
CREATE ROLE eval_app LOGIN PASSWORD 'eval_app';
GRANT CONNECT ON DATABASE omniflow TO eval_seed, eval_app;
ALTER DATABASE omniflow OWNER TO eval_seed;
ALTER SCHEMA public OWNER TO eval_seed;
