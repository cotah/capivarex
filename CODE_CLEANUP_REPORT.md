# CODE_CLEANUP_REPORT

Generated on: 2026-02-13  
Scope: read-only static analysis of `corrigido/` (no code changes applied)  
Primary tools: `ruff`, `vulture`, `jscpd`, `rg`, custom read-only AST/import scanners

## 1) Executive Summary

| Category | Count | Notes |
|---|---:|---|
| Unused imports | 39 symbols | `ruff` `F401` across 16 files |
| Dead code (functions/classes) | 0 high-confidence + 21 verify candidates | `vulture` >=80 had no function/class hits; candidates from `vulture` 60 + reference search |
| Possibly unused dependencies | 17 | Requirements with zero direct import hits in `*.py` |
| Large commented-out blocks | 0 | No `#` blocks >=20 lines; no non-docstring triple-quoted blocks >=8 lines |
| Suspected test/debug/temp files | 8 | Filename heuristics + import graph hints |
| Duplicate logic | 53 clone blocks detected | `jscpd` (`--format python --min-lines 6 --min-tokens 30`) |
| `.env.example` vars not referenced in code | 2 | Exact key string not found in `*.py` |

Estimated impact (estimate only):
- Import cleanup: about 39 lines removable with low behavioral risk (except protected zones).
- Dead-code cleanup candidates: about 200-450 LoC potentially removable/refactorable after runtime verification.
- Dependency cleanup: up to 17 packages to review; likely smaller final removal set after validation.
- Duplication refactor: `jscpd` reports 597 duplicated lines (6.89%) and 5020 duplicated tokens (8.0%).

## 2) Findings Tables

### A) Unused imports by file

| File path | Line numbers | Item name(s) | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| `agents/calendar_agent.py` | 6 | `typing.List` | `ruff F401` | 🟡 VERIFY | In `agents/` (protected/dynamic patterns possible). |
| `agents/voice_agent.py` | 6 | `typing.Optional` | `ruff F401` | 🟡 VERIFY | In `agents/` (protected/dynamic patterns possible). |
| `api/routes/chat.py` | 17 | `models.schemas.ChatMessage` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused import. Route handlers remain protected separately. |
| `autofix/core.py` | 17, 26 | `os`, `typing.Dict`, `typing.List` | `ruff F401` | 🔴 DO NOT REMOVE | `autofix/` is protected by requirement. |
| `bot.py` | 41, 45 | `sys`, `datetime.timedelta` | `ruff F401` | 🟡 VERIFY | Entry script; verify no runtime reflection/string usage before cleanup. |
| `services/car_service.py` | 8 | `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused import. |
| `services/code_executor.py` | 7, 10, 14 | `os`, `tempfile`, `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused imports. |
| `services/elevenlabs_service.py` | 7 | `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused import. |
| `services/file_manager.py` | 7, 10 | `os`, `typing.List`, `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused imports. |
| `services/finance_service.py` | 7 | `typing.Optional`, `typing.List` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused imports. |
| `services/image_service.py` | 10 | `typing.Dict`, `typing.Any` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused imports. |
| `services/weather_service.py` | 7 | `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused import. |
| `services/whisper_service.py` | 6 | `typing.Optional` | `ruff F401` | 🟢 SAFE REMOVE | Standard unused import. |
| `telegram_bot.py` | 16, 17, 38-45, 86-87, 89-90 | `asyncio`, `datetime.timezone`, multiple `autofix.*` symbols | `ruff F401` | 🟡 VERIFY | Imports touch protected `autofix` integration; verify runtime hooks before removal. |
| `telegram_voice_handler.py` | 14-15 | `elevenlabs_service`, `whisper_service` | `ruff F401` | 🟡 VERIFY | File appears operational but may be integration-staged; verify wiring. |
| `test_car_integration.py` | 4 | `os` | `ruff F401` | 🟢 SAFE REMOVE | Test-only file import. |

Additional quality issue observed during import scan:
- `api/routes/chat.py:224`: `ruff F821` undefined name `car_service` (not an unused import; potential runtime error path).

### B) Defined-but-not-referenced functions/classes

High-confidence result (`vulture --min-confidence 80`):
- No functions/classes flagged at >=80 confidence.

Verify-level candidates (`vulture` 60 + reference search evidence):

| File path | Line numbers | Item name | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| `bot.py` | 270 | `get_context_for_webapp` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Might be planned entry helper or external tooling hook. |
| `bot.py` | 1074 | `smart_chat_router` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Could be legacy routing path. |
| `bot.py` | 1637 | `apply_actions` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Could be intended for future action executor integration. |
| `telegram_voice_handler.py` | 22 | `handle_voice` | `vulture` 60%; only docs references found | 🟡 VERIFY | Referenced in `VOICE_INTEGRATION_INSTRUCTIONS.md`, not in runtime code. |
| `telegram_voice_handler.py` | 85 | `handle_audio` | `vulture` 60%; only docs references found | 🟡 VERIFY | Integration appears documented but not wired in code. |
| `telegram_voice_handler.py` | 145 | `cmd_falar` | `vulture` 60%; only docs references found | 🟡 VERIFY | Same as above. |
| `telegram_voice_handler.py` | 211 | `cmd_vozes` | `vulture` 60%; only docs references found | 🟡 VERIFY | Same as above. |
| `telegram_voice_handler.py` | 234 | `cmd_falar_com` | `vulture` 60%; only docs references found | 🟡 VERIFY | Same as above. |
| `services/google_calendar_service.py` | 164 | `create_event` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | May be API surface reserved for future routes/agents. |
| `services/google_calendar_service.py` | 214 | `update_event` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Same pattern as above. |
| `services/google_calendar_service.py` | 269 | `delete_event` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Same pattern as above. |
| `services/redis_service.py` | 305 | `save_session` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Could be runtime-only via future state persistence. |
| `services/redis_service.py` | 332 | `get_session` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Same pattern as above. |
| `services/redis_service.py` | 351 | `delete_session` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Same pattern as above. |
| `services/vehicle_db_service.py` | 168 | `delete_vehicle` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Could be future lifecycle operation. |
| `services/vehicle_db_service.py` | 208 | `update_last_synced` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | Could be planned sync path. |
| `services/whisper_service.py` | 145 | `translate_audio` | `vulture` 60%; no code callsites found by `rg` | 🟡 VERIFY | May be optional endpoint feature. |
| `agents/calendar_agent.py` | 185 | `can_handle` | `vulture` 60%; no explicit callsite found | 🟡 VERIFY | `agents/` protected; dynamic orchestrator dispatch likely. |
| `agents/traffic_agent.py` | 73 | `check_traffic_for_event` | `vulture` 60%; no explicit callsite found | 🟡 VERIFY | `agents/` protected/dynamic invocation risk. |
| `agents/voice_agent.py` | 130 | `get_supported_languages` | `vulture` 60%; no explicit callsite found | 🟡 VERIFY | `agents/` protected/dynamic invocation risk. |
| `autofix/core.py` | 181, 735, 747 | `_extract_top_frame`, `_has_active_tickets`, `_has_recent_errors` | `vulture` 60%; low-confidence dead-code candidates | 🔴 DO NOT REMOVE | `autofix/` is protected by requirement. |

### C) `requirements.txt` dependencies not imported anywhere

Method: parsed `requirements.txt`; scanned `*.py` for `import X` / `from X import ...` using mapped module names.

| Dependency (`requirements.txt`) | Line | Import module searched | Evidence | Risk classification | Notes |
|---|---:|---|---|---|---|
| `uvicorn==0.40.0` | 3 | `uvicorn` | 0 import hits in `*.py` | 🔴 DO NOT REMOVE | Common CLI/runtime server dependency. |
| `python-multipart==0.0.22` | 4 | `multipart` | 0 import hits in `*.py` | 🔴 DO NOT REMOVE | FastAPI form parsing dependency; often implicit. |
| `psycopg2-binary==2.9.11` | 10 | `psycopg2` | 0 import hits in `*.py` | 🟡 VERIFY | Might be legacy DB adapter; not directly imported. |
| `redis==7.1.1` | 11 | `redis` | 0 import hits in `*.py` | 🔴 DO NOT REMOVE | Marked core runtime dependency per constraints. |
| `upstash-redis==1.6.0` | 12 | `upstash_redis` | 0 import hits in `*.py` | 🟡 VERIFY | Could be optional/provider fallback. |
| `PyJWT==2.11.0` | 18 | `jwt` | 0 import hits in `*.py` | 🟡 VERIFY | Auth currently imports `jose.jwt`; package may be redundant. |
| `elevenlabs==2.35.0` | 24 | `elevenlabs` | 0 import hits in `*.py` | 🟡 VERIFY | Service uses direct HTTP via `requests`, not SDK imports. |
| `google-auth-oauthlib==1.2.4` | 29 | `google_auth_oauthlib` | 0 import hits in `*.py` | 🟡 VERIFY | May be optional for OAuth flow not currently coded. |
| `google-auth-httplib2==0.3.0` | 30 | `google_auth_httplib2` | 0 import hits in `*.py` | 🟡 VERIFY | Could be transitive/optional for Google API integrations. |
| `beautifulsoup4==4.14.3` | 38 | `bs4` | 0 import hits in `*.py` | 🟡 VERIFY | Likely unused unless external scripts/plugins rely on it. |
| `pandas==3.0.0` | 41 | `pandas` | 0 import hits in `*.py` | 🟡 VERIFY | No direct data-processing imports found. |
| `numpy==2.4.2` | 42 | `numpy` | 0 import hits in `*.py` | 🟡 VERIFY | No direct numerical imports found. |
| `email-validator` | 45 | `email_validator` | 0 import hits in `*.py` | 🟡 VERIFY | Could be implicit via Pydantic `EmailStr` style usage. |
| `python-dateutil==2.9.0.post0` | 51 | `dateutil` | 0 import hits in `*.py` | 🟡 VERIFY | May be transitive utility; no direct imports found. |
| `pytz==2025.2` | 52 | `pytz` | 0 import hits in `*.py` | 🟡 VERIFY | No direct imports found. |
| `click==8.3.1` | 53 | `click` | 0 import hits in `*.py` | 🟡 VERIFY | Might be CLI-related or transitive. |
| `rich==14.3.2` | 54 | `rich` | 0 import hits in `*.py` | 🟡 VERIFY | Might be CLI/log formatting dependency. |

### D) Large commented-out blocks

| File path | Line numbers | Item name | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| N/A | N/A | No large commented blocks detected | No consecutive `#` blocks >=20 lines; no non-docstring triple-quoted blocks >=8 lines | N/A | Static heuristic only. |

### E) Suspected test/debug/temp files

| File path | Line numbers | Item name | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| `agent_test.py` | N/A | Test/utility script | Filename pattern (`test`), no inbound imports | 🟡 VERIFY | Could be local diagnostics. |
| `test_calendar.py` | N/A | Test script | Filename pattern (`test`), no inbound imports | 🟡 VERIFY | Likely non-production. |
| `test_car_integration.py` | N/A | Test script | Filename pattern (`test`), no inbound imports | 🟡 VERIFY | Likely non-production integration test. |
| `test_voice.py` | N/A | Test script | Filename pattern (`test`), no inbound imports | 🟡 VERIFY | Likely non-production. |
| `test_websocket.py` | N/A | Test script | Filename pattern (`test`), no inbound imports | 🟡 VERIFY | Likely non-production. |
| `tests.http` | N/A | Manual HTTP test collection | Filename pattern (`tests`) | 🟡 VERIFY | Useful for manual QA; not runtime code. |
| `requirements.txt.backup_original` | N/A | Backup artifact | Filename pattern (`backup`) | 🟢 SAFE REMOVE | Strong evidence of non-runtime backup copy. |
| `anthropic_list_models.py` | N/A | One-off utility script | No inbound imports; standalone naming | 🟡 VERIFY | Could be operational utility. |

### F) Duplicate logic (code similarity)

`jscpd` summary (Python only): 53 clones, 597 duplicated lines (6.89%), 5020 duplicated tokens (8.0%).

| File path(s) | Line numbers | Item name | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| `api/routes/image.py` + `api/routes/video.py` | `image.py:67-74` ↔ `video.py:49-56` | Temp upload path setup | `jscpd` clone (7 lines, 72 tokens) | 🟡 VERIFY | Cross-route file upload boilerplate. |
| `api/routes/chat.py` + `api/routes/workspace.py` | `chat.py:56-65` ↔ `workspace.py:43-52` | Repeated DB list query pattern | `jscpd` clone (9 lines, 65 tokens) | 🟡 VERIFY | Similar Supabase query chain. |
| `api/auth.py` + `services/database.py` | `auth.py:57-67` ↔ `database.py:9-19` | `_require_env` style bootstrap | `jscpd` clone (10 lines, 70 tokens) | 🔴 DO NOT REMOVE | Touches auth path; refactor only with extra caution. |
| `agents/traffic_agent.py` + `services/traffic_service.py` | `traffic_agent.py:73-91` ↔ `traffic_service.py:204-222` | Traffic-before-event flow | `jscpd` clone (18 lines, 60 tokens) | 🟡 VERIFY | Agent/service overlap; agents are protected dynamic components. |
| `api/routes/video.py` | `30-44` ↔ `70-82` | Similar generation/error-handling branches | `jscpd` clone (12 lines, 117 tokens) | 🟡 VERIFY | Intra-file route duplication. |
| `api/routes/calendar.py` | `56-68` repeated at `92-104`, `128-140`, `164-176` | Repeated response assembly blocks | `jscpd` clones (12 lines, 107 tokens) | 🟡 VERIFY | Candidate for helper extraction. |
| `api/routes/workspace.py` | `242-255` repeated at `267-280`, `292-305` | Repeated remote op handling | `jscpd` clones (13 lines, 131 tokens) | 🟡 VERIFY | Intra-file command execution/reply pattern. |
| `services/google_calendar_service.py` | `86-110` ↔ `137-161` | Event normalization blocks | `jscpd` clone (24 lines, 285 tokens) | 🟡 VERIFY | Candidate for single formatter helper. |
| `services/finance_service.py` | `40-53` ↔ `97-110` | HTTP request/exception pattern | `jscpd` clone (13 lines, 104 tokens) | 🟡 VERIFY | Repeated API call flow. |
| `telegram_voice_handler.py` | `45-77` ↔ `108-140` | Voice/audio handling workflow | `jscpd` clone (32 lines, 193 tokens) | 🟡 VERIFY | Large intra-file duplication. |

### G) `.env.example` variables not referenced in code (REPORT ONLY)

| File path | Line numbers | Item name | Evidence | Risk classification | Notes |
|---|---|---|---|---|---|
| `.env.example` | 13 | `SUPABASE_KEY` | No exact string hit in `*.py` | 🟡 VERIFY | Code expects `SUPABASE_SERVICE_KEY` in `services/database.py:20`, `services/vehicle_db_service.py:17`. |
| `.env.example` | 14 | `REDIS_URL` | No exact string hit in `*.py` | 🟡 VERIFY | Could be planned cache config or external runtime injection. |

## 3) Cleanup Plan (No Execution)

1. Remove low-risk unused imports first.
- Scope: all `🟢 SAFE REMOVE` import findings in non-protected files.
- Why safe: direct `ruff F401` evidence; no side-effect imports detected.
- Approval needed: low.

2. Hold protected areas for manual approval.
- Scope: anything in `autofix/`, auth/JWT paths, and agent internals.
- Why: explicitly protected by constraints; dynamic invocation likely.
- Approval needed: mandatory.

3. Verify dead-code candidates with runtime wiring before deletion.
- Scope: `bot.py` utility functions, `telegram_voice_handler.py` handlers, service methods flagged by `vulture` 60.
- Why: static tools miss DI, callbacks, string-based or doc-driven integration.
- Approval needed: medium/high.

4. Review dependency pruning in isolated steps.
- Scope: 17 no-import dependencies listed above.
- Why: many may be CLI, implicit framework deps, provider alternatives, or transitive expectations.
- Approval needed: high; remove one-by-one with test gates.

5. Refactor high-duplication hotspots.
- Scope: `api/routes/*`, `services/*`, `telegram_voice_handler.py`.
- Why: improves maintainability and bug surface; no behavior change if extracted carefully.
- Approval needed: medium.

6. Resolve env naming drift without removing vars.
- Scope: `SUPABASE_KEY` vs `SUPABASE_SERVICE_KEY` discrepancy documentation/config alignment.
- Why: reduce deployment misconfiguration risk.
- Approval needed: medium.

Proposed validation commands for cleanup PRs:

```powershell
.\.venv\Scripts\python.exe -m ruff check . --select F401,F821
.\.venv\Scripts\python.exe -m vulture . --min-confidence 80 --exclude .venv,__pycache__,site-packages
.\.venv\Scripts\python.exe -m py_compile api/main.py api/auth.py telegram_bot.py
.\.venv\Scripts\python.exe -c "import api.main; print('import_ok')"
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m uvicorn api.main:app --reload --port 8000
```

## 4) Risks & Mitigations

- Dynamic imports / plugin discovery:
  Static tools can miss `importlib`, string-based loading, and reflection.  
  Mitigation: run search for `importlib`, `getattr`, string router/handler names before deletion.

- FastAPI dependency injection and router decorators:
  Route handlers and dependencies can look unreferenced to static scanners.  
  Mitigation: treat router endpoints/middleware/dependencies as protected unless proven orphaned by runtime tests.

- Runtime-only references:
  CLI entry points, callbacks, and framework hooks may not appear in local call graphs.  
  Mitigation: keep `🟡 VERIFY` classification until integration tests and startup checks pass.

- Protected zones per requirements:
  `agents/` and `autofix/` are explicitly protected; auth/JWT paths are not removal targets.  
  Mitigation: do not propose direct removals there unless explicitly re-scoped by owner.

