# Eval Harness

**Python | PostgreSQL | Ollama | Qwen3 | Docker**

## Resume wording

- Built three evaluation paths for intent classification, SQL result counts, and natural-language generation, combining deterministic checks for structured outputs with LLM judging for flexible responses.
- Implemented an LLM-as-a-judge pipeline to assess answer correctness and grounding against reference answers and supplied context while accepting semantically equivalent wording.
- Developed a Dockerized CLI workflow with per-case results, persistent log and JSONL artifacts, failure categorization, and continued execution after per-case errors.

## Coverage in WALKTHROUGH.md

All three claims are covered in [WALKTHROUGH.md](WALKTHROUGH.md), with the qualifications explained below.

| Resume claim | Walkthrough coverage |
| --- | --- |
| Three evaluation paths and deterministic versus LLM evaluation | Sections 1, 3, and 4 describe intent, SQL count comparison, and grounded answer judging. Section 5 explains the evaluation choices. |
| Judge correctness, grounding, and equivalent wording against references/context | Section 3 identifies the question, ideal answer, records, and generated answer passed to the judge. Section 4C describes grounding and equivalent wording. |
| Dockerized CLI, per-case artifacts, failure categories, and resilient execution | Section 2 describes Docker Compose; section 3 describes the CLI lifecycle, artifacts, and error continuation; section 6 explains reliability and failure categories. |

The walkthrough names PostgreSQL, Ollama, and Docker and describes the Python implementation. It does not explicitly name Qwen3. The default `qwen3:1.7b` is confirmed in [core/config.py](core/config.py), [docker-compose.yml](docker-compose.yml), and the setup section of [README.md](README.md).

## 1. Three evaluation paths

The project separates evaluation by the kind of output being checked. JSON question and ground-truth files are paired by case ID, an adapter produces an actual output, and the central evaluator chooses the appropriate comparison method.

| Path | What runs | How the result is evaluated |
| --- | --- | --- |
| Intent classification | An Ollama adapter classifies a query as `read`, `write`, or `chat` and returns an intent/actions object. | Exact equality against the reference object checks both the label and output structure. |
| SQL/data results | An adapter generates SQL, validates it as an allowed read query, and executes it against PostgreSQL. | The evaluator executes reference SQL and compares its scalar count with the generated query's count. Different SQL text can pass if the counts match. |
| Natural-language generation | An adapter generates an answer from the question and supplied records. | A separate judge call assesses the answer against the question, reference answer, and records. |

Deterministic checks fit intent and counts because those outputs have precise contracts. Natural-language answers can express the same facts in different words, so exact string equality would reject valid paraphrases.

For example, two queries returning a count of `3` pass the count comparison even if their SQL text differs. An answer such as “You have three pending tasks” can also be accepted instead of “There are three pending tasks,” provided the records support that statement.

These are independent suites: running `all` runs each suite, rather than feeding intent output into SQL and SQL output into answer generation. SQL count equality is limited to the current fixture; it does not prove query equivalence or matching row sets. The harness invokes local adapters, not a deployed application's HTTP API.

Implementation: [core/runner.py](core/runner.py), [core/evaluator.py](core/evaluator.py), and the active adapters under `scripts/`.

## 2. LLM-as-a-judge pipeline

The natural-language suite makes one model call to generate an answer and another to judge it. The judge receives four inputs: the original question, `ground_truth.ideal_output`, the supplied records, and the generated answer.

The judge prompt asks it to assess:

- **Correctness:** Does the answer address the question and agree with the supported meaning of the reference?
- **Grounding:** Are its factual claims supported by the record fields, without invented facts or unsupported claims that data was changed?
- **Equivalent meaning:** Does it preserve the correct meaning despite harmless differences in wording or formatting?

Records are explicitly marked as untrusted data, and the prompt tells the model to ignore instructions embedded in them. The verdict must contain exactly a boolean `passed` and a string `reason`; invalid structures or types become evaluation errors. This makes the model's judgment usable by the same PASS/FAIL reporting flow as the deterministic checks.

“Semantic variation” means accepting equivalent wording here. The implementation does not compute a separate semantic similarity score or separate scores for correctness and grounding. It returns one combined verdict and explanation. Generation and judging use the same configured model by default, so this is a separate evaluation call rather than an independent model. Judge accuracy is not established by the offline tests, and there is no calibration, multi-judge voting, or automatic retry.

Implementation: [scripts/llm_judge_test.py](scripts/llm_judge_test.py) and [core/evaluator.py](core/evaluator.py).

## 3. Dockerized CLI and resilient execution

Docker Compose runs PostgreSQL, Ollama, and a Python harness container. PostgreSQL supplies the database fixture, Ollama serves the configured model, and the harness runs evaluation commands. Qwen3 (`qwen3:1.7b`) is the default generation and judge model. Fixture seeding is an explicit operation.

Once the stack and fixture are prepared, the CLI supports whole-suite and individual-case execution:

```bash
docker compose exec harness python -m core.loader --script all
docker compose exec harness python -m core.loader --script sql --case-id 8
```

Each run writes uniquely named human-readable `.log` and machine-readable `.jsonl` files. The readable log preserves inputs, references, actual outputs, reasons, and error details. JSONL records preserve per-case statuses and suite manifests with model configuration, schema version, and SHA-256 hashes of question, reference, and seed files. The host-mounted `logs/` directory retains artifacts beyond the container's lifetime.

Failures have distinct meanings:

| Outcome | Meaning |
| --- | --- |
| `PASS` | The output satisfies the selected evaluator. |
| `FAIL` | Evaluation completed, but the output did not satisfy it. |
| `ERROR` | Validation, adapter execution, or evaluation raised an exception; the recorded stage is `validate`, `run`, or `evaluate`. |

Per-case exception handling records the error and continues to later cases, preserving completed results. Model and database timeouts bound calls, and logs are flushed as they are written. CLI totals and exit codes let callers distinguish successful runs, failed/error cases, and handled configuration or suite-level errors.

“Resilient execution” refers to this error isolation, timeout handling, and artifact preservation. It does not imply automatic retries, checkpoint/resume support, distributed execution, or complete reproducibility of model responses.

Implementation: [Dockerfile](Dockerfile), [docker-compose.yml](docker-compose.yml), [core/loader.py](core/loader.py), [core/runner.py](core/runner.py), and [core/run_log.py](core/run_log.py).

## Interview explanation

“I built a Python evaluation harness with three independent suites. Intent outputs use exact object comparison, generated SQL is checked by executing it against PostgreSQL and comparing counts with reference SQL, and natural-language answers use an LLM judge that checks meaning and grounding against supplied records. Ollama runs Qwen3 locally, and Docker Compose packages the workflow. The CLI saves per-case results and run metadata, distinguishes incorrect answers from execution errors, and continues after individual case errors. The main limitations are count-only SQL checks and probabilistic model judgments.”
