# Sanitization Report

**Source:** `C:\Users\anand\Downloads\v8_reports_bot`
**Destination:** `C:\Users\anand\Downloads\_clean_uploads\v8_reports_bot`

## Summary

- 69 files copied
- 57 files deleted
- 8 files had patterns scrubbed
- 0 files kept with suspicious names (manual review recommended)

## Deleted files

- `.env` — exact-name match in DELETE_EXACT_NAMES (.env)
- `IDRE_Report_Audit_Findings.md` — glob match *Audit_Findings*.md
- `IMPLEMENTATION_PLAN.md` — glob match *IMPLEMENTATION_PLAN*.md
- `__pycache__\harness_entrypoint.cpython-311.pyc` — inside excluded dir __pycache__
- `agents\__pycache__\__init__.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\ambiguity_scorer.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\clarification_agent.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\context_loader.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\debugger_agent.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\executor.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\feedback_injector.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\output_formatter.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\platform_context_agent.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\post_processor.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\response_formatter.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\schema_mapper.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\schema_verifier.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\sql_validator.cpython-311.pyc` — inside excluded dir agents
- `agents\__pycache__\sql_writer.cpython-311.pyc` — inside excluded dir agents
- `cdk_deploy\cdk.context.json` — exact-name match in DELETE_EXACT_NAMES (cdk.context.json)
- `config\__pycache__\__init__.cpython-311.pyc` — inside excluded dir config
- `config\__pycache__\settings.cpython-311.pyc` — inside excluded dir config
- `core\__pycache__\__init__.cpython-311.pyc` — inside excluded dir core
- `core\__pycache__\orchestrator.cpython-311.pyc` — inside excluded dir core
- `data\ambiguity_calibration.jsonl` — exact-name match in DELETE_EXACT_NAMES (ambiguity_calibration.jsonl)
- `data\anomaly_window.json` — exact-name match in DELETE_EXACT_NAMES (anomaly_window.json)
- `data\audit_log.jsonl` — exact-name match in DELETE_EXACT_NAMES (audit_log.jsonl)
- `data\chroma_db\0e52e61d-369c-45ab-9b5b-8df849561c4e\data_level0.bin` — inside excluded dir data
- `data\chroma_db\0e52e61d-369c-45ab-9b5b-8df849561c4e\header.bin` — inside excluded dir data
- `data\chroma_db\0e52e61d-369c-45ab-9b5b-8df849561c4e\length.bin` — inside excluded dir data
- `data\chroma_db\0e52e61d-369c-45ab-9b5b-8df849561c4e\link_lists.bin` — inside excluded dir data
- `data\chroma_db\chroma.sqlite3` — inside excluded dir data
- `data\clarification_history.json` — exact-name match in DELETE_EXACT_NAMES (clarification_history.json)
- `data\error_knowledge_base.json` — exact-name match in DELETE_EXACT_NAMES (error_knowledge_base.json)
- `data\feedback_log.jsonl` — exact-name match in DELETE_EXACT_NAMES (feedback_log.jsonl)
- `data\query_frequency.json` — exact-name match in DELETE_EXACT_NAMES (query_frequency.json)
- `data\saved_queries.json` — exact-name match in DELETE_EXACT_NAMES (saved_queries.json)
- `data\schema_snapshot.json` — exact-name match in DELETE_EXACT_NAMES (schema_snapshot.json)
- `db\__pycache__\__init__.cpython-311.pyc` — inside excluded dir db
- `db\__pycache__\connector.cpython-311.pyc` — inside excluded dir db
- `demo_test.log` — exact-name match in DELETE_EXACT_NAMES (demo_test.log)
- `knowledge\__pycache__\__init__.cpython-311.pyc` — inside excluded dir knowledge
- `knowledge\__pycache__\knowledge_base.cpython-311.pyc` — inside excluded dir knowledge
- `state\__pycache__\__init__.cpython-311.pyc` — inside excluded dir state
- `state\__pycache__\context.cpython-311.pyc` — inside excluded dir state
- `tools\__pycache__\__init__.cpython-311.pyc` — inside excluded dir tools
- `tools\__pycache__\idre_tools.cpython-311.pyc` — inside excluded dir tools
- `utils\__pycache__\__init__.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\audit_analytics.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\audit_writer.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\feedback_analytics.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\feedback_store.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\glossary_matcher.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\join_graph.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\permissions.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\query_cache.cpython-311.pyc` — inside excluded dir utils
- `utils\__pycache__\query_store.cpython-311.pyc` — inside excluded dir utils

## Scrubbed inline


### `DB_ACCESS.md`

- [RDS_ENDPOINT] `idre-prod.cluster-xxx.us-east-1.rds.amazonaws.com`

### `DEMO_GUIDE.md`

- [GEMINI_API_KEY] `AIzaSyDvEqWR6WnYI9plfmxcisuLpWxpyLnB2u4`
- [PERSONAL_PATH_WIN] `C:\Users\anand`
- [ENV_STYLE_SECRET] `DB_PASSWORD=qovmok-7sefpe-vyqPix`

### `generate_doc.py`

- [PERSONAL_PATH_WIN] `C:/Users/anand`

### `README.md`

- [ENV_STYLE_SECRET] `DB_PASSWORD=...`
- [ENV_STYLE_SECRET] `OPENAI_API_KEY=...`

### `schema_catalog.json`

- [RDS_ENDPOINT] `mysql-8-stage-1-cluster.cluster-cc1r7ekdbl8j.us-east-1.rds.amazonaws.com`
- [EMAIL] `christianly.grajales@capitolbridge.com`
- [EMAIL] `edwin.velazquez@capitolbridge.com`
- [EMAIL] `christopher.mactaggart@capitolbridge.com`
- [EMAIL] `lawrence.washington@capitolbridge.com`
- [EMAIL] `anthony.diaz@capitolbridge.com`
- [EMAIL] `leonardo@seedtrustescrow.com`
- [EMAIL] `jesmarie.galloza@capitolbridge.com`
- [EMAIL] `erika.cuevas@capitolbridge.com`
- [EMAIL] `enrique@seedtrustescrow.com`
- [EMAIL] `ariana.candelaria@capitolbridge.com`
- [EMAIL] `amanda.kelly@capitolbridge.com`
- [EMAIL] `garrick.brown@capitolbridge.com`
- [EMAIL] `carlos.ferreris@capitolbridge.com`
- [EMAIL] `robert.howard@capitolbridge.com`
- [EMAIL] `ale.humano@capitolbridge.com`
- [EMAIL] `fernando.acuna@capitolbridge.com`
- [EMAIL] `jorge.bobonis@capitolbridge.com`
- [EMAIL] `Sara.Dixon@capitolbridge.com`
- [EMAIL] `nicole.silvestre@capitolbridge.com`
- [EMAIL] `1@radixhealth.io`
- [EMAIL] `32bjfundnegotiations@32bjfunds.com`
- [EMAIL] `805_ppsi_idr@chs.net`
- [EMAIL] `a.garvin@neurodynamicsinc.org`
- [EMAIL] `a.harris@fam-llc.com`
- [EMAIL] `a.lytle@neurodynamicsinc.org`
- [EMAIL] `aacswoonbilling@aac-md.com`
- [EMAIL] `aansa@idrnsa.com`
- [EMAIL] `aaron.scott@fam-llc.com`
- [EMAIL] `aaron@lmesq.com`
- [EMAIL] `abakar@rightmedicalbilling.com`
- [EMAIL] `abby.o@seedtrustescrow.com`
- [EMAIL] `abdulrazzak.shariff@datamarshall.com`
- [EMAIL] `abeku.paintsil@gpsmdpc.com`
- [EMAIL] `abingtonphysicians@nosurprisebill.com`
- [EMAIL] `abingtonphysiciansnsa@nosurprisebill.com`
- [EMAIL] `abneris.badillo@capitolbridge.com`
- [EMAIL] `abrattole@affinitymedsol.com`
- [EMAIL] `acamarillo@emergentair.org`
- [EMAIL] `accounting@anglehealth.com`
- [EMAIL] `1@radixhealth.io`
- [EMAIL] `32bjfundnegotiations@32bjfunds.com`
- [EMAIL] `805_ppsi_idr@chs.net`
- [EMAIL] `a.garvin@neurodynamicsinc.org`
- [EMAIL] `a.harris@fam-llc.com`
- [EMAIL] `a.lytle@neurodynamicsinc.org`
- [EMAIL] `aacswoonbilling@aac-md.com`
- [EMAIL] `aansa@idrnsa.com`
- [EMAIL] `aaron.scott@fam-llc.com`
- [EMAIL] `aaron@lmesq.com`
- [EMAIL] `abakar@rightmedicalbilling.com`
- [EMAIL] `abby.o@seedtrustescrow.com`
- [EMAIL] `abdulrazzak.shariff@datamarshall.com`
- [EMAIL] `abeku.paintsil@gpsmdpc.com`
- [EMAIL] `abingtonphysicians@nosurprisebill.com`
- [EMAIL] `abingtonphysiciansnsa@nosurprisebill.com`
- [EMAIL] `abneris.badillo@capitolbridge.com`
- [EMAIL] `abrattole@affinitymedsol.com`
- [EMAIL] `acamarillo@emergentair.org`
- [EMAIL] `accounting@anglehealth.com`

### `agents\executor.py`

- [MYSQL_URL_CRED] `mysql+mysqlconnector://{s.db_user}:{s.db_password}@`

### `cdk_deploy\app.py`

- [AWS_ACCOUNT_ID_KWARG] `account="822804284820"`

### `cdk_deploy\stack.py`

- [RDS_ENDPOINT] `mysql-8-stage-1-cluster.cluster-cc1r7ekdbl8j.us-east-1.rds.amazonaws.com`
- [AWS_ARN_ACCOUNT] `arn:aws:secretsmanager:us-east-1:822804284820:`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [PERSONAL_PATH_NIX] `/home/ec2-user`
- [ENV_STYLE_SECRET] `Gemini_API_Key={{gemini}}\\n`
- [ENV_STYLE_SECRET] `DB_PASSWORD={{db_pass}}\\n`
- [ENV_STYLE_SECRET] `APP_PASSWORD={{app_pw}}\\n`

## Next step

```bash
python _github_sanitizer.py scan "C:\Users\anand\Downloads\_clean_uploads\v8_reports_bot" --strict
```

Must return `OK — 0 findings` before any push.
