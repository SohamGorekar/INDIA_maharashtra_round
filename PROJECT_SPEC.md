# Black Box: Project Spec and Remaining Work

> **For Claude Code:** Read this file fully before writing any code. It records every decision already made and everything still to be built. `black_box_implementation_guide.md` (already in this repo) is the general tooling reference; this file is the source of truth for *what we are building*. If the two conflict, this file wins. Build stage by stage (see Section 11), and do not start a stage until the previous stage's acceptance check passes.

---

## 1. Context

- **Event:** Google Developer Groups (GDG), FRCRCE, "Bit N Build: Around the World", Internal Round.
- **Track:** AI/ML, Problem Statement 2: **Black Box: A Flight Recorder for AI Agents**.
- **Builder's background:** limited AI/ML experience. Explain non-obvious ML steps in code comments and keep the code readable and simple.
- **Tooling:** everything is built with Claude Code inside VS Code.

## 2. The problem statement (summary)

AI agents solve tasks through long chains of steps (LLM calls, tool calls, retrieved context, changing state). A run can have many correct steps and still fail because of one bad intermediate decision. Normal traces show *what happened* but not *which step caused the failure*, especially across thousands of runs.

**We must build an AI-powered debugging system that:**

1. **Captures execution data** from successful and failed agent runs.
2. **Trains a model** to recognize patterns of success and failure and to identify the most likely failure-causing step. A prompt to an LLM alone is NOT enough; there must be a real training pipeline, dataset, and evaluation.
3. **Explains the diagnosis** with evidence from the trace.
4. **Supports checkpointed replay**: investigate a run from an intermediate state without re-running earlier steps.
5. **Supports alternative execution (counterfactuals)**: change a suspected step, resume from its checkpoint, and observe the effect on the final outcome.
6. **Evaluates the model**: localization accuracy on known failures AND generalization to previously unseen failures.
7. **Compares traces** (original vs. modified run) to show how a change affected the outcome.

## 3. Decisions already made

| Decision | Choice |
|---|---|
| Agent domain | **Customer support: order support agent** (refunds, exchanges, cancellations) |
| Why this domain | Failures are *silent* (no exception thrown), so simple rules like "blame the first error" fail and a trained model is justified. Culprit step and symptom step are usually different. Side effects (refunds) justify sandboxed replay. Success is rule-checkable. It mirrors real products (Intercom Fin, Sierra, Decagon) and the public tau-bench benchmark. |
| Main agent | Order support agent with 5 tools |
| Second agent (generalization) | Small **SQL analyst agent** over the same SQLite database (e.g. "which product had the most returns?") |
| Language | Python |
| Storage | SQLite for the app database and traces, exported to Parquet/JSONL for training |
| Ground truth source | **Fault injection** (known fault step) plus rule-based success checker |
| UI | Streamlit (with FastAPI backend if needed) |
| Models | Baselines first, then a trained diagnosis model (details in Section 8) |

## 4. Open decisions (default shown; confirm or change)

| Open item | Default if not decided |
|---|---|
| LLM provider | Ollama (local small model, e.g. Qwen or Llama) for bulk run generation, plus Gemini API (free tier) for quality checks. Keep the provider behind one `llm_call()` function so it is swappable. |
| Agent framework | **Custom Python loop** (simpler to control, easy to checkpoint because state is plain JSON). Consider LangGraph only if checkpoint/replay becomes painful. |
| Team size / deadline | Unknown. Ask the user before planning the schedule. If time is short, cut per Section 12. |

## 5. The order support agent

### 5.1 Request types and decisions

Request types: **refund/return**, **exchange**, **cancellation**.

Every run ends in exactly one decision:
`APPROVE`, `DENY`, `REQUEST_PHOTO`, `ESCALATE`.

### 5.2 Tools

| Tool | Purpose | Notes |
|---|---|---|
| `get_order(order_id)` | Items, price, purchase date, ship status, final-sale flag | Reads SQLite |
| `check_policy(topic)` | Returns the relevant policy text | Start with keyword lookup over policy text files; upgrade to embedding retrieval (ChromaDB or sentence-transformers) later if time allows |
| `check_stock(item, size)` | In stock or not | Reads SQLite |
| `take_action(type, order_id, details)` | Issues refund, exchange, or cancellation | **Side-effecting. Must be mocked/sandboxed during replay and counterfactuals.** |
| `send_reply(message)` | Final message to the customer | Ends the run |

### 5.3 Fake data

SQLite tables: `orders`, `items`, `stock` (add `customers` if useful). Generate a few hundred orders with random dates, prices, sizes, and flags (`final_sale`, `shipped`). Use a **fixed "today" date** and fixed random seeds so everything is reproducible.

### 5.4 Policies (write as short text files)

1. Returns accepted within 30 days if the item is unused.
2. Damaged items eligible within 45 days; a photo is required.
3. Final-sale items cannot be returned unless defective.
4. Cancellation allowed only before the order ships.
5. Exchanges allowed within 30 days if the requested size is in stock.
6. Refunds above 5,000 (INR) must be escalated to a manager.
7. Shipping delays over 10 days qualify for a shipping-fee refund (optional, v2).
8. Warranty claims accepted within 12 months for defects.

Interacting rules (final-sale + defective, damaged + over 5,000) are intentional: they force the agent to combine facts and create more interesting failures.

## 6. Ground truth: the answer key

`correct_decision(order, request)` is the single source of truth for labeling runs. Rule precedence below; implement it as pure Python and **unit test it**. (Policy 7 is v2 and not in the function yet.)

```
1. cancellation:
     shipped            -> DENY
     else               -> APPROVE
2. reason = damaged:
     days > 45          -> DENY
     no photo provided  -> REQUEST_PHOTO
     price > 5000       -> ESCALATE
     else               -> APPROVE
3. reason = defective / warranty:
     days > 365         -> DENY
     price > 5000       -> ESCALATE
     else               -> APPROVE
4. any other reason (wrong size, changed mind, etc.):
     final_sale         -> DENY
     days > 30          -> DENY
     exchange and size not in stock -> DENY
     refund and price > 5000        -> ESCALATE
     else               -> APPROVE
```

Each generated task is stored with: request text, order id, request type, reason, photo flag, and the expected decision.

## 7. Success criteria and labels

A run is **SUCCESS** only if ALL hold:

- Final decision equals `correct_decision(...)`.
- Refund/exchange amount and item/size are correct (when applicable).
- Required process steps happened in order: `check_policy` before `take_action`; `check_stock` before an exchange.
- No forbidden action was taken (e.g. a refund on a DENY case).

Otherwise the run is a **FAILURE**. Record which criterion failed.

### Trace schema (keep from day one)

```
run_id, step_idx, step_type (llm | tool), tool_name,
input, output, latency, tokens,
state_snapshot (JSON),
-- ground truth, only for generated data:
fault_injected (bool), fault_type, is_culprit (bool)
-- run-level:
task_id, expected_decision, final_decision, outcome (success | failure), fault_step, benign (bool)
```

## 8. Faults and dataset generation

Implement the fault injector as **middleware** around tool calls and LLM calls. Inject at most one fault per run at a random step. Also generate fault-free runs. Log `fault_type` and `fault_step` as labels.

| Fault type | Where injected |
|---|---|
| `wrong_date` | `get_order` output (purchase date altered) |
| `wrong_policy` | `check_policy` output (wrong policy returned) |
| `wrong_order_id` | argument to `get_order` |
| `wrong_stock` | `check_stock` output (out of stock reported as in stock) |
| `skipped_check` | agent plan (required step removed) |
| `wrong_amount` | `take_action` argument |
| `benign_extra_field` | `get_order` output (harmless extra field) |

**Important:** if an injected fault does not change the final outcome, label the run `benign` and do NOT mark that step as the culprit. The model must learn not to blame benign faults.

**Target:** 1,000+ labeled runs (more is better), balanced across fault types, plus clean runs. Use a local model or free tier with retries and rate-limit handling. Save as JSONL/Parquet.

**Clean-run requirement:** the agent must solve a healthy majority (target 70%+) of fault-free tasks. If not, fix the agent before generating data, since the model needs successful runs to compare against.

## 9. Diagnosis model and evaluation

### Baselines (required)

1. Random step.
2. Blame the last tool call.
3. Blame the first tool call that returned an error.

### Models (build in this order)

1. **Step-level classifier**: features per step (tool name, error flag, output length, embedding similarity between step output and task/policy, deviation from the same step position in successful runs, whether required checks were done so far) fed to XGBoost or an MLP that outputs a "culprit" score per step.
2. **Sequence model** (main model if time allows): small transformer or BiLSTM over per-step embeddings (sentence-transformers) with a per-step output head, so it sees the whole run.

Prediction for a failed run: the step with the highest culprit score. Also expose top-k and a confidence value (and allow "uncertain" output).

### Explanations

For each flagged step, show evidence from the trace: for example "this step's output differs from the same step in successful runs", "retrieved policy has low similarity to the request", or "required check was skipped". Per-feature contributions (SHAP for the tree model) or attention weights can back this up.

### Evaluation (must produce a results table)

- Top-1 and top-3 step localization accuracy.
- Comparison against all baselines.
- **Held-out fault types:** train on some fault types, test on the rest, and rotate.
- **Held-out agent:** train on the support agent, test on the SQL analyst agent.
- Counterfactual fix success rate.
- Replay efficiency (steps reused vs. re-executed, and tokens saved).
- Calibration of confidence (plot) and behavior on benign faults.

## 10. Replay, counterfactuals, trace diff

- **Checkpoints:** save full agent state (JSON) after every step.
- **Record-and-replay cache:** key every LLM and tool call by a hash of its input. Steps before the checkpoint are served from cache, which handles nondeterminism. Use low temperature for newly executed calls.
- **Side-effect safety:** during replay and counterfactuals, `take_action` is stubbed. Show a clear "no production changes made" indicator.
- **Counterfactual runner:** load the checkpoint before the suspected step, patch its input/output (the correct value is known for injected faults), resume, and check whether the outcome flips to success. A flip confirms the diagnosis.
- **Metrics:** log steps reused vs. re-executed for every replay.
- **Trace diff:** structural comparison of two runs (`difflib` or DeepDiff) highlighting the divergence point and how the change propagated downstream.

## 11. Folder structure and build stages

```
blackbox/
├── data/            # SQLite DB, policy text files, generated tasks
├── agent/           # agent loop, tools, prompts, llm_call()
├── tracing/         # tracer, trace storage
├── faults/          # fault injector
├── checker/         # correct_decision + success checker (+ unit tests)
├── runs/            # generated labeled traces
├── model/           # features, baselines, training, explanations
├── replay/          # checkpoints, cache, counterfactual runner, diff
├── app/             # FastAPI + Streamlit UI
├── eval/            # metrics, plots, results table
└── PROJECT_SPEC.md
```

| Stage | Goal | Acceptance check |
|---|---|---|
| 1 | DB, policies, `correct_decision` (with unit tests), task generator | Print 20 tasks with correct expected decisions; tests pass |
| 2 | Agent loop with the 5 tools | Agent solves ~70%+ of clean tasks |
| 3 | Tracer writing the full schema | Every run appears in storage with all fields |
| 4 | Fault injector and bulk run generation | 1,000+ labeled runs including clean and benign |
| 5 | Baselines, then diagnosis model(s) | Learned model beats "blame last tool call" on top-1 accuracy |
| 6 | Replay engine, counterfactual runner, trace diff | A fix at the culprit step flips a failed run to success, with reuse stats logged |
| 7 | Streamlit UI | Timeline, flagged step with evidence and confidence, replay button, counterfactual editor, diff view |
| 8 | Full evaluation incl. held-out faults and held-out agent | Results table and plots ready for slides |

Keep a rough, runnable UI available as early as possible so there is always something demoable.

## 12. If time runs short, cut in this order

1. Drop the second (SQL) agent; use held-out fault types for the generalization story.
2. Drop the sequence model; keep the step-level classifier plus baselines.
3. Use keyword policy lookup instead of embedding retrieval.
4. Reduce to 3 request types' worth of tasks, fewer fault types, and fewer runs (but keep at least a few hundred).

**Never cut:** fault-injected labeled data, at least one baseline plus one trained model, checkpointed replay with cache, one working counterfactual, and an evaluation table.

## 13. Bonus ideas (only after the core works)

- Side-effect-safe replay indicator (already in core, polish it).
- Auto-labeling natural failures: culprit = earliest step whose patch flips the run to success.
- Root-cause vs. symptom chain visualization.
- Failure clustering dashboard (share of failures by root cause).
- Fix-then-regression-test: apply a fix to 50 similar failed runs, report fix rate and any new breakage.
- Confidence calibration plot and abstention.
- Cost savings metric (tokens and money saved by checkpointed replay).
- Evaluate on a small slice of an external agent-failure benchmark (verify the dataset's contents and license first).

## 14. Demo story (use for slides and the live demo)

1. Customer says: "My order #4821 arrived damaged. I want a refund."
2. An injected fault makes `check_policy` return the standard returns policy instead of the damaged-goods policy. No error is thrown.
3. The agent approves a refund without requesting a photo. Every step "succeeded", but the outcome violates policy.
4. Black Box flags the `check_policy` step (not the `take_action` step where damage occurred) and shows evidence.
5. Replay from the checkpoint after `get_order`, reusing earlier steps from cache. `take_action` is stubbed.
6. Counterfactual: patch in the correct damaged-goods policy. The agent now requests a photo and the run succeeds.
7. Trace diff shows divergence at the policy step and propagation to the decision.
8. Show the evaluation table: baselines vs. trained model, seen vs. unseen fault types.

## 15. Instructions for Claude Code

- Work stage by stage. After each stage, run its acceptance check and tell the user the result before moving on.
- Keep everything deterministic where possible: fixed seeds, fixed "today" date, cached LLM and tool outputs.
- Put the LLM behind a single `llm_call()` function so the provider can be swapped.
- Write unit tests for `correct_decision` and the success checker first; every other label depends on them.
- Never run generated or agent-written code outside a sandbox if the SQL or coding variants are added.
- Keep code simple and commented, since the user is new to ML; explain what each ML step does.
- Do not invent benchmark numbers or results. All reported metrics must come from actual runs.
- Ask the user for the open decisions in Section 4 (LLM provider access, team size, deadline) before stage 2 if they are still unknown.
