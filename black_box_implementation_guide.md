# Black Box: A Flight Recorder for AI Agents — Implementation Guide

A concrete stack mapped to the 8 build steps. If you want the simplest path that still looks strong, jump to **Recommended minimal stack** at the end.

## Build steps (overview)

1. Build one or two small agents (for example, a tool-using QA or data-processing agent).
2. Add a tracing layer that logs every step to structured storage.
3. Write a fault injector and generate a few hundred or thousand labeled runs.
4. Train the diagnosis model and compare it against a baseline.
5. Build the replay engine with checkpoints.
6. Add a counterfactual runner and a trace diff view.
7. Build a simple UI that walks through the trace, the flagged step, the evidence, the replay, and the comparison.
8. Run evaluation on seen and unseen failure types and present the numbers.

---

## Language and general setup

**Python** for everything: agents, tracing, ML, and backend. Use a virtual environment (`venv` or `uv`), Git/GitHub, and **Docker** later if you want a reproducible demo.

---

## Step 1: Building the agents

**LLM provider (pick one):**
- **Gemini API via Google AI Studio.** It has a free tier, which suits a GDG event, and it supports function/tool calling.
- **Groq or OpenRouter** for fast, cheap inference on open models.
- **Ollama** to run a small model locally (Llama, Qwen). This avoids rate limits when you generate thousands of runs, which matters a lot here.

**Agent framework (two reasonable options):**
- **LangGraph** is the pick if you want replay quickly. It has built-in checkpointers (SQLite or Postgres), lets you list a run's checkpoint history, edit state at a checkpoint, and resume from there. That is most of your replay and counterfactual engine for free.
- **A plain Python loop** (think, call tool, observe, repeat) gives you full control. The cost is that you write the checkpointing yourself, but it's not hard because the state is just a JSON object (messages, tool results, scratchpad).

**Tasks for the agent.** Choose tasks with automatically checkable answers, otherwise you can't label runs as success or fail:
- Math or multi-step reasoning (GSM8K-style) with a calculator tool
- QA over a small document set using retrieval (**ChromaDB** or **FAISS** plus **sentence-transformers** embeddings)
- Data questions answered with SQL against a **SQLite** database, which is deterministic and easy to verify

Two different agent types (say, a retrieval QA agent and a SQL agent) is enough to show generalization.

---

## Step 2: Tracing layer

Write your own thin wrapper rather than adopting a heavy platform. Every LLM call and tool call goes through a function that logs a structured record:

`run_id, step_idx, type, input, output, latency, tokens, state_snapshot`

- **Storage:** SQLite for a hackathon, or Postgres if you want to look serious. Export to **Parquet** or JSONL for training.
- **Reference tools** to borrow ideas from (optional): OpenTelemetry, Langfuse, Arize Phoenix. You can use one as a viewer, but your own schema makes feature engineering easier.

---

## Step 3: Fault injector and dataset generation

Build this as **middleware** around your tools and LLM calls. It intercepts a call at step k and applies a fault:
- Corrupt a tool output (swap a number, truncate, return an error)
- Wrong tool argument
- Irrelevant or poisoned retrieved document
- Hallucinated or altered intermediate result
- Wrong plan or skipped step

Log `fault_type` and `fault_step` as ground-truth labels. Run the agents over many tasks with random faults plus some fault-free runs, in parallel using `asyncio` or `concurrent.futures`. Store everything with labels.

Include a mix: runs where the fault changes the outcome (true failures) and runs where it doesn't (benign), because that distinction is part of the real problem.

---

## Step 4: Diagnosis model and baseline

**Libraries:**
- **PyTorch** plus **Hugging Face Transformers** for the main model
- **sentence-transformers** to embed step text
- **scikit-learn** and **XGBoost/LightGBM** for baselines
- **PyTorch Geometric** only if you want a graph model (optional, extra work)

**Model options, easiest to hardest:**
1. **Step-level classifier:** embed each step plus features (tool error flag, output length, similarity to the query, difference from successful runs at the same position), then train XGBoost or an MLP to score "is this the culprit".
2. **Sequence model:** a small transformer or BiLSTM over the step embeddings of the whole run, with a per-step output head. This is a good main model because it sees context across steps.
3. **Fine-tuned small language model** (e.g. DistilBERT-size) on serialized traces. Stronger but needs GPU time.

**Baselines (required):** "blame the last tool call", "blame the first tool error", and random. Show your model beats them.

**Compute:** **Google Colab** or **Kaggle notebooks** (free GPUs) are enough. Track experiments with **Weights & Biases** or **MLflow**.

**Explanation:** use attention weights, or a simpler approach like per-step feature contributions (**SHAP** for the tree model), and show the top evidence snippets from the trace. Comparing the flagged step to the same step in successful runs also makes a good explanation.

---

## Step 5: Replay engine with checkpoints

- If you use LangGraph, use its checkpointer and time-travel features.
- If custom, save the full agent state after every step (`state_k` as JSON). Resuming from step k means loading `state_k` and continuing the loop.
- **Handle nondeterminism** with a **record-and-replay cache**: key each LLM and tool call by a hash of its input, and serve cached outputs for steps before the checkpoint. Use low temperature for new calls. Log "steps re-executed vs. steps reused" for your efficiency metric.

---

## Step 6: Counterfactual runner and trace diff

- **Counterfactual runner:** load the checkpoint before the suspected step, patch its output or input (original tool output replaced with the correct value, or a corrected argument), resume, and record whether the final answer is now correct.
- You can also automate the patch: ask an LLM to propose a fix for the flagged step, then test it.
- **Trace diff:** Python's `difflib` or **DeepDiff** for structural comparison of two runs. Highlight where they diverge and how the change propagated downstream.

---

## Step 7: UI

- **Streamlit** is the fastest option. It's pure Python and good enough for a trace timeline, a flagged-step highlight, and side-by-side diffs.
- **FastAPI + React** (with **React Flow** for execution-graph visualization) looks more polished but takes much longer. Only do this if you have a frontend teammate.
- Use **Plotly** for metric charts and **Graphviz** for a simple execution graph in Streamlit.

The UI should have these views:
- Trace timeline
- Flagged step with its confidence and evidence
- "Replay from here" button
- Counterfactual editor
- Diff view

---

## Step 8: Evaluation

Tools: **pandas**, **scikit-learn metrics**, and **matplotlib/Plotly**. Report:
- Top-1 and top-3 step localization accuracy
- Performance on **held-out fault types** (train on, say, 4 fault types, test on the 5th, and rotate)
- Performance on a held-out agent or task if you built two
- Counterfactual fix success rate
- Replay savings (steps reused vs. re-run)
- Comparison against baselines

---

## Suggested architecture

```
Tasks → Agent (LangGraph or custom loop)
           ↓ wrapped by
   Fault injector + Tracer  →  SQLite/Parquet (labeled runs)
                                      ↓
                          Feature/embedding pipeline
                                      ↓
                     Diagnosis model (+ baselines) → explanations
                                      ↓
   FastAPI backend ← Replay engine (checkpoints + cache) ← Counterfactual runner
                                      ↓
                             Streamlit UI
```

---

## Recommended minimal stack

- **Python + Gemini API (or Ollama for bulk runs)**
- **Custom agent loop or LangGraph**, with calculator, SQLite, and Chroma tools
- **SQLite + JSONL/Parquet** for traces
- **sentence-transformers + PyTorch + XGBoost** for the models
- **Colab/Kaggle** for training, **W&B** for tracking
- **FastAPI + Streamlit** for the app

---

## Order of work

Build the agent, tracer, and fault injector first, since everything depends on having labeled data. Then do the baseline and model while building replay in parallel. Leave the UI for last, but keep a rough version running early so you always have something demoable.
