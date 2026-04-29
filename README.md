# IDRE Reports Bot v2

AI-powered multi-agent chatbot for the IDRE platform. Staff query the dispute database in plain English; the system maps intent → SQL → executes → formats results.

## Project Structure

```
reports_bot2/
├── .env                        # DB credentials (never commit)
├── global-bundle.pem           # AWS RDS SSL certificate
├── requirements.txt            # Python dependencies
├── analyze_db.py               # DB schema analysis script
├── schema_catalog.json         # Generated: 44 tables, 83 FK relationships
│
├── state/
│   └── context.py              # StateContext Pydantic model (flows through all agents)
│
├── agents/
│   ├── clarification_agent.py  # Ambiguity scorer + follow-up questions
│   ├── schema_mapper.py        # Vector search → relevant tables
│   ├── sql_writer.py           # NL → SQL generation
│   ├── sql_validator.py        # Deterministic safety gate
│   ├── executor.py             # DB query runner
│   ├── response_formatter.py   # Chart/table/prose selector
│   └── debugger_agent.py       # Error classifier + retry context
│
├── config/
│   ├── metric_cards.json       # 18 core metrics with SQL templates
│   ├── business_glossary.json  # Business term → SQL filter mappings
│   └── access_control.json     # Role → table permission mappings
│
├── core/
│   ├── orchestrator.py         # LangGraph pipeline + retry loop
│   ├── db_connector.py         # SQLAlchemy read-only connection
│   └── embeddings.py           # Schema embedding + ChromaDB indexing
│
├── app.py                      # Streamlit chat UI (Phase 1)
└── venv/                       # Python virtual environment
```

## Architecture: Multi-Agent Pipeline

```
User NL Query
  ↓
[Context Loader] — loads permissions + session history + business glossary
  ↓
[1. Clarification Agent] — ambiguity scorer; asks 1 follow-up if needed
  ↓
[2. Schema Mapper] — vector search → filter by permissions → pick 5-8 tables
  ↓
[3. SQL Writer] — generates SQL + self-confidence score
  ↓
[4. SQL Validator] — DDL/DML block, column existence, permission re-check (DETERMINISTIC)
  ↓
[5. Executor] — read-only DB, 30s timeout, 10K row cap
  ↓  (on error → [Debugger] → retry SQL Writer, max 3×)
[6. Response Formatter] — auto chart + query explainer + proactive suggestions
  ↓
[Audit Trail] — async log
  ↓
User
```

## Personas
| Code | Name | Triggered by |
|---|---|---|
| ES | Executive Summarizer | "total", "summary", "how many" |
| FA | Financial Auditor | "revenue", "unpaid", "fee", "payment" |
| OM | Operations Manager | "overdue", "stuck", "pending" |
| CEA | Clinical/Eligibility Analyst | "ineligible", "failed", "eligibility" |
| DQD | Data Quality Debugger | "why don't these match", "discrepancy" |

## Database
- **AWS RDS MySQL 8** — `idre_stage`
- **44 tables**, ~1.83M rows, ~3.7GB
- **83 FK relationships** mapped in `schema_catalog.json`
- Key tables: `case` (50 cols), `payment` (32 cols), `case_action` (499K rows)

## Build Phases
- **Phase 1 (MVP):** Core pipeline, Streamlit UI, table-level access control
- **Phase 2:** Business Glossary, Debugger Agent, cross-session memory, Next.js UI
- **Phase 3:** Production hardening, caching, fine-tuning, audit analytics

## Setup

```bash
# Activate virtual environment
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# Generate/refresh schema catalog
python analyze_db.py

# Run the chatbot
streamlit run app.py
```

## Environment Variables (.env)
```
DB_HOST=...
DB_PORT=3306
DB_NAME=idre_stage
DB_USER=...
DB_PASSWORD=<redacted>
DB_SSL_CA=./global-bundle.pem
OPENAI_API_KEY=<redacted>   # or ANTHROPIC_API_KEY
```
