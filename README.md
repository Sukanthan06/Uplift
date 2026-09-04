# Uplift

Payment recovery through uplift-aware retry scheduling.

Uplift takes a failed payment, confirms with the gateway that it actually failed (not just that it was reported as failed), classifies the failure cause with an LLM, scores the expected incremental revenue of retrying it at each of several candidate times, and lets a deterministic policy engine decide whether, when, and how to retry. Every external call runs through a single bounded action service with idempotency keys and a hash-chained audit log. The system is built and evaluated against a simulated payment population with a grounded decline taxonomy and a hidden causal recovery curve, so the retry policy can be scored honestly against baselines before anyone trusts it with real money.

## The problem

A payment failure is not one thing. Some declines are transient (an issuer's system was briefly down), some are structural (the card is expired, the account is fraud-flagged), and some depend entirely on timing (a customer's account will have funds again on payday, not now). A merchant that retries every failure the same way is solving the wrong problem twice: retrying transient failures immediately, before the underlying cause has cleared, and retrying structural failures at all, which burns processing cost and irritates the customer for a payment that was never going to succeed.

The obvious fixes both fail in a specific way. Never retrying leaves real, recoverable revenue on the table. Retrying everything, repeatedly, recovers more revenue but does so inefficiently: on this project's simulated 50,000-attempt population, retrying every failed payment three times recovers ₹4.08M against ₹369k of revenue that customers or banks would have recovered on their own with no retry at all, but it does so by spending nearly 2.75x the retries of a policy that targets and times its retries by cause. Uplift is the correct objective because it asks the only question that matters commercially: not "will this payment succeed if I retry it" (which a transient failure would answer "yes" to unprompted, on its own, without spending anything), but "does retrying this payment now create revenue that would not otherwise exist." A policy graded on that question can be worse than brute force on raw recovery and still be the better policy, because it spends less to get there.

Concretely: on the same 50,000-attempt population, a hand-picked rule that simply skips hard declines and times the rest by cause (wait out an outage, retry insufficient-funds near payday) recovers 92% of the brute-force retry-three-times policy's revenue using 36% of its retries. That result holds before any model exists. The uplift model's job is to see whether learning from data beats that hand-picked rule, and to report honestly if it doesn't yet.

## How it works

A failed payment enters through the reconciler, which exists because a "failed" status is not always true. Some decline codes (a payment timeout, a UPI timeout) mean the gateway genuinely could not confirm what happened, and the charge may have gone through anyway. The reconciler resolves that ambiguity before anything downstream is allowed to act, and no retry decision is ever made against an unreconciled or unknown status.

Once a payment is confirmed known-failed, the diagnoser sends its decline code and description to an LLM and gets back a structured diagnosis: a cause family, whether the failure looks transient, a human-readable root cause, and a confidence score. This is the LLM's only job. It classifies; it does not decide anything about money. That boundary is enforced downstream, not just documented, which matters in practice: a live run of this system had the LLM classify a hard decline (an invalid UPI account, unretriable) as a soft customer error, which would have let a bad retry through if anything trusted that classification for a safety-critical decision. It didn't, because the block check runs off a separate, deterministic lookup, never off the LLM's own opinion.

The scorer then takes the diagnosed attempt and estimates its uplift: the difference between the probability the payment recovers if retried and the probability it recovers on its own, computed separately for retrying now versus retrying at each of several later offsets. This is a T-learner, two independent models rather than one, because a single model trained to predict "will this succeed if retried" would happily retry payments that were going to succeed anyway, at real cost, for zero incremental revenue. The scheduler turns the scorer's numbers into a concrete decision: retry now, retry later at whichever offset the model predicts is best, or don't retry at all if no offset shows positive expected uplift.

The policy engine is the last gate before anything happens, and it is deliberately not a model. It reads a small set of rules from a config file: the payment must be reconciled, its cause family must not be on a hard block list, the diagnosis confidence must clear a floor, and the predicted uplift must be positive. Any model, any LLM, any future addition to this pipeline still has to pass through this same deterministic gate, which is the point: the probabilistic parts of the system get to suggest, and only this part gets to authorize.

If the policy engine approves a retry, the action service is the only component that ever calls an external payment API, and it does so with a budget. Every call carries an idempotency key derived from the payment, the action, the scheduled time, and the policy version in effect, so calling it twice with the same inputs never charges twice. On a failing gateway it retries with exponential backoff up to a hard cap, then stops and raises an incident rather than looping. Every stage, whether it acted or not, writes an entry to a hash-chained audit log, so the full sequence of what was decided and why is reconstructable and tamper-evident after the fact.

## Architecture

```
                 ┌─────────────┐
  failed payment │  Reconciler │  confirms true status
 ───────────────>│             │──────┐
                 └─────────────┘      │ known-failed
                                       v
                                ┌─────────────┐
                                │  Diagnoser  │  LLM: classify only
                                │   (Groq)    │
                                └──────┬──────┘
                                       v
                                ┌─────────────┐
                                │   Scorer    │  T-learner: uplift(now), uplift(offset)
                                └──────┬──────┘
                                       v
                                ┌─────────────┐
                                │  Scheduler  │  now / later / never
                                └──────┬──────┘
                                       v
                                ┌─────────────┐
                                │   Policy    │  deterministic gate (policy.yaml)
                                │   Engine    │
                                └──────┬──────┘
                                       │ approved
                                       v
                                ┌─────────────┐
                                │   Action    │  idempotent, bounded retries,
                                │  Service    │  the only external caller
                                └──────┬──────┘
                                       v
                                ┌─────────────┐
                                │ Audit Log   │  hash-chained, every stage
                                └─────────────┘
```

The one architectural principle worth naming is the boundary between the probabilistic middle of this pipeline and the deterministic edges around it. The diagnoser and the scorer are both allowed to be wrong, approximate, or occasionally miscalibrated, because nothing they produce can directly cause money to move. The policy engine and the action service are not models at all; they are a rules file and a bounded HTTP client, and everything that touches an external system or a retry decision has to pass through one of the two. The reconciler, diagnoser, and action service's gateway client are each defined as a small interface (a Protocol, in Python's terms) rather than a concrete implementation, specifically so the gateway and the LLM provider can be swapped or mocked without touching the decision logic that sits between them.

See `ARCHITECTURE.md` for the full component breakdown and data model.

## Evaluation

Every policy below is scored against the same simulated population using the same methodology: expected value computed analytically from each attempt's true (simulated) recovery probability, not a single random draw, so the comparison is deterministic and not dominated by sampling noise.

Baseline comparison, all 6,693 failed attempts in the 50,000-attempt population, no machine learning involved:

| Policy | Recovered (₹) | Retries | Cost/₹ recovered | Customer contacts | Near-misses |
|---|---|---|---|---|---|
| Do nothing | 369,031 | 0 | 0.0000 | 0 | 0 |
| Retry all (1×) | 2,797,993 | 6,693 | 0.0048 | 1,250 | 35 |
| Retry all (3×) | 4,083,535 | 14,336 | 0.0070 | 2,643 | 35 |
| Rule-based | 3,756,049 | 5,227 | 0.0028 | 1,250 | 35 |

Do-nothing's recovered amount is not zero because some payments recover on their own, without any retry; that is the correct floor to measure incremental revenue against, not zero. The rule-based policy, which only knows to skip hard declines and time the rest by cause, recovers 92% of retry-3×'s revenue at 36% of its retry volume and less than half its cost per rupee recovered. That result requires no model.

Head-to-head on the held-out chronological test set (1,107 attempts from the final 15 days, never seen during training), uplift-ranked matched to rule-based's budget so both spend the same money:

| Policy | Recovered (₹) | Retries | Cost/₹ recovered | Customer contacts | Near-misses |
|---|---|---|---|---|---|
| Do nothing | 60,272 | 0 | 0.0000 | 0 | 0 |
| Retry all (1×) | 448,728 | 1,107 | 0.0049 | 204 | 7 |
| Retry all (3×) | 652,834 | 2,381 | 0.0073 | 431 | 7 |
| Rule-based | 602,287 | 863 | 0.0029 | 204 | 7 |
| Uplift-ranked | 592,384 | 863 | 0.0029 | 194 | 7 |

The learned model ties, and narrowly loses to, the hand-picked rule: 1.6% less revenue at the identical budget. That is reported as the actual result, not adjusted. Two numbers say the model's ranking is nonetheless real signal, not noise: `uplift@20%` is 0.78 (the top-20%-by-predicted-uplift group shows a 0.78 percentage-point higher observed recovery rate among treated attempts than control), and the Qini curve is positive and rises across the entire ranking rather than flattening or reversing partway through. The likely explanation is not a flawed approach but a small sample: the rule already encodes the causal structure that roughly 4,400 training examples can teach a model, and 1,107 held-out attempts is a small population for stable causal-effect estimation.

The sensitivity sweep tests that explanation directly by varying the simulated base decline rate, which controls how much failure volume (and therefore training and test data) each scenario has. The uplift-ranked policy's margin against rule-based moves from -22.7% at half the default decline rate, to -0.6% near the default rate, to +2.5% at twice the default rate — a model that never wins in this sweep, but whose gap to the baseline narrows and eventually reverses as data volume increases. Two of the four swept parameters, retry cost and customer patience decay, show no effect on the margin at all, which is expected rather than a wasted test: the margin is defined on recovered revenue, and retry cost never enters that calculation, while patience decay only compounds across multi-retry policies and both rule-based and uplift-ranked here issue a single retry per attempt.

The decline taxonomy behind this population is grounded in real PSP and card-network documentation (Razorpay's published card error codes, ISO 8583 response codes, NPCI UPI response codes; netbanking and wallet codes are extrapolated from the same cause families and marked as such). The recovery-probability curves, outage frequency and duration, and per-attempt cost are illustrative, not sourced statistics — real decline distributions and recovery curves are proprietary to payment processors and issuers. Every one of those numbers lives in one config file specifically so it can be swept and the honest range of outcomes shown, rather than picked once and hidden. A production deployment would replace every illustrative number here with the merchant's own historical recovery data, at volumes this simulation's 90-day, 50,000-attempt window does not attempt to represent.

## Running locally

```bash
git clone https://github.com/Sukanthan06/Uplift
cd Uplift
cp .env.example .env   # add GROQ_API_KEY to enable the diagnoser
docker compose up -d --build
```

Open http://localhost:5173 for the dashboard. `docker compose up` starts three services in dependency order: Postgres first (waited on via a health check), then the FastAPI backend, then the Vite frontend — backend and frontend both bind-mount their source, so code changes apply without a rebuild.

The population and models are not generated automatically on startup. Inside the running backend container:

```bash
docker compose exec backend alembic upgrade head
docker compose exec backend python -m simulator.generator
docker compose exec backend python -m ml.train_uplift
docker compose exec backend python -m ml.evaluate
```

`http://localhost:8000/health` should return `{"status": "ok"}` once the backend is up; `http://localhost:8000/docs` has the full interactive API schema.

## Configuration

| Variable | Default | Description |
|---|---|---|
| `DATABASE_URL` | — | Postgres connection string. Set by `docker-compose.yml` for the containerized backend; only needed in `.env` for running the backend outside Docker. |
| `GROQ_API_KEY` | — | Required for the diagnoser to make real LLM calls. Everything through Phase 4 (simulator, baselines, uplift model, sensitivity sweep) works without it. |
| `GROQ_MODEL` | `openai/gpt-oss-120b` | Model passed to the Groq API. |
| `POLICY_VERSION` | `v1` | Tag stored on every decision and folded into each idempotency key; bump it when `policy.yaml`'s rules change meaning. |
| `ACTION_MODE` | `mock` | Which `GatewayClient` backend the action service uses: `mock` (deterministic, no external call), `razorpay_test` (real HTTP to Razorpay's sandbox, test-mode key only), or `off` (shadow — logs the intended action, calls nothing). |
| `RAZORPAY_API_KEY` | — | Required only when `ACTION_MODE=razorpay_test`. Must start with `rzp_test_`; a live key is rejected at startup. |
| `RAZORPAY_API_SECRET` | — | Paired with `RAZORPAY_API_KEY`. |
| `RAZORPAY_TEST_ENDPOINT` | `https://api.razorpay.com/v1` | Razorpay API base URL. |
| `ENV` | `development` | Not currently read for branching logic; reserved for future environment-specific behavior. |

Retry-blocking rules, the confidence floor, and the retry-budget cap live in `backend/app/config/policy.yaml`, not in code — changing what gets retried or under what conditions means editing that file, not the policy engine itself.

## API

| Method | Path | Description |
|---|---|---|
| GET | `/health` | Liveness check. |
| GET | `/overview` | Simulator stats, baseline and uplift-model comparison tables, sensitivity sweep results, and live pipeline activity counters — everything the dashboard's Overview page renders. |
| GET | `/decisions` | Most recent decisions, newest first. |
| GET | `/decisions/{decision_id}` | One decision's full record: the payment, its reconciliation, its diagnosis, its uplift scores, the rules that fired, the resulting action, and its audit trail. |
| GET | `/batch/run?limit=N` | Runs `N` failed attempts through the live pipeline (real LLM calls, real Postgres writes) and streams one result per attempt over Server-Sent Events. |
| GET | `/audit/verify` | Walks the entire hash chain and reports which records are valid, and the first one that isn't, if any. |

Full request/response schemas are at `/docs` (FastAPI's generated OpenAPI UI) while the backend is running.

## Safety properties

Reconciliation runs before every retry decision, with no exception. A payment whose true status is unknown is never a candidate for retry, because retrying a payment that may have already succeeded is how a customer gets charged twice. The reconciler exists specifically to close that gap before anything downstream can act on a status that turns out to be wrong.

The policy engine is a deterministic gate, not a model, and it sits between every probabilistic component in this system and any action that touches money. It exists as a separate component, not folded into the scorer or the diagnoser, so that a bad LLM classification or a miscalibrated uplift score can be caught by a rule that does not care what either of them said. That separation is not theoretical: a live run of this pipeline had the LLM classify a hard, unretriable decline as a soft one, and the policy engine still blocked the retry, because its block check runs off a fixed, deterministic classification of the decline code, never off the LLM's own output.

Every external action carries an idempotency key built from the payment, the action type, the scheduled time, and the policy version in effect, hashed together. Before the action service ever calls an external API, it checks whether an action with that exact key already exists and, if so, returns its recorded result instead of calling again. That is what makes it actually safe to call twice, not merely deterministic to compute.

The action service enforces a hard cap of two retries on a failing gateway call, with exponential backoff between attempts, and nothing in this codebase retries past that cap under any circumstance. Once the budget is exhausted, the service stops, records the outcome as exhausted rather than retrying indefinitely, and writes an incident record rather than silently giving up. An infinite retry loop against a genuinely broken gateway is the failure mode this cap exists to make structurally impossible, not just unlikely.

## Limitations and production path

The gateway reconciliation lookup is mocked, not a real call to a payment processor's status API. It is not a coin flip — for the specific decline codes where a real gateway could not have confirmed the outcome either, it resolves from the same hidden ground truth the simulator itself used to decide what actually happened, so it answers the way a real gateway honestly would for those cases. But it is still a lookup against a file, not a network call, and a real deployment needs an actual reconciliation API integration with its own failure modes (timeouts, partial responses, rate limits) that this build has not had to handle.

The action service's real backend, when enabled, creates a sandbox test order rather than retrying an actual captured payment, because every payment in this system is simulated and none of them exist as real Razorpay transactions to retry. It proves the integration path (a real authenticated HTTP call, a real response, the same idempotency and retry-budget logic handling it) but is not evidence that a real payment-capture retry would behave identically under load or under Razorpay's production rate limits.

The uplift model has no hyperparameter search behind it — both XGBoost models use untuned defaults, a deliberate scope cut given the timeline, not an oversight. The evaluation above shows the model is limited by training-data volume more than by tuning, so a search would likely move the result less than more data would, but that has not been verified. There is also no retraining loop: the model is trained once, offline, against a fixed historical window. A production deployment needs a defined retraining cadence, drift monitoring against the live decline-code distribution, and a rollback path if a newly trained model regresses against the currently deployed one.

The audit log's append operation is not safe under concurrent writers — it reads the last record, computes the next hash, and inserts, with no database-level lock around that sequence. Fine for this single-process build; a deployment with concurrent request handling needs a serializable transaction or row lock around that read-compute-insert sequence, or two simultaneous appends can chain off the same prior record.

Nothing here has run against real payment traffic. The credible path from this system to production is the standard one for a model that is allowed to influence, but never directly authorize, money movement: run the full pipeline in shadow mode against live traffic first (diagnose, score, decide, but never call the action service), compare its decisions against what actually happened with no retry policy running at all, then roll the actual retry action out to a small percentage of real traffic before trusting it with all of it. Every step of that path is exactly what this project's evaluation harness was built to make honest, not something bolted on afterward.

## Development

```bash
cd backend
uv sync --extra dev
uv run pytest -x -q
uv run ruff check .
uv run ruff format --check .
docker compose exec backend python -m simulator.generator   # regenerate the simulated population
docker compose exec backend python -m ml.train_uplift        # retrain both T-learner models
```

The test suite (97 tests) needs no database or network access — DB-touching functions are exercised against an in-memory fake session, and every external call (the LLM, the payment gateway) is injected behind a small interface and swapped for a test double.

Work happens on one branch per feature (`feat/`, `fix/`, `chore/`, `docs/` prefixes), merged into `develop` with `--no-ff`; `develop` merges into `main`, which stays deployable, at phase boundaries only.

## Stack

| Layer | Technology | Why |
|---|---|---|
| API | FastAPI + Python 3.11 | Async-capable but used synchronously throughout, matching a batch/simulation workload with no need for concurrent request fan-out. |
| Database | PostgreSQL 16, SQLAlchemy 2.0, Alembic | Relational schema with a real foreign-key graph (attempts → reconciliations/diagnoses/decisions → actions); migrations tracked from the first table. |
| ML | XGBoost (T-learner: two independent classifiers) | Two-model uplift estimation implemented directly rather than through a causal-ML framework, so the leakage boundary and the grading methodology are both auditable in this repo's own code. |
| Inference | Groq (`openai/gpt-oss-120b`) | Structured-output LLM calls for failure classification only; swapped in for the originally planned vendor by explicit choice, see `docs/DECISIONS.md`. |
| Frontend | React 18, Vite, Tailwind, Recharts | Single page, four tabs, no router — small enough surface area that client-side tab state is simpler than routing. |
| HTTP client | httpx | The one dependency allowed to make a real external call, confined to a single file by an architecture test. |
| Containers | Docker, Docker Compose | Three services (Postgres, backend, frontend), source bind-mounted for both app services so the container rebuilds only when a dependency changes. |
