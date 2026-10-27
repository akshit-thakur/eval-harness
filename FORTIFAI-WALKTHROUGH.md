# Fortifai Technical Evidence Walkthrough

Repository reviewed: `eval-harness`. Review date: 2026-10-20.

This is an implementation evidence report for interview preparation, not a claim of personal authorship, production deployment, or measured business impact. **Fact** denotes behavior supported by inspected code/configuration/fixtures; **inference** denotes an interpretation of that behavior; **unknown** denotes something not established by this checkout. Proposed improvements are explicitly identified.

Review covered all Python source in `core/` and `scripts/`, `tests/test_harness.py`, all six JSON datasets, database scripts, Docker configuration, dependency manifests, README, and supporting design/walkthrough material. Source and fixtures take precedence over narrative documentation. No model inference, database reset, Docker build, dependency installation, or expensive pipeline was performed. The available `python3` environment has no `pytest`, `psycopg`, or `sqlglot`; therefore this review does not claim a passing test run. No saved evaluation logs or measured benchmark artifacts were present in the inspected checkout.

## 1. Project Overview

The project evaluates three AI behaviors associated with an OmniFlow personal dashboard: request classification, PostgreSQL count-query generation, and answers grounded in supplied records. Its engineering problem is separating deterministic correctness checks from flexible natural-language judgment while retaining actionable failure evidence. This motivation is documented in `README.md`; implementation is in `core/runner.py::SCRIPTS`, `run_script`, and `core/evaluator.py::evaluate`.

The implementation is a synchronous Python CLI proof of concept with source-level regression tests and a local Docker Compose workflow. It contains substantive executable logic, rather than only an architectural proposal. Actual successful deployment or live-model accuracy is **unknown** from the available artifacts. README also describes it as a local proof of concept, not a security-hardened platform or validated benchmark.

| Implemented capability | Evidence and boundary |
| --- | --- |
| Load paired question/reference datasets with identity checks | `core/loader.py::load_cases`; no dataset labeling/review application |
| Evaluate intent objects exactly | `scripts/intent_test.py::run`, `core/evaluator.py::_exact`; classifications do not execute actions |
| Generate, restrict, execute, and compare SQL counts | `scripts/sql_test.py::run`, `core/sql_guard.py::validate_read_query`, `core/evaluator.py::_query_result`; only scalar count tasks |
| Generate grounded answers and request a model verdict | `scripts/llm_judge_test.py::run`, `judge`; supplied records, not live retrieval |
| Continue after individual case errors and save diagnostics | `core/runner.py::run_script`, `core/run_log.py::RunLog`; no resume/retry system |
| Provision a disposable database fixture and local runtime | `docker-compose.yml`, `db/reset_and_seed.sh`; deployment configuration, not deployment evidence |

Not implemented: model training/fine-tuning, traditional statistical ML, anomaly detection, time-series modeling, embeddings/vector search, ranking, autonomous planning/tool selection, dashboard writes, production API integration, distributed workers, automatic baseline comparison, or CI workflows. These absences are bounded to the inspected repository. Larger-scale operation and additional integrations discussed in `WALKTHROUGH.md` and `SIMPLIFIED.md` are proposals.

Two documentation boundaries matter: README mentions `scripts/omniflow-gpt/`, but that directory is absent in this checkout. The SQL adapter's comment references external `api/app/mutations.py`; that application source is not present, so schema parity with the external application is unverified.

## 2. Architecture and Data Flow

### Components

| Component | Responsibility |
| --- | --- |
| `core/__main__.py`, `core/loader.py::main` | CLI selection, SQL preflight, suite orchestration, aggregate totals and exit status |
| `core/loader.py::load_cases`, `validate_case_payload` | Join question/reference JSON by typed ID and check adapter-facing shapes |
| `core/runner.py::SCRIPTS`, `run_script` | Hardcoded file/module/mode registry, dynamic imports, model preflight, serial execution, error isolation |
| `scripts/*_test.py::run` | Actual inference adapters; despite filenames, these are application adapters, not pytest tests |
| `core/evaluator.py::evaluate` | Exact, count-result, or model-judge evaluation; produces `EvalResult(passed, reason)` |
| `core/ollama.py::run_model` | Shared subprocess invocation of the external Ollama CLI |
| `core/schema_contract.py::TABLE_FIELDS`, `prompt_schema` | Ten-table column-name contract shared by prompts and database checks |
| `core/sql_guard.py::validate_read_query` | Custom SQL policy built on SQLGlot's PostgreSQL parsing and scope analysis |
| `core/db.py` | Psycopg connections, timeouts, schema inspection, queries, scalar validation |
| `core/run_log.py::RunLog` | Console output, readable logs, JSONL manifests/results |

### Execution path

```text
CLI selection
  -> SQL database preflight, when selecting SQL
  -> paired JSON loading and optional case-ID filtering
  -> adapter import / callable checks / model availability
  -> suite manifest
  -> for each case: validate -> adapter.run(input) -> evaluate(reference, actual)
  -> PASS / FAIL / ERROR records
  -> aggregate counters, log closure, process exit status
```

`--script all` runs the three suites independently in registry order. It does **not** feed classification into SQL, or SQL output into answer generation. SQL cases already specify `intent=read` and permitted tables. Answer cases already contain record lists. IDs belong to each suite; identical IDs across suites do not connect cases. Evidence: `core/runner.py::run_script`, `SCRIPTS`, and `data/*_questions.json` / `data/intent_question.json`.

The generator receives case input, not the reference answer. For the natural-language suite, a separate judge call receives the input, reference, and generated answer through the runner's lambda wrapper. This is evaluation separation, not a guarantee against all reference contamination in a broader workflow.

Storage consists of JSON fixture files, PostgreSQL fixture tables, local run files, and Docker named volumes for PostgreSQL/Ollama. There is no vector store or results database. `core/db.py::fetch` creates a new connection per query and materializes all rows. Generated and reference queries use separate connections/transactions, so concurrent database changes could affect comparison; there is no shared snapshot.

Runtime uses Python 3.12 in `Dockerfile`, `psycopg[binary]==3.2.10` and `sqlglot==26.33.0` in `requirements.txt`, PostgreSQL 16 Alpine and an Ollama service in Compose. SQLGlot supplies parser/scope machinery; Ollama supplies inference/model serving; PostgreSQL supplies SQL execution and transactional semantics. The project's custom contribution is their orchestration, validation policy, adapter prompts, evaluator contracts, and diagnostics—not implementation of those third-party capabilities.

## 3. Hands-on AI/ML Implementation

### Shared inference configuration and preprocessing

`core/config.py::model_name` defaults to `qwen3:1.7b`, overridden by `OLLAMA_REASONER_MODEL`. `inference_timeout` defaults to 180 seconds via `OLLAMA_TIMEOUT_SECONDS`. `core/ollama.py::run_model` runs an argument-list subprocess equivalent to `ollama run <model> <prompt>`, optionally appending `--format <JSON schema>`, with captured stdout, checked exit status, and timeout. It does not use a shell, load weights in Python, or implement decoding. `ensure_model_available` runs `ollama show` with a 10-second timeout; it does not download a model.

The model is an externally supplied pretrained model used for **inference only**. No training dataset construction, gradient updates, optimizer, loss function, checkpoint saving, fine-tuning, or training experiment exists. No temperature, top-p, token budget, random seed, or model-selection search is set by the project. No performance or quality rationale for choosing this model over alternatives is established by the code. Runtime model defaults are not measured optimal hyperparameters.

`scripts/model_output.py::final_json` removes ANSI escapes and completed leading reasoning wrappers, optionally unwraps a whole fenced response, then decodes the final JSON. It rejects unfinished thinking traces and extra JSON objects, while preserving reasoning-like tags inside JSON strings/SQL literals. This is deterministic response parsing, not learned preprocessing or training.

### A. Request intent classification

- **Problem:** distinguish requests to read dashboard records, mutate them, or converse.
- **Technique:** prompt-based classification using the configured model and an intent enum JSON schema. The prompt explicitly considers only the current user message and describes mutation verbs versus reads/general conversation.
- **Input preparation:** require a nonblank query string; concatenate it into the instruction prompt. No embeddings, feature extraction, classifier training, or retrieved context.
- **Selection/output:** validate the parsed object and membership in `read`, `write`, `chat`; return `{intent, actions: []}`. Actions are always empty, not model-generated execution plans.
- **Evaluation:** exact Python equality against the entire reference object. No probability, confidence threshold, calibration, or per-class metric.
- **Evidence:** `scripts/intent_test.py::_INTENT_SCHEMA`, `run`; `core/evaluator.py::_exact`; `data/intent_question.json`, `data/intent_ground_truth.json`.

The schema requests no additional properties, but local validation does not reject every extra model field; it selects the intent and constructs a normalized output. Do not describe this adapter as full JSON Schema validation or a write authorization system.

### B. Natural-language-to-SQL count generation

- **Problem:** answer dashboard count questions using structured data.
- **Technique:** schema-conditioned LLM generation followed by deterministic SQL checks, database execution, and strict scalar validation.
- **Input preparation:** require read intent and a nonempty list of known tables. `prompt_schema` supplies only those tables' advertised fields. The prompt specifies `COUNT(*)`, PostgreSQL booleans, `medication_plans.active`, and `media_items.status = 'completed'`; it excludes invented columns and vector/hybrid retrieval.
- **Output:** decode `{sql: string}`, validate it with `validate_read_query(sql, set(tables))`, normalize its final semicolon, execute it, and return `{sql, count}`.
- **Evaluation:** execute trusted reference SQL separately and compare nonnegative integer scalar counts. The evaluator does not compare SQL strings or row identities.
- **Evidence:** `scripts/sql_test.py::_SQL_SCHEMA`, `run`; `core/schema_contract.py`; `core/sql_guard.py`; `core/db.py::scalar_count`; `core/evaluator.py::_query_result`.

The prompt requests `COUNT(*)`, but the guard does not enforce a COUNT AST. A permitted `SELECT` returning one nonnegative integer can satisfy the output contract, including a constant. SQL column names are not independently checked against the prompt schema. Extra fields in a model's parsed JSON are not comprehensively rejected locally.

### C. Grounded natural-language answer generation

- **Problem:** answer from supplied records while avoiding invented facts and instructions embedded in record content.
- **Technique:** context-conditioned generation, using already supplied structured records. This demonstrates grounded generation, not an implemented retrieval-augmented search pipeline.
- **Preparation:** require query, record list, `source_table`, `source_id`, and dictionary `metadata`. `results` takes precedence over fallback `context`. Serialize records compactly into `{source_table, source_id, fields: metadata, search_text: text or empty}`; field names are made explicit in the prompt.
- **Instructions:** answer only the question, use correct field labels, state insufficient evidence, treat records as untrusted, and do not claim mutations.
- **Output:** strip common reasoning/ANSI wrappers and return `{answer, context: original_records}`. No deterministic factuality validator runs on the answer.
- **Configuration:** an input-level `model` may override answer generation. Availability preflight and manifests still use the global default model, so an override is not fully represented/validated there.
- **Evidence:** `scripts/llm_judge_test.py::run`, `_strip_thinking`, `_run_model_traced`; `core/runner.py::run_script`.

Unlike `final_json`, `_strip_thinking` removes tagged reasoning blocks throughout the response. This can remove literal tag-containing answer content; no test establishes preservation for this prose path.

### D. LLM-as-judge

- **Problem:** assess flexible wording without requiring exact reference text.
- **Technique:** a second inference call sees the question, ideal answer, supplied records, and generated answer. The prompt asks it to reject unsupported facts, irrelevant answers, embedded instructions treated as commands, and unsupported mutation claims; it permits paraphrases, quoted record text, and negated mutation claims.
- **Contract:** parse JSON with `strict=False` to tolerate control characters inside strings, then require exactly `passed: bool` and `reason: str`. Invalid verdicts raise errors rather than silently coercing strings such as `"false"`.
- **Decision rule:** one boolean verdict; no numeric similarity score, pass threshold, ensemble, disagreement handling, or human-calibrated rubric scores.
- **Model:** globally configured model, normally the same model used for generation. Separate calls do not make the judge statistically independent. Correlated errors/bias are a reasonable risk inference, not a measured finding.
- **Evidence:** `scripts/llm_judge_test.py::_JUDGE_SCHEMA`, `judge`; `core/evaluator.py::_from_judge`.

### Training, tuning, and optimization boundary

All four behaviors above are inference applications. Prompt instructions, output schemas, timeouts, and SQL policy are engineering configuration. There is no automated hyperparameter tuning or prompt-search loop. Modular evaluation and schema-limited prompts are pipeline design choices, not evidence of measured pipeline optimization. No custom deep-learning architecture, statistical anomaly detector, forecasting model, or time-series method is implemented. Inventory `quantity < min_quantity` is a fixed SQL business predicate, not learned anomaly detection.

## 4. Evaluation and Validation

### Fixtures and reference quality

| Suite | Cases and coverage | Reference mechanism |
| --- | --- | --- |
| Intent | 10: four read, three write, three chat labels | `data/intent_ground_truth.json`: intent plus empty actions |
| SQL | 8: tasks, priority, medications, active plans, exercises, recipes, inventory minimum, completed media | `data/sql_ground_truth.json`: executable reference SQL |
| Grounded answer | 8: empty retrieval, title, incomplete tasks, missing dosage, summary, malicious record instruction, recipe count, absent due date | `data/llm_ground_truth.json`: ideal answer text |

These are small regression fixtures, not a statistically representative benchmark or training/test split. Their provenance beyond repository documentation describing user-authored data is unknown. No label agreement or independent adjudication is recorded.

The seed defines ten tables with 21 inserted rows: five tasks; two each in medications, medication plans, plan times, exercise catalog, recipes, ingredients, inventory, and media; zero medication logs. From inspection of `db/seed_test_data.sql` and the reference SQL, expected counts are **4, 1, 2, 1, 2, 2, 1, 1**. These are statically derived fixture expectations, not observed database outputs.

**Reference ambiguity:** SQL case 1 asks “How many tasks do I have?” but its reference filters incomplete tasks. The seed contains five total tasks, four incomplete. A model returning five can fail despite a defensible interpretation of the question. `load_cases` intentionally does not reconcile semantic inconsistencies. This limits what a failure means and is a concrete topic for dataset review.

**Count collisions:** `tests/test_harness.py::test_sql_result_matching_does_not_claim_semantic_equivalence` deliberately demonstrates that equal counts pass even with different SQL. Passing does not prove semantic equivalence or correct selected records. The tiny fixture and repeated counts increase the opportunity for undetected wrong queries; that risk is inferred, not measured.

### Existing regression tests

`tests/test_harness.py` contains 24 test functions. Coverage includes:

- SQL writable statements/CTEs, SELECT INTO, schema restrictions, nested relations, qualified joins, CTE shadowing, identifier case, and semicolons/keywords in string literals.
- Strict count and judge types; explicit acknowledgement of SQL count-equivalence limitations.
- Judge input wiring and malformed verdict rejection. The quoted-content/mutation/negation test supplies predetermined mocked model verdicts; it does **not** show that the live judge understands these distinctions.
- Typed IDs and invalid ID shapes; final-JSON extraction and preservation of SQL literal text.
- Textual checks that seed columns match the advertised schema and that destructive seeding is outside normal startup dependencies.
- Continued execution after evaluation errors and later-case validation errors, with JSONL records.

Named evidence includes `test_sql_guard_parses_qualified_joins_nested_queries_and_cte_scope`, `test_sql_guard_applies_postgres_identifier_case_to_cte_scope`, `test_grounded_judge_requires_strict_model_verdict`, `test_final_json_preserves_reasoning_tags_inside_sql_literals`, and `test_runner_records_evaluator_errors_and_continues`.

No test execution result is asserted in this report. Dependencies were unavailable and were not installed. Tests mock model/database interactions; no checked-in live PostgreSQL integration, deployment smoke-test artifact, or measured judge-accuracy study was found. Several implemented branches lack direct tests, including real subprocess timeouts, actual role restrictions/migration rollback, full CLI status handling, and live schema inspection.

### Metrics and diagnostics actually implemented

`core/runner.py::run_script` counts `total`, `passed`, `failed`, `errors`. `core/loader.py::main` aggregates them and adds `no_results` when aggregate total is zero. The implementation does not calculate accuracy percentages, precision, recall, F1, confusion matrices, uncertainty intervals, ranking metrics, or baseline deltas. A handled suite-level failure contributes one error with zero cases, so aggregate errors are not necessarily a subset of aggregate total.

`_run_model_traced` optionally prints elapsed seconds and prompt/response character counts when `EVAL_TRACE` is enabled. These are diagnostics for the answer/judge calls, not stored latency distributions, token counts, costs, or throughput benchmarks.

Manual review is supported by readable logs and `--script <suite> --case-id <id>` reruns. Full inputs, references, actual outputs, reasons, generated SQL when available, and exception tracebacks support investigation. There is no annotation interface, adjudication queue, automatic cross-run comparison, or dedicated human approval workflow.

## 5. Reliability and Failure Handling

### Validation and trust boundaries

`core/loader.py::_read_list`, `_index_by_id`, and `load_cases` reject missing/blank/malformed files, non-array roots, duplicate IDs, absent/unused reference IDs, and top-level prefilled `actual` values. `_id_key` preserves JSON scalar types, so numeric `1` and string `"1"` are distinct. CLI filtering uses string representations and rejects ambiguous matches. Complete file validation precedes filtering, so an unrelated malformed row can block a single-case rerun.

`validate_case_payload` checks suite-specific shapes; it does not validate reference meaning, reject all extra fields, or deeply type-check record metadata/source identifiers. SQL adapter membership checks further restrict tables. `validate_database_contract` checks visible table/column names against `TABLE_FIELDS`, not types, constraints, fixture rows, ownership, or absence of write privileges. Its `fixture-v1` schema version is a code constant, not database migration state.

### SQL protections and their limits

`core/sql_guard.py::validate_read_query` parses PostgreSQL with SQLGlot, requires one `exp.Select`, rejects SELECT INTO and named writable AST nodes, and traverses scopes to inspect physical relations. CTE and derived-table aliases are distinguished from physical sources. It normalizes unquoted identifiers for PostgreSQL case rules while retaining quoted case, rejects catalog qualification, and restricts relations to the supplied allowlist. Top-level set operations such as UNION are outside its accepted root contract.

Independent connection settings in `core/db.py::connect` enable read-only transactions and defaults of 5 seconds for connect timeout, 5,000 ms statement timeout, and 1,000 ms lock timeout. Compose separates `eval_app` from fixture-owner `eval_seed`. These are layered safeguards, **not proof of a complete SQL sandbox**: there is no function allowlist, column policy, query-cost estimator, search-path pinning, or mandatory physical-table reference. Reference SQL bypasses the generated-query guard and is treated as trusted fixture content, though it uses the same database connection settings.

`fetch` retrieves all rows before `scalar_count` checks exactly one row/column and a nonnegative Python integer, excluding booleans. A model can therefore produce a large result before it is rejected. `execute` exists but uses the same read-only connection defaults and is not an active dashboard mutation path.

### Errors, recovery, transactions, and idempotency

`run_script` catches ordinary exceptions separately at validation, adapter execution, and evaluation, records stages `validate`, `run`, `evaluate`, and continues. An incorrect comparable result is FAIL; inability to evaluate is ERROR. Reference database exceptions become `EvaluationError` in `_query_result`. If an adapter fails before returning, `actual` remains null; generated SQL/raw model output is not guaranteed to survive every failure.

`main` catches selected suite-level exception classes and can continue later suites. It does not catch all import/filesystem/database errors. Logs are closed in `finally` once the execution block begins; log creation failures occur earlier. Exit statuses are 0 for successful selected cases, 1 for case failures/errors or empty suites, and 2 for handled suite/configuration errors or invalid CLI arguments.

There are no inference retries, repair loops, checkpoints, resume semantics, or run deduplication. `inference_config` explicitly records retries as zero. Read queries avoid application mutations, but repeated evaluations can differ due to model output/database state and create new log files.

`db/reset_and_seed.sh` polls readiness with a default 60-second deadline, then uses `psql` with `ON_ERROR_STOP=1` and a single transaction to drop/recreate `public`, apply DDL/data, grant access, and commit. Failure is intended to prevent a partially committed replacement through PostgreSQL rollback semantics; this was not integration-tested during review. It is destructive and isolated behind the explicit Compose `seed` profile, not a normal harness dependency.

`db/migrate_existing_roles.sql` conditionally creates missing roles and grants existing-table access without dropping data. It does not migrate missing columns, reset existing role passwords, revoke pre-existing write privileges, or configure future-table default grants. It is not wrapped in an explicit all-or-nothing migration transaction. Runtime read-only role enforcement on an existing installation must not be assumed from the presence of this script alone.

### Guardrails, logging, and auditability

Answer/judge prompts label record content untrusted; case 6 exercises an embedded “delete everything” instruction. This is prompt-based guidance and an evaluation fixture, not measured injection resistance. No human approval gate is needed by the implemented read-only evaluation flow, and none is implemented. Intent `write` remains only a label.

`RunLog` creates UTC timestamp/UUID-named files exclusively, flushes readable output and JSONL records, and retains records in an in-memory list. `run_script` writes suite manifests containing model/configuration, judge presence, schema version, and SHA-256 of question, reference, and seed files. This supports tracing fixture changes.

Limits: no code commit, prompt hash, model digest, dependency/environment snapshot, or live database-state fingerprint; hashing seed text does not prove it was applied. Manifests are written after preflight, so preflight failures lack them. Case JSONL is less complete than readable logs; handled suite errors are logged textually rather than as structured case records. There is no tamper-evident storage, fsync guarantee, atomicity across the two files, retention/redaction, monitoring service, alerting, or distributed tracing. Logs may contain full supplied records. These are local diagnostic artifacts, not a compliance audit system.

## 6. Engineering Decisions and Tradeoffs

| Demonstrated decision | Rationale status and consequence |
| --- | --- |
| Deterministic checks for structured outputs; judge for prose | Explicit README principle. Exact/count checks are easy to interpret; the judge permits paraphrases but introduces probabilistic evaluation. |
| Independent adapters rather than full application calls | README describes an independent evaluation layer. Inference: this isolates behaviors and reduces application coupling; it does not test routing, retrieval, production prompts, or cumulative failures. |
| Count equality rather than SQL string equality | Code accepts different query text yielding equal counts. Inference: this tolerates alternative formulations but loses row identity and semantic guarantees. No historical comparison experiment is documented. |
| Shared schema contract | `TABLE_FIELDS` feeds prompts and preflight; the seed consistency test checks names. Inference: reduces duplicated field-name drift, but does not validate types or external application parity. |
| Parser/scope analysis plus database restrictions | SQL guard docstring explicitly retains independent DB protections. Better scoped than keyword matching; depends on SQLGlot behavior and remains a bounded policy. |
| Structured output plus local parsing | Intent/SQL/judge schemas constrain requested output; local checks detect selected malformed responses. Judge validation is stricter than intent/SQL property validation. |
| One generator and one judge model by default | Configuration fact, not a documented optimal model selection. Inference: simple local setup, with correlated-error risk and no independent judge calibration. |
| Serial execution, subprocess calls, new DB connections | Implementation fact. Inference: simple isolation/lifecycle handling at the expense of parallel throughput and repeated setup overhead. No measured tradeoff is supplied. |
| Explicit destructive seed, separate migration | Compose profiles and DB scripts make reset opt-in. Existing schema upgrades still need separate implementation. |
| Fixture hashes and incremental local logs | Supports diagnosis and input identification; does not ensure deterministic inference or durable enterprise auditability. |

There is no evidence of accuracy gains, cost savings, latency reductions, or experimentally selected algorithms. Those claims would require before/after measurements not present here.

## 7. Scale, Performance, and Deployment

Compose defines PostgreSQL and Ollama with loopback host ports 8091 and 8092, plus a Python harness container. The harness sleeps until CLI commands are invoked; it is not an HTTP service. PostgreSQL has a readiness check; Ollama is only required to have started at Compose level, with model availability checked later. Database/model volumes persist, while `data`, `scripts`, and `logs` are host-mounted. Core code is copied into the image and requires rebuild for container updates. Evidence: `Dockerfile`, `docker-compose.yml`, `core/ollama.py::ensure_model_available`.

The configuration contains local demo credentials. Runtime Python packages are version-pinned, but base images, `ollama:latest`, the downloaded installer, and model tag are not immutable digest-pinned. Pytest is not listed in runtime requirements. There is no Kubernetes/cloud infrastructure, CI/CD definition, autoscaling, production authentication layer, or demonstrated hosted deployment in this checkout.

Demonstrated workload is the 26-case fixture and 21-row seed, not enterprise data. A fully successful `all` traversal would make 34 inference calls (10 intent + 8 SQL + 8 answer + 8 judge), three model-availability subprocess calls, and 17 database connections (one schema preflight plus 16 generated/reference queries). These are code-derived operation counts, not measured throughput; failures reduce them. Fixture SQL cases are single-table counts, while guard tests cover more complex joins/subqueries. Medication-log/time fields do not establish time-series analytics.

Known scale limits: sequential cases; one subprocess per inference; no DB pool; entire datasets loaded into memory; all query rows fetched; no prompt-context/token budget; all run records also retained in `RunLog.summary`; synchronous local logging; no retries, queue, partitioning, checkpointing, or durable centralized result store. No measured wall-clock run time, p95 latency, resource profile, load test, or concurrency limit is available.

**Proposed enterprise work, not current capability:** first establish representative datasets, reviewed references, calibrated judges, and meaningful quality/latency measurements. Then add bounded worker concurrency, provider-aware limits, database pooling/snapshot control, transient-error retry policies, resumable case identities, durable result storage, CI regression comparisons, model/environment provenance, and production secret/log-data controls. Actual scale requirements should drive design; the repository does not demonstrate a target such as 100,000 cases merely because existing walkthroughs discuss it hypothetically.

## 8. Fortifai Relevance

This mapping uses the requirements supplied for this report; it does not assert independently verified details about Fortifai's internal architecture.

| Requirement | Classification | Evidence and qualification |
| --- | --- | --- |
| Applied ML/deep learning | **Partially demonstrated** | Applied pretrained LLM inference and evaluation in all three adapters. No custom training, fine-tuning, supervised model development, or deep-learning architecture implementation. |
| Statistical or anomaly-detection techniques | **Not demonstrated** | No anomaly model, statistical test, forecasting, or time-series pipeline. Inventory minimum comparison is a business rule. |
| LLM and agentic systems | **Partially demonstrated** | LLM generation, structured responses, grounding prompts, and judging directly demonstrated. No autonomous agent loop, planner, tool selection, memory, or action execution. |
| Structured-data retrieval and reasoning | **Directly demonstrated** | Schema-conditioned SQL generation, restricted PostgreSQL execution, count contracts, and supplied-record reasoning. Scope is small count fixtures and prerecorded context; no search/ranking/vector retrieval. |
| Model evaluation and regression testing | **Directly demonstrated** | Exact, query-result, and model-judge evaluators, fixtures, 24 offline test functions, failure artifacts. Live-model quality, representative benchmark validity, and automated historical regression comparison remain unverified/absent. |
| Production Python engineering | **Partially demonstrated** | Modular CLI, typed interfaces/dataclass, subprocess and DB timeouts, resource context managers, Docker packaging, exception isolation. No production operational history, service SLOs, distributed execution, or CI deployment evidence. |
| Reliability, observability, and auditability | **Partially demonstrated** | SQL restrictions, read-only settings, role separation, stage errors, manifests/hashes, readable/JSONL logs. Live safeguard verification, monitoring, durable audit controls, recovery/resume, and complete reproducibility are absent. |

The strongest defensible positioning is hands-on LLM evaluation and defensive structured-data execution. Presenting this as an anomaly-detection or trained-ML project would exceed the evidence.

## 9. Technical Interview Deep Dive

1. **Does `all` evaluate the complete assistant end to end?**
   No. `core/runner.py::SCRIPTS` and `run_script` run independent fixtures. SQL receives preassigned tables/read intent; answer generation receives records. This isolates component behavior but misses routing/retrieval and cascading application errors. A true end-to-end adapter would be additional work.

2. **Can a wrong SQL query pass, and how would you improve evaluation?**
   Yes. `_query_result` compares only counts, and `test_sql_result_matching_does_not_claim_semantic_equivalence` explicitly documents a collision. The guard also does not require COUNT syntax. Proposed improvements include diverse database fixtures, known counterexamples, row-set checks for richer tasks, and reviewed question/reference semantics. Case 1's incomplete-task filter is an existing reference ambiguity.

3. **Why is parsing preferable to banning SQL keywords, and is it sufficient?**
   `validate_read_query` uses PostgreSQL AST and scope traversal to distinguish strings, CTE aliases, nested physical tables, and writable nodes. Keyword filtering would misread literals and miss scope. It is insufficient alone: functions, columns, costs, and search paths are not comprehensively controlled, so read-only DB settings, privileges, and timeouts remain separate safeguards.

4. **What does the LLM judge actually measure, and how do you know it is right?**
   `scripts/llm_judge_test.py::judge` returns a single prompted pass/fail judgment against question/reference/records. Strict JSON checks establish verdict shape, not correctness. Mocked tests establish wiring; there is no human calibration, inter-judge agreement, or repeated-run accuracy study. The same default model generates and judges answers.

5. **How do you separate bad answers from infrastructure failures?**
   `run_script` distinguishes FAIL from ERROR and tags errors by validation/run/evaluation stage. Reference-query exceptions become `EvaluationError`, rather than incorrect-answer failures. Cases continue, and actual output is preserved when evaluation fails after generation. Failures inside an adapter may leave no actual payload; some suite-level exception classes can still terminate the process.

6. **Are runs reproducible, and can model changes be attributed confidently?**
   Manifests record fixture hashes and configuration (`run_script`), but not code/prompt/model digests or live DB state. Decoding settings/seeds are uncontrolled, and queries lack a shared snapshot. Hashes improve traceability without proving repeatability or causal attribution. Input-level answer model overrides are another manifest gap.

7. **What did you train or tune, and why this model?**
   Nothing in this repository trains or fine-tunes a model. `core/ollama.py::run_model` invokes a supplied model for inference; `core/config.py` specifies a default tag. Prompt/schema work is implementation configuration, not hyperparameter search. There is no documented comparative model-selection experiment, so no performance rationale should be invented.

8. **How would you scale this while preserving evaluation integrity?**
   Current code is serial and local (`run_script`, `fetch`, `RunLog`). Proposed changes are bounded concurrency, pooled/snapshot-consistent DB access, durable per-case records with resume semantics, transient retries that do not hide failure rates, and pinned provenance. Before optimizing throughput, fix ambiguous references and calibrate the judge; faster execution cannot repair an invalid evaluation criterion.

## 10. Evidence Index

Strength describes repository evidence, not personal ownership: **Direct code** establishes implementation; **test source** establishes intended regression coverage, not an observed test pass; **fixture/config** establishes supplied data or executable configuration, not successful live operation; **inference** identifies a derived consequence.

| Technical claim | Supporting file path | Relevant function/class/test | Evidence strength | Qualification |
| --- | --- | --- | --- | --- |
| Three independent suites | `core/runner.py` | `SCRIPTS`, `run_script` | Direct code | Not a chained agent/application test |
| Typed identity and paired-reference validation | `core/loader.py` | `_id_key`, `load_cases`, `_index_by_id` | Direct code + test source | Does not validate label semantics |
| Case shape validation | `core/loader.py` | `validate_case_payload` | Direct code | Partial field validation, extra keys allowed |
| Pretrained model inference boundary | `core/ollama.py`, `core/config.py` | `run_model`, `model_name` | Direct code | External model internals/training not implemented here |
| Intent classification with enum output | `scripts/intent_test.py` | `_INTENT_SCHEMA`, `run` | Direct code | No action generation; no confidence score |
| Final JSON separated from reasoning wrappers | `scripts/model_output.py`, `tests/test_harness.py` | `final_json`, `test_final_json_preserves_reasoning_tags_inside_sql_literals` | Direct code + test source | Not a universal model-output repair system |
| Schema-conditioned SQL generation | `scripts/sql_test.py`, `core/schema_contract.py` | `run`, `prompt_schema`, `TABLE_FIELDS` | Direct code | Count tasks; no retrieval ranking |
| Scoped SQL relation policy | `core/sql_guard.py`, `tests/test_harness.py` | `validate_read_query`, `_physical_relations`, `test_sql_guard_applies_postgres_identifier_case_to_cte_scope` | Direct code + test source | SQLGlot supplies parser/scope engine; incomplete sandbox |
| Strict scalar result | `core/db.py` | `scalar_count` | Direct code | Checks shape/type after all rows fetched |
| Count comparison permits false semantic matches | `core/evaluator.py`, `tests/test_harness.py` | `_query_result`, `test_sql_result_matching_does_not_claim_semantic_equivalence` | Direct code + test source | No semantic-equivalence proof |
| Supplied-record answer grounding | `scripts/llm_judge_test.py` | `run` | Direct code | Prompt guidance, not deterministic factuality guarantee |
| Strict model-judge verdict | `scripts/llm_judge_test.py`, `core/evaluator.py` | `judge`, `_from_judge` | Direct code + test source | No judge-quality calibration |
| Judge handles quoted/mutation cases in wiring tests | `tests/test_harness.py` | `test_grounded_judge_distinguishes_quoted_content_mutations_and_negation` | Test source | Predetermined mocked verdicts, not live comprehension |
| Separate mismatch and execution errors | `core/runner.py`, `core/evaluator.py` | `run_script`, `EvaluationError` | Direct code | Selected suite-level exceptions can escape |
| Continue after evaluation/validation errors | `tests/test_harness.py` | `test_runner_records_evaluator_errors_and_continues`, `test_later_case_validation_error_does_not_discard_prior_result` | Test source + direct code | Not retries or resume |
| Read-only connection settings and timeouts | `core/db.py` | `connect`, `fetch` | Direct code | Live privileges/behavior not verified here |
| Shared schema-name preflight | `core/db.py`, `core/schema_contract.py` | `validate_database_contract`, `TABLE_FIELDS` | Direct code | No type/constraint/content checks |
| Atomic explicit fixture replacement | `db/reset_and_seed.sh`, `docker-compose.yml` | Transaction block; `db-seed` profile | Script/config | Destructive; rollback not tested live during review |
| Separate application and seed roles | `db/init-users.sql`, `db/migrate_existing_roles.sql` | Role creation/grants | Script/config | Existing write privileges are not revoked |
| Diagnostic artifacts and fixture fingerprints | `core/run_log.py`, `core/runner.py` | `RunLog.record`, `_sha256`, `run_script` | Direct code | No retained run artifacts inspected; incomplete provenance |
| Local containerized runtime | `Dockerfile`, `docker-compose.yml` | `harness`, `db`, `ollama` services | Config | Not evidence of deployed production application |
| 26 cases, 21 seed rows, expected reference counts | `data/*.json`, `db/seed_test_data.sql` | Dataset rows and INSERT/reference statements | Fixture + static derivation | Not live performance or accuracy measurements |
| Ambiguous task-count label | `data/sql_test_questions.json`, `data/sql_ground_truth.json` | Case 1 | Direct fixture evidence | Question does not state incomplete-only interpretation |
| Training/anomaly detection not demonstrated | `core/`, `scripts/`, `requirements.txt` | Inspected execution paths | Repository-scope absence | Does not establish the owner's experience outside this project |

## Claims Safe to Use on a Resume

Candidate technical achievements for human review. Confirm personal contribution before using first-person ownership; these describe implementation, not measured quality improvements or production scale.

- Implemented a Python evaluation harness with exact intent checks, PostgreSQL count-result comparisons, and LLM-judged grounded answers across 26 fixture cases.
- Integrated Ollama inference with structured output requests, final-JSON parsing, strict judge verdict validation, and configurable model-call timeouts.
- Added PostgreSQL AST/scope-based query restrictions using SQLGlot, alongside read-only connection settings and strict scalar-result contracts.
- Built per-case failure isolation and readable/JSONL diagnostics with error-stage categorization and SHA-256 fixture provenance.
- Added offline regression test coverage for SQL policy, model-output parsing, evaluation contracts, and continuation after case errors; test execution is not verified by this report.
