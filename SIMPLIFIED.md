# Eval Harness, in Plain Language

## 1. What this project does

Think of this project as an examiner for an AI assistant. It gives the AI prepared questions, checks its responses, and saves a report.

It checks three abilities:

1. **Understanding the request:** Does the user want to read information, change something, or just chat?
2. **Finding information:** Can the AI ask a database for the right information?
3. **Explaining the answer:** Can the AI give a useful answer based on the records it receives, without making things up?

The examiner is kept separate from the application so its tests and marking rules can stay consistent as the application changes.

**An important boundary:** This project runs selected AI behaviors directly using a locally running AI model and a prepared test database. It does not run the complete production application or test its entire information-finding process.

## 2. How the pieces fit together

The basic flow is:

**Prepared questions and expected answers → AI response → checking → saved report**

Different parts of the project load the questions, run the tests, decide the results, and save the reports. Keeping those jobs separate makes the project easier to maintain and extend.

Some responses can be checked using fixed rules. Others need a second AI to judge their meaning.

## 3. What happens during a test run

1. **Choose the tests.** Run a group of tests or a particular question.
2. **Check the test materials.** Each question must have a matching expected answer and a unique identifier. The files must contain the required information and cannot include pre-filled actual results.
3. **Give the AI the question.** The AI receives the test input, not the expected answer used to grade it.
4. **Collect its response.** Depending on the test, this is a request category, a database query and its result count, or an answer based on supplied records.
5. **Check the response.** Compare it with the expected result using the appropriate marking method.
6. **Save the outcome.** Record the input, response, result, and explanation, along with settings and fingerprints identifying the test files used.

There are three possible outcomes:

| Outcome | Meaning |
|---|---|
| **PASS** | The response met the test's rules. |
| **FAIL** | The response could be checked, but did not meet those rules. |
| **ERROR** | Something prevented a proper check—for example, an invalid response or a problem running the test. |

When an individual test encounters an error, it is recorded and later tests continue. Problems with the overall test setup can prevent the run from getting that far.

Reports are saved in both a human-readable form and a form other programs can process.

## 4. The three kinds of tests

### A. Does the AI understand what the user wants?

The AI must classify a request as **read**, **write**, or **chat**. For example, asking to see information is a read request; asking to change it is a write request.

The response must match the expected category and required response structure exactly. There is no need for another AI to judge this because the allowed answers are fixed.

An unreadable response or an invalid category is an error, rather than simply a wrong answer.

### B. Does the AI find the right amount of information?

The AI writes a database query: an instruction asking the database for information. The project checks that it is allowed, runs it on the test database, and compares its result count with the count from a prepared correct query.

Safety checks restrict the AI to reading approved information. They block changes to data, access to unapproved tables, and other disallowed query patterns. The database connection also prevents changes and limits how long queries can run.

**The main limitation is that this test compares counts, not the actual records.** If the correct answer contains five matching items and a wrong query also reports five, the test can pass. Passing therefore does not prove that the AI found the right items.

### C. Does the AI explain the supplied information correctly?

The AI receives a question and some records, then writes an answer. A second AI acts as the examiner and checks whether the answer:

- Addresses the question.
- Is supported by the supplied records.
- Ignores instructions hidden inside those records.
- Avoids claiming it changed anything without evidence.

Different wording can still pass if the meaning is correct. An appropriate answer saying that no information was found can also pass when no records were supplied.

The examiner must return a clear pass/fail decision and a reason in the required format. If it does not, the result is an error.

**This examiner is also an AI, so its decisions can vary or be wrong.** There is currently one judgment per answer, with no automatic second opinion or retry.

## 5. Why the project is designed this way

These are the likely reasons behind the main design choices:

| Choice | Why it helps | Trade-off |
|---|---|---|
| Separate running, checking, and reporting | Each part is easier to change and test. | There are more pieces than in a single script. |
| Use exact checks for request categories | Fixed answers can be checked clearly and cheaply. | Even a small mismatch in the required structure matters. |
| Compare database result counts | Different ways of writing a query can still pass. | Wrong queries can produce the same count. |
| Check queries before running them | Helps prevent unwanted database operations. | Adds rules that must be maintained. |
| Use an AI examiner for written answers | Allows correct answers with different wording. | AI judgment is less predictable than fixed rules. |

## 6. How reliable are the results?

The fixed checks are predictable when the test files and database stay the same. AI-generated responses and AI judgments can change between runs.

The project saves settings, responses, explanations, and file fingerprints so someone can investigate what happened. Those records help identify the materials used, but they do not guarantee identical results next time.

There are automated tests for the checking rules, database protections, handling of invalid responses, consistency of test data, and continuation after individual errors. These do **not** prove that the AI examiner always judges correctly or that a complete live run will always repeat exactly.

Possible improvements include tighter control of AI settings and model versions, repeated judgments, better records of the environment and database state, and checking the examiner against examples with known correct verdicts. **These are proposals, not current features.**

## 7. What would need to change for much larger runs?

The project currently handles cases one at a time. At a scale such as 100,000 questions, repeated AI calls and database work would make runs slow and resource-intensive.

Possible improvements include:

- Running a controlled number of tests at the same time.
- Grouping work where possible and respecting service limits.
- Saving progress so interrupted runs can resume.
- Retrying temporary failures after a delay.
- Storing large reports in a more durable, manageable way.
- Measuring speed, cost, errors, database load, and agreement between AI examiners.

Other proposed additions are testing the deployed application directly, running evaluations automatically when code changes, tracking whether results get worse over time, and reviewing disagreements between examiners.

**These larger-scale capabilities are not implemented here.**

## 8. How to explain this project in an interview

### A short explanation

“I built a separate testing tool for three AI abilities: understanding a request, asking a database for information safely, and answering from supplied records. It uses prepared questions and expected answers, runs the AI, and saves a result and explanation for each test. Fixed answers use exact checks, database tests compare counts, and written answers are assessed by another AI. The main limitations are that matching counts can hide incorrect database queries, and AI examiners can make mistakes.”

### A longer explanation

Start with the journey of one question: load it, check the test materials, ask the AI, check its response, and save the result. Then explain the three marking methods above.

Make clear that the project tests selected behaviors directly, rather than the full production application. Finish with how errors are recorded, what the reports preserve, and what would need to improve for larger or more dependable runs.

### Common questions

**Why keep the testing tool separate?**  
So the application can change while the test questions and marking rules remain consistent.

**Why not use an AI examiner for every test?**  
When there is a fixed set of allowed answers, direct comparison is simpler, cheaper, and more predictable.

**Can different database queries both be correct?**  
Yes. Comparing counts allows different queries to pass, but it can also let incorrect queries pass. Checking the returned records would provide stronger evidence.

**Will every run give the same results?**  
The fixed checks should behave consistently with the same materials. AI responses and judgments may vary.

**What if the AI examiner is wrong?**  
That remains a limitation. Repeated checks, independent examiners, and human review are possible improvements, but are not currently implemented.

**What happens when something breaks?**  
An individual test records an error and the run continues with later cases. A response that is checked successfully but misses the expected result is a failure.

**How would you handle many more tests?**  
Measure the bottlenecks, run a controlled amount of work in parallel, save progress, and retry temporary problems without overwhelming the AI or database.

**Why not test the deployed application directly?**  
That would test more of the real system, but also introduces service and connection problems. The current approach is simpler and covers a narrower scope.
