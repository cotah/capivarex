# RELATÓRIO 1 — PLANO DE TESTE PROFISSIONAL

## Projeto: Capivarex — Proactive AI Life Assistant (Backend)

**Data:** 2026-03-13  
**QA Engineer:** Claude (QA Lead + Staff Python Engineer)  
**Repositório:** https://github.com/cotah/capivarex.git  
**Versão analisada:** commit HEAD (main branch)

---

## 1. RESUMO DO PROJETO

O Capivarex é um assistente de IA proativo tipo "Jarvis" que integra 33+ agentes especializados para gerenciar a vida diária do utilizador. O backend é construído em Python 3.11 com FastAPI e utiliza uma arquitetura de Service Registry (singleton) com lazy loading, e Agent Registry para roteamento de intenções.

**Stack Técnica:** Python 3.11, FastAPI, Supabase (PostgreSQL), Upstash Redis, OpenAI GPT-4.1-mini, Telegram Bot, WebSocket, arq (worker), Prometheus, Sentry.

**Métricas do código fonte:**

- Linhas de código fonte (excl. testes): ~70.000
- Linhas de testes: ~45.000
- Total de testes existentes: 2.943
- Total de arquivos Python: ~150
- Cobertura declarada: 79%+

---

## 2. MATRIZ DE COMPONENTES

### 2.1 Camada API (FastAPI) — 30+ rotas

| Módulo | Arquivo | Endpoints | Criticidade |
|--------|---------|-----------|-------------|
| Auth (JWT) | `api/routes/auth.py` | POST /login, POST /register | CRÍTICA |
| WebApp Chat | `api/routes/webapp.py` (2626 linhas) | POST /chat, GET /conversations, etc. | CRÍTICA |
| Admin | `api/routes/admin.py` | GET/POST /tenants, /security-events | ALTA |
| Billing (Stripe) | `api/routes/billing.py` | POST /checkout, webhooks | CRÍTICA |
| Google Auth (OAuth2) | `api/routes/google_auth.py` | /callback, /status | ALTA |
| Spotify Auth | `api/routes/spotify_auth.py` | OAuth2 flow | MÉDIA |
| SmartThings | `api/routes/smartthings.py` | OAuth2 + device control | ALTA |
| Calendar | `api/routes/calendar.py` | CRUD eventos | ALTA |
| Car (Smartcar) | `api/routes/car.py` | Veículo EV status | MÉDIA |
| Chat | `api/routes/chat.py` | Telegram chat flow | ALTA |
| Voice WS | `api/routes/voice_ws.py` | WebSocket voz real-time | ALTA |
| Voice Pipeline | `api/routes/voice_pipeline_routes.py` | STT → LLM → TTS | ALTA |
| Twilio Stream | `api/routes/twilio_stream.py` | Chamadas telefónicas | ALTA |
| Upload | `api/routes/upload.py` | File upload + OCR | MÉDIA |
| Notes | `api/routes/notes.py` | CRUD notas | BAIXA |
| Finance | `api/routes/finance.py` | Cotações stocks | BAIXA |
| Weather | `api/routes/weather.py` | Previsão tempo | BAIXA |
| Music | `api/routes/music.py` | Spotify search | BAIXA |
| Image/Video | `api/routes/image.py`, `video.py` | Geração de mídia | MÉDIA |
| Health | `api/routes/health.py` | Health checks | ALTA |
| Workspace | `api/routes/workspace.py` | Projetos + Git | MÉDIA |
| Webhooks | `api/routes/webhooks.py` | Webhooks genéricos | MÉDIA |

### 2.2 Agentes Especializados (33 agentes)

| Agente | Arquivo | Integração |
|--------|---------|------------|
| Orchestrator | `orchestrator_agent.py` | OpenAI GPT-4.1-mini |
| Chat | `chat_agent.py` | OpenAI |
| Calendar | `calendar_agent.py` | Google Calendar API |
| Meeting | `meeting_agent.py` | Google Calendar API |
| SmartHome | `smarthome_agent.py` | SmartThings OAuth2 |
| Travel | `travel_agent.py` | Duffel API |
| Car | `car_agent.py` | Smartcar API |
| Weather | `weather_agent.py` | OpenWeatherMap |
| Finance | `finance_agent.py` | Twelve Data API |
| Crypto | `crypto_agent.py` | CoinGecko API |
| Research | `research_agent.py` | Perplexity Sonar |
| Search | `search_agent.py` | Serper API |
| Dev | `dev_agent.py` | Anthropic Claude |
| GitHub | `github_agent.py` | GitHub API |
| Twilio | `twilio_agent.py` | Twilio + Deepgram |
| Image | `image_agent.py` | Google Gemini |
| Video | `video_agent.py` | Google Gemini Veo |
| Voice | `voice_agent.py` | ElevenLabs |
| Transport | `transport_agent.py` | Transit APIs |
| Mercado | `mercado_agent.py` | Supabase + Vision OCR |
| Email | `email_agent.py` | Gmail API |
| Music | `music_agent.py` | Spotify API |
| Notes | `notes_agent.py` | Supabase |
| Reminder | `reminder_agent.py` | Supabase + Redis |
| Restaurant | `restaurant_agent.py` | Google Places |
| Maps | `maps_agent.py` | Google Maps |
| Traffic | `traffic_agent.py` | Google Maps Traffic |
| Leaving Now | `leaving_now_agent.py` | Maps + Calendar |
| Tracking | `tracking_agent.py` | 17TRACK API |
| Translate | `translate_agent.py` | AI-powered |
| Timer | `timer_agent.py` | Redis + Upstash |
| YouTube | `youtube_agent.py` | YouTube Data API |
| Media Cast | `media_cast_agent.py` | Chromecast |

### 2.3 Serviços de Infraestrutura

| Serviço | Arquivo | Função |
|---------|---------|--------|
| Database | `services/infrastructure/database.py` | Supabase client |
| Redis | `services/infrastructure/redis_service.py` | Upstash Redis cache |
| Notification | `services/infrastructure/notification_service.py` | Telegram notifications |
| Security Events | `services/infrastructure/security_event_service.py` | Audit logging |
| Sentry | `services/infrastructure/sentry_service.py` | Error tracking |
| Code Executor | `services/infrastructure/code_executor.py` | Python sandbox |
| File Manager | `services/infrastructure/file_manager.py` | File operations |
| Git | `services/infrastructure/git_service.py` | Git operations |

### 2.4 Serviços de Negócio

| Serviço | Função |
|---------|--------|
| QuotaService | Controlo de quotas por plano (free/me/everywhere) |
| MercadoService | Lista de compras, OCR de recibos, tracking preços |
| TimerService | Timers/alarmes com Redis |
| ReminderService | Lembretes persistentes |
| ChatService | Serviço de chat conversacional |
| ProactivityService | Briefings proativos |
| EmailPollingService | Polling de emails |

### 2.5 Background Workers

| Worker | Função |
|--------|--------|
| `_timer_loop()` | Loop 10s: timers, lembretes, relatório mensal, alertas preço, lembrete compras |
| `worker.py` | arq worker para tarefas assíncronas |

---

## 3. BUGS E ISSUES JÁ IDENTIFICADOS NA VARREDURA

### 3.1 [CRITICAL] 7 Testes Falhando — QuotaService não mockado

**Testes afetados:** Todos em `TestWebappChat`, `TestChatVision`, `TestChatImageUrlConversion`

**Causa raiz:** Os testes não fazem mock do `get_service("quota")`, permitindo que o QuotaService real execute. Como o Supabase real não está disponível no ambiente de teste, `_get_used()` retorna `999_999` (fail-safe), causando `QuotaExceededError` → HTTP 429.

**Impacto:** 7 testes falhando, pipeline de CI pode estar quebrando.

### 3.2 [CRITICAL] Inconsistência de Chave JWT — voice_ws.py

**Arquivo:** `api/routes/voice_ws.py:31`  
**Issue:** Usa `os.environ.get("SECRET_KEY", "")` enquanto todo o resto do sistema usa `JWT_SECRET_KEY`.  
**Impacto:** Se apenas `JWT_SECRET_KEY` estiver configurado (como documentado), o WebSocket de voz aceita tokens assinados com string vazia — **bypass de autenticação completo**.

### 3.3 [HIGH] Default vazio para JWT Secret Key

**Arquivos:** `api/routes/auth.py:49`, `api/routes/chat.py:35`  
**Issue:** `SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")` — se a variável não existir, usa string vazia.  
**Impacto:** Tokens JWT trivialmente falsificáveis se a env var estiver ausente. A função `_require_env()` existe no mesmo arquivo mas NÃO é usada para SECRET_KEY.

### 3.4 [MINOR] audioop deprecado

**Arquivo:** `utils/audio_converter.py:26`  
**Issue:** Módulo `audioop` é deprecated em Python 3.12 e será removido em 3.13.

---

## 4. ESTRATÉGIA DE TESTES

### 4.1 Testes Unitários (pytest)

- Verificar todos os 2943 testes existentes passam (corrigir os 7 falhando)
- Adicionar testes para cobrir os bugs de segurança encontrados
- Priorizar testes para fluxos críticos: auth, quota, chat, billing

### 4.2 Testes de Integração (com mocks)

- API routes com TestClient (FastAPI)
- Fluxos de auth completos: register → login → token → protected endpoint
- Fluxos de quota: free plan limits, upgrade, exceeded
- WebSocket voice pipeline (mock STT/TTS)

### 4.3 Testes Negativos / Edge Cases

- JWT com string vazia como secret (deve falhar com segurança)
- JWT expirado, malformado, sem "sub" claim
- Payloads inválidos em todas as rotas (campos vazios, tipos errados, overflow)
- Rate limiting: verificar que 5/min funciona para login
- Quota exceeded: verificar HTTP 429 com mensagem adequada
- Credenciais de API ausentes: verificar degradação graciosa

### 4.4 Testes de Segurança

- Admin routes sem token: devem retornar 403/503
- Debug endpoints em produção: devem retornar 404
- CORS: verificar que origens não configuradas são bloqueadas
- JWT secret vazio: verificar que não permite acesso
- Injection: verificar sanitização de inputs

### 4.5 Critérios de Pass/Fail

| Critério | Meta |
|----------|------|
| Testes passando | 100% (0 failures) |
| Cobertura mínima | 79% (manter o atual) |
| Bugs CRITICAL | 0 abertos ao final |
| Bugs HIGH | 0 abertos ao final |
| Regressões | 0 introduzidas |

---

## 5. INTEGRAÇÕES E COMO TESTAR

| Integração | Método | Mock/Real |
|------------|--------|-----------|
| Supabase (PostgreSQL) | Mock via `_mock_db()` existente | MOCK |
| Upstash Redis | Mock via `unittest.mock` | MOCK |
| OpenAI API | Mock response objects | MOCK |
| Google Calendar | Mock async methods | MOCK |
| Telegram Bot | Mock `bot.send_message` | MOCK |
| Stripe | Mock stripe module | MOCK |
| Twilio/Deepgram | Mock WebSocket frames | MOCK |
| Smartcar/SmartThings | Mock HTTP responses | MOCK |
| Todas as APIs externas | Variáveis de env + fallback mock | MOCK |

---

## 6. RISCOS E ÁREAS CRÍTICAS

| Área | Risco | Severidade |
|------|-------|------------|
| JWT Secret vazio | Auth bypass total | CRITICAL |
| Voice WS secret key errada | Auth bypass no WebSocket | CRITICAL |
| QuotaService fail-safe | Bloqueia acesso quando DB cai | HIGH |
| Timer loop no processo FastAPI | Crash no loop afeta toda API | HIGH |
| Code Executor (subprocess) | Execução de código sem sandboxing rigoroso | MEDIUM |
| Arquivo webapp.py com 2626 linhas | Manutenibilidade, risco de bugs | LOW |
| audioop deprecated | Quebra em Python 3.13 | LOW |

---

## 7. PLANO DE EXECUÇÃO

**Fase 1 — Correção dos testes falhando (7 testes)**
- Adicionar mock do QuotaService nos testes afetados
- Verificar que todos 2943 testes passam

**Fase 2 — Correção de bugs de segurança**
- Fix `voice_ws.py`: mudar `SECRET_KEY` para `JWT_SECRET_KEY`
- Fix `auth.py` e `chat.py`: validar que JWT secret não é vazio no startup

**Fase 3 — Testes adicionais**
- Adicionar testes para os bugs corrigidos
- Verificar regressão zero

**Fase 4 — Relatório final**

---

*Documento gerado automaticamente pela varredura QA do repositório Capivarex.*
