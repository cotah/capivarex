# CAPIVAREX — Changelog para Claude Code

**Documento de sincronização.** Tudo que foi implementado/alterado no backend.
O Claude Code deve ler isto para saber o estado actual do projecto.

**Última actualização:** 2026-03-16 (A-TIER fechado)
**Sessões cobertas:** QA Session 9 (S-TIER + Sprint 0 + Resilience + A-TIER completo)

---

## 1. S-TIER Intelligence — 9 Serviços Proactivos (TODOS COMPLETOS)

### S1. Morning Briefing
- **Ficheiro:** `services/business/morning_briefing_service.py`
- **Testes:** `tests/test_morning_briefing_service.py`
- **O que faz:** Briefing matinal combinando weather + calendar + finance. Humanizado via GPT.
- **Trigger:** Proactivity loop Step 5, diário 06:00-10:00 UTC
- **Integra com:** weather service, calendar service, finance service, OpenAI

### S2. Meeting Briefing
- **Ficheiro:** `services/business/meeting_briefing_service.py`
- **Testes:** `tests/test_meeting_briefing_service.py`
- **O que faz:** Prep automático 1.5-2.5h antes de reuniões com contexto RAG.
- **Trigger:** Proactivity loop Step 6, a cada ciclo de 5 min
- **Integra com:** calendar service, RAG service, OpenAI

### S3. Finance Alerts
- **Ficheiro:** `services/business/finance_alert_service.py` (já existia)
- **O que faz:** Alerta quando stocks/crypto passam threshold do user.
- **Trigger:** Proactivity loop Step 4, a cada ciclo

### S4. Weekly Finance Recap
- **Ficheiro:** `services/business/weekly_recap_service.py`
- **Testes:** `tests/test_weekly_recap_service.py`
- **O que faz:** Resumo semanal de stocks/crypto + watchlist personalizada por user.
- **Trigger:** Proactivity loop Step 7, segundas 08:00-10:00 UTC
- **Watchlist:** Guardada em `user_context` table. Default: AAPL, MSFT, GOOGL, AMZN, TSLA + BTC, ETH, SOL.
- **Finance Agent atualizado:** `agents/specialized/finance_agent.py` — comandos "add X to watchlist", "remove X", "show watchlist"

### S5. Personalized News
- **Ficheiro:** `services/business/finance_news_service.py` (reescrito)
- **O que faz:** News personalizada por interesses do user via RAG + Perplexity + GPT.
- **Trigger:** Proactivity loop Step 3, 2x/dia
- **Cada user recebe notícias DIFERENTES** baseadas no perfil RAG + watchlist + user_context

### S6. Travel Planner (3 Fases)
- **Ficheiro:** `services/business/travel_planner_service.py`
- **Testes:** `tests/test_travel_planner_service.py`
- **Fase 1 (Detection):** Scan calendar 14-30 dias à frente. 100+ destinos (países/cidades, multi-language). Keywords de viagem. Min 3 dias. Dedup per event_id.
- **Fase 2 (Itinerary):** `gather_travel_profile()` from RAG + user_context. `build_preference_questions()` só pergunta o que FALTA. `build_itinerary()` via Perplexity + weather + GPT.
- **Fase 3 (Session):** State machine: detected → gathering → building → reviewing → finalized. `handle_travel_planning_message()` full conversation flow. Connected to `agents/specialized/travel_agent.py`.
- **Trigger:** Proactivity loop Step 8, diário 10:00-12:00 UTC

### S7. Voice → Notes + Reminders
- **Ficheiro:** `services/business/implicit_action_service.py`
- **Testes:** `tests/test_implicit_action_service.py`
- **O que faz:** Detecta acções implícitas em mensagens ("nota que...", "lembra-me...", "agenda...")
- **2 níveis:** Fast keyword detection (0 custo API) + GPT classification (ambíguos)
- **Executa:** via notes agent, reminder agent, calendar agent
- **Entry point:** `check_and_execute_implicit_action()` — chamar ANTES do orchestrator

### S8. Email Triage
- **Ficheiro:** `services/business/email_triage_service.py`
- **Testes:** `tests/test_email_triage_service.py`
- **O que faz:** "Trata da inbox" → busca emails → GPT categoriza (urgent/important/info/ignore) → extrai acções → sugere respostas → resumo humanizado
- **GPT batch:** classifica todos os emails em 1 API call
- **Fallback:** keyword-based classification quando GPT indisponível
- **Reply draft:** `generate_reply_draft()` — tom ajustável (professional/casual/formal)

### S9. Meeting Orchestrator
- **Ficheiro:** `services/business/meeting_orchestrator_service.py`
- **Testes:** `tests/test_meeting_orchestrator_service.py`
- **O que faz:** "Marca reunião com X" → verifica disponibilidade → cria evento com Meet link → envia convite email → cria notas de prep → confirma humanizado
- **parse_meeting_request():** GPT extrai título, attendees, data, hora, duração, descrição
- **Se conflito:** avisa + sugere horário alternativo
- **Se um passo falha:** os outros continuam

---

## 2. Sprint 0 — Security Fixes (11 fixes)

### F1. JWT_SECRET_KEY crash em prod
- **Ficheiros:** `api/dependencies/auth.py`, `api/routes/auth.py`
- **O que faz:** `RuntimeError` no startup se JWT_SECRET_KEY vazio em produção
- **Permite vazio em:** test, development, dev, ci

### F2. Rate limiter verify_signature
- **Ficheiro:** `api/middleware/rate_limit.py`
- **O que faz:** JWT decode agora verifica assinatura com JWT_SECRET_KEY + algorithm
- **Adicionou:** `import os`
- **Fallback:** unsigned só se JWT_SECRET_KEY vazio (dev mode)

### F3. /dev/test → admin only
- **Ficheiro:** `api/routes/dev.py:231`
- **O que faz:** `get_current_user` → `get_admin_user`

### F4. Webhook email HMAC auth
- **Ficheiro:** `api/routes/webhooks.py`
- **O que faz:** HMAC-SHA256 signature verification via `X-Webhook-Signature` header
- **Env var:** `WEBHOOK_SECRET`
- **Sem secret:** permite em dev (warning no log)

### F5. Subprocess sandbox
- **Ficheiro:** `services/infrastructure/code_executor.py`
- **O que faz:** `env={}` com só PATH, PYTHONPATH, HOME, LANG
- **Adicionou:** `import os`

### F6. Admin constant-time comparison
- **Ficheiro:** `api/routes/admin.py`
- **O que faz:** `hmac.compare_digest` em vez de `!=`

### F7. CORS headers restricted
- **Ficheiro:** `api/main.py`
- **O que faz:** `allow_headers=["*"]` → lista explícita (Authorization, Content-Type, Accept, Origin, X-Requested-With, X-Webhook-Signature)

### F8. Timer race condition
- **Ficheiro:** `services/business/timer_service.py`
- **O que faz:** `asyncio.Lock` em create_timer, cancel_timer, cancel_all_timers, check_and_fire_due
- **Lazy init:** `_get_lock()` cria lock na primeira chamada (deve ser em async context)

### F9. Supabase sync → async
- **Ficheiro:** `api/main.py`
- **O que faz:** 2 chamadas `client.table().select()` wrapped com `asyncio.to_thread`
- **Locais:** startup schema check + `/api/health` endpoint

### F10. Fire-and-forget safe_create_task
- **Ficheiro novo:** `utils/safe_task.py`
- **O que faz:** Wrapper de `asyncio.create_task` com exception logging via callback
- **Aplicado em:** `api/routes/webapp.py` (8 calls), `api/routes/voice_ws.py` (4 calls)
- **Antes:** erros silenciosos. Agora: logados com nome da task

### F11. Env var validation on startup
- **Ficheiro:** `api/main.py` (lifespan function)
- **Crash se faltar:** JWT_SECRET_KEY, SUPABASE_URL, SUPABASE_SERVICE_KEY (só em prod)
- **Warning se faltar:** OPENAI_API_KEY, ENCRYPTION_KEY, SENTRY_DSN

---

## 3. Resilience Service (Supabase Outage Protection)

- **Ficheiro:** `services/infrastructure/resilience_service.py`
- **Testes:** `tests/test_resilience_service.py`
- **O que faz:** Quando Supabase cai, serve dados do Redis cache
- **Funções principais:**
  - `resilient_query(cache_key, supabase_fn, ttl)` — tenta Supabase → cache em Redis → fallback do Redis
  - `_mark_supabase_down()` / `_mark_supabase_up()` — health tracking (3 falhas consecutivas = down)
  - `get_user_resilient()`, `get_proactivity_users_resilient()` — queries pré-construídas
  - `cache_user_on_login()`, `cache_auth_token()` — caching proactivo
  - `get_resilience_status()` — retorna mode normal/degraded

- **Integrado em:** `services/infrastructure/database.py` — `get_user_by_id()` agora usa `resilient_query`
- **Health endpoint:** `api/main.py` — mostra "degraded" quando Supabase down mas Redis funciona

---

## 4. A-TIER — High Value Features (9/12 COMPLETAS)

### A1. Birthday Detection
- **Ficheiro:** `services/business/birthday_service.py`
- **Testes:** `tests/test_birthday_service.py`
- **O que faz:** Detecta aniversários no calendário (próximos 7 dias)
- **Keywords:** birthday, aniversário, bday, niver (multi-language)
- **Extrai nome** da pessoa do summary do evento
- **Alert humanizado** via GPT com sugestões (presente, mensagem, jantar)
- **Dedup:** por event_id (1 alerta por aniversário)
- **Proactivity loop Step 9:** `proactivity_loop.py` — `_run_birthday_detection()` diário 08:00-10:00 UTC

### A2. Leaving Home Check
- **Ficheiro:** `services/business/leaving_home_check_service.py`
- **Testes:** `tests/test_leaving_home_check_service.py`
- **O que faz:** Quando user diz "vou sair" → briefing completo de saída
- **Trigger keywords:** "vou sair", "i'm leaving", "heading out", "me voy" (PT/EN/ES)
- **Detecção:** `is_leaving_trigger(message)` — chamar antes do orchestrator
- **4 verificações:** Weather, Calendar + departure time, Smart Home, Traffic
- **Humanizado** via GPT — 1 mensagem warm com tudo junto

### A3. Arriving Home Prep — ⏸️ PAUSADO (precisa device físico)

### A4. Payment Reminder
- **Ficheiro:** `services/business/payment_reminder_service.py`
- **Testes:** `tests/test_payment_reminder_service.py`
- **O que faz:** Detecta contas/pagamentos em mensagens e emails → lembra antes do vencimento
- **40+ keywords** PT/EN/ES: conta, fatura, bill, invoice, payment...
- **GPT extrai:** nome, valor, dia de vencimento, se é recorrente
- **Storage:** `user_context` table (key: payment_reminders)
- **Alertas:** 3 dias antes, 1 dia antes, no dia, atrasado
- **Entry point:** `handle_payment_mention(user_id, message)`

### A5. Agenda Conflict Detection
- **Ficheiro:** `services/business/agenda_conflict_service.py`
- **Testes:** `tests/test_agenda_conflict_service.py`
- **O que faz:** Detecta sobreposições e gaps curtos entre eventos no calendário
- **2 tipos:** overlap (mesmo horário) + tight_gap (<30 min entre locais diferentes)
- **Ignora** gap curto se mesmo local (não precisa de viagem)
- **Humanizado** via GPT → sugere remarcar ou tornar virtual
- **Runner:** `check_conflicts_for_all_users()` pronto para proactivity loop

### A6. Overdue Tasks
- **Ficheiro:** `services/business/overdue_tasks_service.py`
- **Testes:** `tests/test_overdue_tasks_service.py`
- **O que faz:** Detecta reminders e notas com prazo atrasado → nudge gentil
- **Verifica:** reminders pendentes (últimos 3 dias) + notas com due_date passado (últimos 7 dias)
- **Tom:** "Just checking in..." — gentil, não nagging
- **Runner:** `check_overdue_for_all_users()` pronto para proactivity loop

### A7. Unexpected Weather Alert
- **Ficheiro:** `services/business/weather_alert_service.py`
- **Testes:** `tests/test_weather_alert_service.py`
- **O que faz:** Alerta proativo quando tempo muda para pior
- **5 tipos:** chuva (>70%), vento forte (>50km/h), calor extremo (>35°C), neve/gelo, queda de temperatura
- **Dedup:** 1 alerta por tipo por dia (no spam)
- **Storage:** proactivity_feed (por alert_type + data)
- **Runner:** `check_weather_for_all_users()` pronto para proactivity loop

### A8. Relationship Maintenance — ⏭️ PULADO (pouca utilidade prática)

### A9. Subscription Expiring
- **Ficheiro:** `services/business/subscription_service.py`
- **Testes:** `tests/test_subscription_service.py`
- **O que faz:** Detecta subscrições em emails/mensagens → avisa 5 dias antes de renovar
- **35+ serviços conhecidos:** Netflix, Spotify, Adobe, ChatGPT, etc.
- **GPT extrai:** nome, valor, data de renovação, frequência
- **Storage:** `user_context` table (key: subscriptions)
- **Entry point:** `handle_subscription_mention(user_id, message)`

### A10. Package Tracking Central
- **Ficheiro:** `services/business/package_tracking_service.py`
- **Testes:** `tests/test_package_tracking_service.py`
- **O que faz:** Auto-detecta tracking numbers em emails/mensagens → monitora via 17TRACK
- **Regex patterns:** UPS, FedEx, DHL, USPS, CTT/An Post, Amazon, genérico
- **Monitorização:** polling de status, detecta mudanças (shipped→transit→delivered)
- **Para automaticamente** quando entregue
- **Entry point:** `handle_tracking_mention(user_id, message)`

### A11 + A12 — 📦 MOVIDOS para "Work Pack" (add-on profissional futuro)

---

## 5. Bugfixes durante A-TIER

### CORS allow_headers fix
- **Ficheiro:** `api/main.py`
- **O que mudou:** `allow_headers` voltou a `["*"]` — o F7 (headers restritos) bloqueava preflight OPTIONS do Tuya login
- **Segurança mantida:** `allow_origin_regex` continua a restringir QUEM acede (só capivarex.com)

### Tuya token refresh fix (PYTHON-20 Sentry)
- **Ficheiro:** `services/auth/tuya_oauth_service.py`
- **O que mudou:** Após 3 falhas de refresh, desactiva o token (`active=false`) → user vê "Reconectar"
- **Novo método:** `_deactivate_token(user_id)` — marca token como inactivo no DB
- **Debug logging:** cada tentativa loga prefixos dos tokens usados
- **Endpoint:** `/smarts/devices` retorna `needs_reconnect: true` quando token inactivo
- **Causa raiz:** refresh_token expirado (>30 dias) — Tuya retorna "sign invalid" em vez de "token expired"

---

## 7. CI/CD Changes

- **PyJWT:** 2.11.0 → 2.12.0 (`requirements.txt`) — fix CVE-2026-32597
- **GitHub Actions:** v5 → v6 (`ci.yml`) — Node 24 nativo
  - `actions/checkout@v6`
  - `actions/setup-python@v6`
  - `actions/cache@v5`
- **Security audit:** removido `continue-on-error: true` (agora falha pipeline se houver vulns)

---

## 6. Documentação

- **README.md** — Reescrito completamente (35 agentes, 9 S-TIER, 17 business services, proactivity loop)
- **SECURITY_FIX_ROADMAP.md** — Verificação das 15 vulns (2 falsos positivos, 13 reais)
- **ROADMAP_TIERS.md** — Sprint 0 + S-TIER + A-TIER + B-TIER + C-TIER (61 features total)

---

## 7. Proactivity Loop Steps (Actual)

Ficheiro: `proactivity_loop.py`

1. Proactivity checks (insights)
2. Email polling
3. News fetching (2x/day)
4. Finance price alerts (every cycle)
5. Morning briefings (06:00-10:00 UTC)
6. Meeting briefings (every cycle)
7. Weekly finance recap (Mondays 08:00-10:00 UTC)
8. Travel detection (daily 10:00-12:00 UTC)
9. Birthday detection (daily 08:00-10:00 UTC)

---

## 8. Test Metrics

| Métrica | Valor |
|---------|-------|
| Tests passando | 3430 |
| Tests falhando | 0 |
| Tests skipped | 0 |
| Coverage | 79.09% |
| Ruff errors | 0 |
| Test files | 108 |
| Python files | 375+ |

---

## 9. Env Vars Novas

| Variável | Propósito | Obrigatória |
|----------|-----------|-------------|
| `WEBHOOK_SECRET` | HMAC signature para email webhook | Não (permite sem em dev) |

Todas as outras env vars existentes continuam iguais.

---

## 10. Regra IMPORTANTE

**TODAS as mensagens proactivas DEVEM passar pelo GPT para humanização.** SEMPRE. Sem templates robóticos, sem listas secas. Cada mensagem soa como um amigo inteligente.
