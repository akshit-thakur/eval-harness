# Eval Harness

Eval Harness is an independent evaluation layer for AI systems.

## Public proof of concept

This repository is a runnable local proof of concept demonstrating that a
split evaluation layer can be engineered and executed end to end. It is
shared as evidence of a working implementation, not as a general-purpose
evaluation platform, security-hardened stack, or validated benchmark.

The supported public demo is a fresh Docker volume followed by the explicit
fixture seed. The included adapters and data are shaped around the public
OmniFlow application; they are an example integration rather than a generic
adapter framework. The `scripts/omniflow-gpt/` directory is retained for
comparison/history and is not part of the active pipeline.

The offline pytest suite is the regression bar. Live results depend on the
configured Ollama model and supplied fixture data; the default model may
produce failing evaluation cases, which is expected for this demonstration
and should not be presented as a passing accuracy benchmark.

Docker services bind to loopback and the repository contains demo credentials
for the local fixture (`eval_app`, `eval_seed`, and the initialization/admin
values). These credentials are for local lab use only. Existing PostgreSQL
volume recovery is documented for maintainers; it is not the first-run demo
path.

Before inviting reuse, add a `LICENSE` file stating the terms under which
others may use and test this repository; no license is currently included.

Its purpose is to make AI application quality measurable in a way that matches how different parts of the system actually behave. Instead of reducing an AI workflow to a single generic accuracy score, Eval Harness separates objective checks from subjective ones and applies the appropriate evaluation method to each.

The core principle is simple:

- Use deterministic evaluation when there is a clear right or wrong answer.
- Use LLM-based judging only when outputs are inherently flexible, such as natural-language responses.

This makes failures easier to understand. A poor final response may come from an incorrect classification, incorrect data selection, or weak generation. Eval Harness is designed to distinguish between those failure types rather than treating them as one problem.

The project is intended to sit independently from the AI system being evaluated. This allows the same evaluation approach to be reused across different projects and makes regression testing possible as prompts, models, retrieval strategies, or application logic change over time.

The current version demonstrates this evaluation model against a real AI application. It covers three evaluation paths: structured decisions, objective data results, and final natural-language responses.

The longer-term goal is to make AI evaluation a repeatable engineering process rather than an ad hoc manual review step.

## Current status

The harness runs end-to-end: it loads cases and references, executes the
selected adapter, evaluates the result, and writes readable and JSONL run
artifacts. A passing or failing result should be interpreted in the context of
the supplied data. Evaluation quality depends on the completeness and meaning
of retrieved records, the reference answers, the adapter prompts, and the
configured model. In particular, an empty retrieval result does not prove
that no matching records exist; it may mean that the available evidence is
insufficient.

## Evaluation pipeline

`core.loader` pairs questions and references by ID, `core.runner` calls the
selected adapter, and `core.evaluator` scores its output. Each suite runs
independently; `all` runs all three suites rather than chaining their outputs.

| Suite | Active adapter | Evaluation |
| --- | --- | --- |
| `intent` | `scripts.intent_test` | Exact equality of the returned intent/actions object and reference |
| `sql` | `scripts.sql_test` | Execute generated and reference SQL against PostgreSQL and compare integer counts |
| `llm_judge` | `scripts.llm_judge_test` | Generate an answer, then judge it against `ideal_output`, the question, and supplied records |

Questions and references under `data/` are authoritative user-generated input.
The harness does not rewrite them. SQL result equality means matching on the
current database; it does not prove that two queries are semantically equivalent.
LLM judging accepts paraphrases and checks grounding, but its quality depends on
the configured model.

## Setup with Docker

Run commands from the repository root. Install Docker with Compose support.
The stack uses PostgreSQL and Ollama, with `qwen3:1.7b` as the default model.
Local ports bind to loopback: PostgreSQL on `8091`, Ollama on `8092`.
The harness is a CLI container, not an HTTP service.

Normal startup does not seed or reset the database. Fixture replacement is an
explicit operation through the `seed` profile.

### Fresh installation

Start infrastructure, explicitly replace the disposable fixture, then start
the harness:

```bash
docker compose up -d db ollama
docker compose --profile seed run --rm db-seed
docker compose exec ollama ollama pull qwen3:1.7b
docker compose up --build -d harness
```

`db-seed` drops and recreates `public`; use it only when replacing the fixture
is intentional.

### Existing PostgreSQL volumes

The init scripts run only when PostgreSQL creates a new data directory. For an
existing volume, do not invoke `db-seed`. Start only the non-destructive
infrastructure services, then run the explicit role migration using the
existing PostgreSQL administrator (`eval` in the original setup):

```bash
docker compose stop harness
docker compose up -d db ollama
psql -h 127.0.0.1 -p 8091 -U eval -d omniflow -v ON_ERROR_STOP=1 -f db/migrate_existing_roles.sql
```

The migration command requires a local `psql` client and the existing
administrator's password. Review its verification row: application schema
usage and seed schema CREATE access should be true; when the legacy `tasks`
table exists, task SELECT should be true and task INSERT false. A NULL task
privilege result means the volume has no `tasks` table and still needs a
separate schema/fixture migration; role migration does not create tables.

Then make the model available and start the harness:

```bash
docker compose exec ollama ollama pull qwen3:1.7b
docker compose up --build -d harness
```

The role migration preserves existing tables and data; it does not update the
existing table schema. Changing `POSTGRES_USER` does not create an administrator
inside an existing volume. Use the role that already administers it, and do not
run `db-seed` when existing data must be preserved.

The migration is also available as an explicit Compose one-shot. Set the
credentials for the administrator that actually exists in the volume:

```bash
PGADMIN_USER=eval PGADMIN_PASSWORD=eval \
  docker compose --profile migrate run --rm db-migrate
```

Starting the harness performs a non-destructive preflight for the `eval_app`
login and every table/column advertised by `core/schema_contract.py`. It stops
with a migration or schema message if the existing volume is behind the code.

## Run evaluations

```bash
docker compose exec harness python -m core.loader --script intent
docker compose exec harness python -m core.loader --script sql
docker compose exec harness python -m core.loader --script llm_judge
docker compose exec harness python -m core.loader --script all
docker compose exec harness python -m core.loader --script sql --case-id 8
```

Omitting `--script` runs all suites. `--case-id` requires a single suite; IDs
whose string representations collide produce an ambiguity error. The harness
checks model availability before running each built-in suite. Rebuild the
harness after changing core code or dependencies, which are copied into its
image; `data/`, `scripts/`, and `logs/` are mounted from the host.

### Run on the host

Use Python 3.12 or newer and a local Ollama CLI. With the Docker infrastructure
and database already prepared:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
export DATABASE_URL=postgresql://eval_app:eval_app@127.0.0.1:8091/omniflow
export OLLAMA_HOST=http://127.0.0.1:8092
export OLLAMA_REASONER_MODEL=qwen3:1.7b
python -m core.loader --script all
```

## Results and exit codes

Runs write uniquely named `.log` and `.jsonl` files to `logs/` by default. The
readable log includes inputs, references, actual outputs, and error details.
JSONL contains suite manifests and case results, including error stages
(`validate`, `run`, or `evaluate`). Manifests record configured inference
settings and question, reference, and seed-file hashes. CLI totals are printed
at completion. Logs can contain the full supplied record contents.

| Exit code | Meaning |
| --- | --- |
| `0` | Every selected case passed |
| `1` | Case failures, case execution errors, or no results |
| `2` | Invalid CLI arguments or a handled suite-level configuration/execution error |

Per-case errors preserve completed results and allow later cases to continue.
Reference-query failures are evaluation errors, not incorrect-answer verdicts.
Handled suite-level errors allow other selected suites to continue.

## Configuration

| Environment variable | Default | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | Required for SQL evaluation | PostgreSQL connection string; Compose supplies `eval_app` credentials |
| `OLLAMA_HOST` | `http://ollama:11434` in the image | Ollama service address; use port `8092` from the host |
| `OLLAMA_REASONER_MODEL` | `qwen3:1.7b` | Default generation and judge model |
| `OLLAMA_TIMEOUT_SECONDS` | `180` | Timeout for each generation or judge call; no automatic retries |
| `EVAL_CONNECT_TIMEOUT_SECONDS` | `5` | Database connection timeout |
| `EVAL_STATEMENT_TIMEOUT_MS` | `5000` | Database statement timeout |
| `EVAL_LOCK_TIMEOUT_MS` | `1000` | Database lock timeout |
| `EVAL_LOG_DIR` | Repository `logs/` | Output directory |
| `RESET_TIMEOUT_SECONDS` | `60` | Database readiness deadline for explicit fixture reset |

Compose forwards `OLLAMA_REASONER_MODEL` from the host when creating the
harness container; pull that model into Ollama before evaluating. Other runtime
overrides can be passed explicitly, for example:

```bash
docker compose exec -e OLLAMA_TIMEOUT_SECONDS=300 harness python -m core.loader --script llm_judge
```

Generated SQL is checked with a PostgreSQL-aware AST parser for statement type,
writable operations (including `SELECT INTO`), allowed relations, and CTE scope.
Database connections independently enable read-only transactions and timeouts.
The application role is separate from the fixture-seeding role.

## Tests

Install the runtime dependencies and pytest in your local environment:

```bash
python -m pip install -r requirements.txt pytest
python -m pytest -q
```

The offline suite covers SQL restrictions, count and verdict contracts, loader
identity handling, error continuation, and judge wiring. Synthetic test data
stays outside `data/`. Judge responses and database interactions are mocked;
passing these tests does not establish live-model judging accuracy or verify
database permissions and migration behavior against a running PostgreSQL server.

## Repository layout

| Path | Purpose |
| --- | --- |
| `core/` | CLI, loading, execution, evaluation, SQL checks, database access, and logs |
| `scripts/` | Active project-specific adapters |
| `scripts/omniflow-gpt/` | Alternate adapters, not selected by the current runner |
| `data/` | User-authored questions and reference outputs |
| `db/` | Fixture schema/data, explicit reset, and role provisioning/migration |
| `tests/` | Offline harness regression tests |
| `logs/` | Generated run artifacts |
