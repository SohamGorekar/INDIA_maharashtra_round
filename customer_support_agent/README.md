# Durva Shopping — Support Agent

An AI customer support agent for an online store.

A customer signs in, sees their orders, picks the one with a problem, and
describes it in a chat. The agent looks up the order, checks store policy, and
resolves it — approving, refusing, asking for a photo, or escalating to a
manager. The conversation continues across turns, so sending the photo it asked
for gets a real answer rather than a repeat of the question.

### Demo accounts

Password for all four: `User@123`

| Email | Name |
|---|---|
| soham.gorekar@example.com | Soham Chetan Gorekar |
| durva.waykole@example.com | Durva Amol Waykole |
| zeel.girase@example.com | Zeel Yashpalsinh Girase |
| aditya.singh@example.com | Aditya Nirajkumar Singh |

Each has the same 12 orders (at slightly different prices), chosen to cover every
branch of the policy: one not yet shipped, one inside the return window, one over
₹5,000, one exchangeable, one whose replacement size is out of stock, two final
sale, and several at different ages either side of the 30 / 45 / 365-day
boundaries.

Built with **LangGraph + Mistral** (Gemini also supported) behind a **FastAPI**
backend, a **React** front end, and **Supabase Postgres**.

---

## Setup

### 1. Python

All commands below are run from this folder (`customer_support_agent/`).

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt    # Windows
# source .venv/bin/activate && pip install -r requirements.txt  # macOS/Linux
```

### 2. Gemini API key

Open `.env` (already in this folder) and replace the placeholder:

```
GOOGLE_API_KEY=your-key-here
```

Get a free key at <https://aistudio.google.com/apikey>. No quotes, no spaces
around the `=`. The file is gitignored, so the key is never committed.

### 3. The store database

The store runs on **Supabase Postgres**, or on a local SQLite file if you have
not set one up.

**Supabase:** copy the *pooled* connection string (Project Settings → Database →
Connection string → URI, port **6543**) into `.env`:

```
DATABASE_URL=postgresql://postgres.xxxx:PASSWORD@aws-0-REGION.pooler.supabase.com:6543/postgres
```

Then create the tables and fill them:

```bash
.venv/Scripts/python.exe -m support.data.seed
```

**Local instead:** leave `DATABASE_URL` blank (or set `LOCAL_SQLITE=1`) and run

```bash
.venv/Scripts/python.exe -m support.data.seed --local
```

Either way you get 300 orders, 60 customers, stock and payments generated from a
fixed random seed — identical on every machine, every time. Reseeding drops and
recreates everything, which is always safe: the data is generated, never
collected, so there is nothing to preserve.

### 4. Front end

```bash
cd ui && npm install
```

---

## Running it

Two terminals:

```bash
# terminal 1 -- backend, from customer_support_agent/
.venv/Scripts/python.exe -m uvicorn support.api:app --reload --port 8000

# terminal 2 -- frontend, from customer_support_agent/ui/
npm run dev
```

Open <http://localhost:5173>.

Pick one of the generated sample requests (each has a known correct answer, so
the UI grades the agent live) or write your own. **Dry run** is on by default —
the agent's actions are simulated and the database is never modified.

---

## How it works

```
customer request
  → verify_customer → find_order → get_order → get_payment_history
  → check_policy  (+ check_stock if an exchange)
  → DECISION
      ├ DENY / ESCALATE / REQUEST_PHOTO → send_reply
      └ APPROVE → take_action → verify_action → send_reply
```

The agent **chooses its own tools** — the prompt presents the above as the
expected path, not as a rail. The graph loops between the model and the tools
until `send_reply` is called, capped at 15 turns.

### The four decisions

| Decision | When |
|---|---|
| `APPROVE` | Valid request; the action has been taken. |
| `DENY` | Policy does not allow it. |
| `REQUEST_PHOTO` | A damage claim with no photo supplied. |
| `ESCALATE` | Valid, but the refund exceeds Rs. 5,000. |

### The nine tools

`verify_customer`, `find_order`, `get_order`, `get_payment_history`,
`check_policy`, `check_stock`, `take_action`, `verify_action`, `send_reply`.

`take_action` is the only one that writes, and it honours the dry-run flag.

---

## Layout

```
customer_support_agent/
├── .env           your Gemini key goes here
├── requirements.txt
├── support/
│   ├── data/      db connection, schema.sql, seed, 8 policy texts, requests
│   ├── rules/     correct_decision() -- the policy oracle, plus its tests
│   ├── agent/     Gemini wrapper + cache, the 9 tools, the LangGraph graph
│   └── api.py     FastAPI backend
└── ui/            React front end (Vite)
```

This folder is self-contained: its own virtualenv, its own `.env`, its own
dependencies. Nothing outside it is needed to run the agent.

### `rules/decision.py` is the answer key

`correct_decision()` is the store's policy as a pure function. **The agent never
calls it.** It exists so accuracy can be measured: it says what the answer should
have been, which is what the eval script and the UI's grading banner compare
against.

---

## Checking it works

```bash
.venv/Scripts/python.exe -m pytest support/ -q      # 49 tests, no API key needed
.venv/Scripts/python.exe -m support.agent.run --request-id 1 --verbose
.venv/Scripts/python.exe -m support.agent.eval --n 50
```

`eval` prints overall accuracy, a per-decision breakdown, what the agent answered
instead when it was wrong, and process checks (did it consult policy before
acting?).

---

## Notes

- **Rate limits.** The Gemini free tier allows roughly 10 requests/minute. The
  agent backs off and retries automatically, so a 50-request eval takes several
  minutes rather than failing.
- **Response cache.** Identical requests are served from a local SQLite cache, so
  re-running something while debugging costs no quota. Clear it from the UI or
  with `DELETE /api/cache`.
- **Fixed dates.** The store has a fixed "today" (`support/data/db.py`), so an
  order that is 25 days old stays 25 days old. Without this, accuracy numbers
  would drift as real time passed.
