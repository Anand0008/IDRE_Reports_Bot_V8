# IDRE Reports Bot — Demo Guide

## Quick Start
```bash
cd <HOME>\Downloads\reports_bot2
source venv/Scripts/activate
streamlit run app.py
```
Visit **http://localhost:8501** in your browser.

---

## What's Been Built (MVP Complete)

### ✅ Core Pipeline (8 agents, fully wired)
- **Context Loader** — Resolves pronouns & references using conversation history
- **Ambiguity Scorer** — Flags vague queries (date range, org scope, metric type)
- **Clarification Agent** — Asks follow-ups for high-ambiguity queries
- **Schema Mapper** — Vector search (all-MiniLM-L6-v2) → picks 5-8 relevant tables
- **SQL Writer** — Gemini 3.1 Pro generates SELECT SQL with ASSUMPTIONS block
- **SQL Validator** — Blocks DDL/DML, validates table names
- **Executor** — Runs on live MySQL (43,994 cases) with 30s timeout, 10K row cap
- **Response Formatter** — Markdown table/count + assumptions callout + SQL display

### ✅ Session Features
- **Conversation History** — All queries tracked; used for pronoun resolution
- **Saved Queries** — Save queries by name, run them later (e.g. "save as open_cases" → "run open_cases")
- **Agent Trace Timeline** — Visual pipeline execution panel in sidebar

### ✅ Database
- **44 tables**, 83 FK relationships, ~1.83M rows total
- **Read-only MySQL user** on AWS RDS (`app_idre_rw`)
- **Schema catalog** with join paths pre-computed

---

## Demo Script (Step-by-Step)

### Step 1: Basic Query (3-5 seconds)
**Type:** "How many cases are currently open?"

**What happens:**
1. Context Loader loads history (empty on first query)
2. Ambiguity Scorer scores 0.2 (low — date and org scope are clear from context)
3. Schema Mapper picks `case` table
4. SQL Writer generates: `SELECT COUNT(*) FROM case`
5. Executor runs it → ~43,994 rows
6. Response Formatter displays: "**total_disputes:** 43,994"

**Trace shows:** 8 green checkmarks (all agents succeeded)

---

### Step 2: Session Memory — Pronoun Resolution (3 seconds)
**Previous context:** "How many cases are currently open?"

**Type:** "Show me their statuses"

**What happens:**
1. Context Loader detects "their" → resolves to "cases" from previous query
2. `resolved_query` → "Show me statuses of cases that are currently open"
3. Schema Mapper picks `case` + `case_action` tables
4. SQL Writer generates JOIN + GROUP BY to show status distribution
5. Response Formatter shows a markdown table with status counts

**Demo value:** Proves conversation history is live & working

---

### Step 3: Save & Run Query (5 seconds)
**Type:** "Save this as open_cases"

**What happens:**
1. SQL Writer detects SAVE intent in input
2. Stores query in `data/saved_queries.json` with name `open_cases`
3. Sidebar updates with new saved query button

**Then type:** "Run open_cases"

**What happens:**
1. App detects RUN intent
2. Retrieves stored SQL from query store
3. Executor runs it immediately (skips all agents)
4. Same results as Step 2, but instant

**Demo value:** Shows query persistence & reuse

---

### Step 4: Assumptions Annotation (5 seconds)
**Type:** "Show me payment amounts by case status for disputes filed in Q1 2024"

**What happens:**
1. Ambiguity Scorer flags: **date range** (Q1 ambiguous), **metric type** (payment amount — multiple interpretations)
2. Score = 0.65 (medium-high)
3. Clarification Agent asks: "By 'payment amount' do you mean: (A) total amount paid so far, (B) amount pending, or (C) amount requested?"
4. User responds: "(A) total paid"
5. SQL Writer regenerates with assumptions:
   ```
   ASSUMPTIONS:
   - "Q1 2024" interpreted as Jan 1 - Mar 31, 2024
   - "payment amount" = sum of payment amounts where status = COMPLETED
   - "by case status" = GROUP BY case.status
   ```
6. Formatter shows assumptions in a **yellow callout box** above results

**Demo value:** Shows clarification UX + assumption transparency

---

### Step 5: Agent Trace Timeline (2 seconds)
**Look at sidebar after any query**

**Shows:**
- Each agent's execution with icon + status
- Color-coded: green (success), yellow (skipped), red (error)
- Step names: "Context Loader" → "Schema Mapper" → "SQL Writer" → etc.

**Click "Show Details"** to see:
- Input to that agent
- Output from that agent
- Tables/SQL snippets

---

## Technical Highlights

### Why Gemini 3.1 Pro?
- Produces cleaner SQL with fewer hallucinated columns
- Better at understanding complex joins via schema context
- Faster token throughput than GPT-4o

### Why all-MiniLM-L6-v2?
- 384-dim embeddings, very fast inference on CPU
- Cached in `data/chroma_db/` after first run
- No API calls (local), works offline

### Why LangGraph?
- Conditional routing (clarification → yes/no → END or continue)
- Retry loop: if SQL execution fails, SQL Writer runs again (max 2 retries)
- Explicit state machine (more predictable than agents with tool calling)

---

## What's Coming Next (Next 3-5 Days)

### Epic 4 — Business Glossary
- Terms like "dispute," "arbitration," "eligible" mapped to SQL
- Agents use glossary to disambiguate domain language
- Stored in `data/business_glossary.json`

### Epic 5 — Debugger Agent
- On SQL execution error, debugger analyzes & suggests fixes
- E.g., "Column `case_status` doesn't exist, did you mean `status`?"
- Feeds back to SQL Writer for regeneration (counts toward retry budget)

### Epic 6 — Role-Based Permissions
- 5 personas (ES, FA, OM, CEA, DQD) with different table access
- Column-level ACL (Financial Auditor sees dollar amounts, others see counts only)
- Validator blocks queries that violate user's role

### Phase 2 — Frontend Upgrade
- Next.js + Tailwind (replaces Streamlit)
- Multi-workspace support (different teams, saved dashboards)
- Query result caching + export to CSV/PDF

### Phase 3 — Production Hardening
- Audit trail logging (who ran what, when, results count)
- Cost controls (max query complexity, execution time warnings)
- Model fine-tuning on IDRE's 18 metrics

---

## Troubleshooting

### Streamlit won't start
```bash
# Kill old process
pkill -f streamlit

# Reactivate venv and restart
source venv/Scripts/activate
streamlit run app.py
```

### Database connection timeout
- Check VPN is on (RDS is in private AWS region)
- Verify `.env` has correct password: `DB_PASSWORD=<redacted>`
- Test: `python -c "from db.connector import get_engine; get_engine().connect()"`

### ChromaDB won't load
- First run regenerates embeddings (takes ~10 seconds)
- If stuck, delete `data/chroma_db/` and restart

### Gemini API key invalid
- Verify `.env`: `Gemini_API_Key=<GEMINI_API_KEY>`
- Check rate limits haven't been exceeded (100 req/min)

---

## Key Files to Know

| File | Purpose |
|---|---|
| `app.py` | Streamlit UI + chat loop |
| `core/orchestrator.py` | LangGraph pipeline definition |
| `agents/` | 8 agent node functions |
| `state/context.py` | GraphState TypedDict (all pipeline data) |
| `data/chroma_db/` | ChromaDB persisted embeddings |
| `data/saved_queries.json` | User-saved queries |
| `schema_catalog.json` | Full DB schema (44 tables, 83 FKs) |

---

## Questions?

- See `README.md` for architecture overview
- See `docs/` for feature-level documentation
- See `IMPLEMENTATION_PLAN.md` for full Epic/Story mapping
