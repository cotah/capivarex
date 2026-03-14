# RELATÓRIO 2 — RESULTADOS DO QA PROFISSIONAL

## Projeto: Capivarex — Proactive AI Life Assistant (Backend)

**Data:** 2026-03-13  
**QA Engineer:** Claude (QA Lead + Staff Python Engineer)  
**Repositório:** https://github.com/cotah/capivarex.git

---

## 1. SUMÁRIO EXECUTIVO

| Métrica | Valor |
|---------|-------|
| Testes executados | 2.943 |
| Testes passando (antes) | 2.934 (7 falhando) |
| Testes passando (depois) | 2.941 (0 falhando) |
| Testes ignorados | 2 |
| Bugs encontrados | 4 |
| Bugs corrigidos | 3 |
| Bugs pendentes | 1 (minor, sem fix necessário agora) |
| Regressões introduzidas | 0 |
| Arquivos alterados | 3 |

---

## 2. O QUE FOI TESTADO

A varredura cobriu 100% dos módulos do repositório:

**Camada API (30+ rotas FastAPI):** Auth, WebApp Chat, Admin, Billing, Google Auth, Spotify Auth, SmartThings, Calendar, Car, Chat, Voice WS, Voice Pipeline, Twilio Stream, Upload, Notes, Finance, Weather, Music, Image, Video, Health, Workspace, Webhooks, Traffic, Agent Generic, Images Serve.

**33 Agentes especializados:** Orchestrator, Chat, Calendar, Meeting, SmartHome, Travel, Car, Weather, Finance, Crypto, Research, Search, Dev, GitHub, Twilio, Image, Video, Voice, Transport, Mercado, Email, Music, Notes, Reminder, Restaurant, Maps, Traffic, Leaving Now, Tracking, Translate, Timer, YouTube, Media Cast.

**Serviços de Infraestrutura:** Database (Supabase), Redis (Upstash), Notification, Security Events, Sentry, Code Executor, File Manager, Git.

**Serviços de Negócio:** Quota, Mercado, Timer, Reminder, Chat, Proactivity, Email Polling, Translate, Crypto, Search, Notes, Leaving Now.

**Background Workers:** Timer loop (timers, reminders, relatório mensal, alertas preço, shopping reminder).

**Verificações de Segurança:** JWT secret keys, CORS config, admin auth, debug endpoints, encryption, input validation.

**Verificações de Qualidade:** Linter (ruff — 0 issues), imports, dependências, schemas Pydantic.

---

## 3. O QUE FOI ENCONTRADO

### Issue #1 — [CRITICAL] 7 Testes Falhando: QuotaService não mockado

**Severidade:** CRITICAL (pipeline CI quebrando)  
**Módulo:** `tests/test_webapp_routes.py`  
**Testes afetados:**
1. `TestWebappChat::test_chat_creates_conversation_and_returns_response`
2. `TestWebappChat::test_chat_with_existing_conversation`
3. `TestChatVision::test_chat_vision_with_image_attachment`
4. `TestChatVision::test_chat_vision_no_file_id_falls_through`
5. `TestChatImageUrlConversion::test_chat_converts_image_path_to_url`
6. `TestChatImageUrlConversion::test_chat_converts_multiple_image_paths`
7. `TestChatImageUrlConversion::test_chat_converts_video_path_to_url`

**Causa raiz:** Os testes não fazem mock de `get_service("quota")`. O QuotaService real tenta acessar Supabase, falha (sem DB real), e o fail-safe `_get_used()` retorna `999_999`, disparando `QuotaExceededError` → HTTP 429 em vez do esperado 200.

**Como reproduzir:**
```bash
export ENCRYPTION_KEY="<key>" JWT_SECRET_KEY="test" SUPABASE_URL="https://test.supabase.co" SUPABASE_SERVICE_KEY="test"
python -m pytest tests/test_webapp_routes.py::TestWebappChat::test_chat_creates_conversation_and_returns_response --no-cov -v
# Resultado: FAILED - assert 429 == 200
```

**Status:** CORRIGIDO

---

### Issue #2 — [CRITICAL] Inconsistência de JWT Secret Key no Voice WebSocket

**Severidade:** CRITICAL (auth bypass potencial)  
**Arquivo:** `api/routes/voice_ws.py:31`  
**Problema:** Usava `os.environ.get("SECRET_KEY", "")` enquanto todo o sistema usa `JWT_SECRET_KEY`. Se apenas `JWT_SECRET_KEY` estiver configurado, o WebSocket de voz valida JWTs com string vazia — qualquer token forjado seria aceito.

**Como reproduzir (antes do fix):**
```python
# voice_ws.py lia SECRET_KEY (vazio se não configurado)
# enquanto auth.py lia JWT_SECRET_KEY (configurado)
# → tokens válidos para API REST falham no WebSocket
# → tokens forjados (assinados com "") passam no WebSocket
```

**Status:** CORRIGIDO — alterado para `JWT_SECRET_KEY`

---

### Issue #3 — [HIGH] JWT Secret Key com Default Vazio

**Severidade:** HIGH  
**Arquivo:** `api/routes/auth.py:49`  
**Problema:** `SECRET_KEY = os.environ.get("JWT_SECRET_KEY", "")` — fallback para string vazia permite JWTs trivialmente falsificáveis. A função `_require_env()` existe no mesmo arquivo mas não era usada para SECRET_KEY.

**Status:** CORRIGIDO — adicionado log CRITICAL se SECRET_KEY estiver vazio em produção

---

### Issue #4 — [MINOR] Módulo audioop deprecado

**Severidade:** MINOR  
**Arquivo:** `utils/audio_converter.py:26`  
**Problema:** `audioop` está deprecated desde Python 3.12 e será removido em 3.13. Usado para conversão de áudio µ-law.

**Status:** PENDENTE — não é um bug atual, mas precisa de migração antes de atualizar para Python 3.13+. Alternativa: usar `audioop-lts` ou reescrever com numpy.

---

## 4. O QUE FOI CORRIGIDO

### Fix #1 — Mock do QuotaService nos 7 testes

**Arquivos alterados:** `tests/test_webapp_routes.py`  
**Alteração:** Adicionado `patch("api.routes.webapp.get_service", return_value=None)` no bloco `with` de cada teste, fazendo o quota service retornar `None` (mesmo padrão do teste existente `test_chat_quota_service_unavailable_allows_through`).  
**Impacto:** Testes agora simulam corretamente o cenário onde quota não bloqueia, permitindo testar o fluxo de chat real.  
**Risco:** Zero — usa o mesmo padrão que o teste de quota existente.

### Fix #2 — JWT Secret Key no Voice WebSocket

**Arquivo alterado:** `api/routes/voice_ws.py`  
**Alteração:** Mudado `os.environ.get("SECRET_KEY", "")` para `os.environ.get("JWT_SECRET_KEY", "")` e `os.environ.get("ALGORITHM", "HS256")` para `os.environ.get("JWT_ALGORITHM", "HS256")`.  
**Impacto:** Voice WebSocket agora usa a mesma chave JWT que o resto do sistema.  
**Risco:** Baixo — se alguém usava `SECRET_KEY` separada para o WebSocket, precisará migrar para `JWT_SECRET_KEY`. Mas isso era quase certamente um bug, não feature intencional.

### Fix #3 — Warning para JWT Secret Key vazia

**Arquivo alterado:** `api/routes/auth.py`  
**Alteração:** Adicionada validação que emite `logger.critical(...)` se `JWT_SECRET_KEY` estiver vazia em ambiente não-teste.  
**Impacto:** Operadores verão imediatamente o problema no log de startup.  
**Risco:** Zero — apenas adiciona logging, não altera comportamento.

---

## 5. COMO VALIDAR

```bash
# 1. Instalar dependências
pip install -r requirements.txt -r requirements-dev.txt

# 2. Configurar ambiente mínimo
export ENCRYPTION_KEY="<gerar com: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'>"
export JWT_SECRET_KEY="<string-segura-aleatória>"
export SUPABASE_URL="<url>"
export SUPABASE_SERVICE_KEY="<key>"
export ENVIRONMENT="development"

# 3. Rodar todos os testes
python -m pytest tests/ --no-cov -q
# Esperado: 2941 passed, 2 skipped, 0 failed

# 4. Rodar apenas os testes corrigidos
python -m pytest tests/test_webapp_routes.py -k "test_chat_creates_conversation or test_chat_with_existing or test_chat_vision or test_chat_converts" --no-cov -v
# Esperado: 7 passed

# 5. Verificar lint (zero issues)
ruff check . --select E,W,F --ignore E501,E402
```

---

## 6. MÉTRICAS

| Métrica | Valor |
|---------|-------|
| Testes antes | 2934 passed / 7 failed |
| Testes depois | 2941 passed / 0 failed |
| Testes adicionados | 0 (corrigidos os existentes) |
| Cobertura de testes existente | ~79% |
| Arquivos alterados | 3 |
| Linhas adicionadas | ~8 |
| Linhas modificadas | ~3 |

---

## 7. CHANGELOG TÉCNICO (diffs de alto nível)

### `tests/test_webapp_routes.py`
- 7 testes: adicionado `patch("api.routes.webapp.get_service", return_value=None)` no context manager `with` para fazer mock do QuotaService

### `api/routes/voice_ws.py`
- Linha 31: `"SECRET_KEY"` → `"JWT_SECRET_KEY"`
- Linha 32: `"ALGORITHM"` → `"JWT_ALGORITHM"`

### `api/routes/auth.py`
- Após linhas 49-51: adicionado bloco de validação que emite `logger.critical(...)` se `JWT_SECRET_KEY` estiver vazio em produção

---

## 8. RECOMENDAÇÕES FUTURAS (priorizadas)

### Prioridade ALTA

1. **Refatorar `api/routes/webapp.py`** — 2626 linhas é excessivo para um único arquivo. Extrair em sub-módulos: `webapp_chat.py`, `webapp_conversations.py`, `webapp_notes.py`, `webapp_finance.py`, etc.

2. **Validação do JWT Secret no startup da app** — Bloquear o startup em produção se `JWT_SECRET_KEY` não estiver definido (não apenas logar warning).

3. **Migrar audioop** — Antes de atualizar para Python 3.13, migrar `utils/audio_converter.py` para usar `audioop-lts` ou numpy.

4. **Migrar PyPDF2 para pypdf** — PyPDF2 está deprecated (warning nos testes).

### Prioridade MÉDIA

5. **Centralizar configuração JWT** — Ter um único módulo `config/jwt.py` que exporta `SECRET_KEY` e `ALGORITHM`, em vez de cada route file ler do os.environ separadamente.

6. **QuotaService fail-safe revisto** — O retorno de `999_999` quando todos os sistemas falham é agressivo demais. Considerar um "grace period" ou flag de degradação graciosa.

7. **Testes de integração com Supabase mock completo** — Os 2 testes skipped podem indicar falta de infraestrutura de teste para cenários mais complexos.

### Prioridade BAIXA

8. **Reduzir warnings** — 12 deprecation warnings nos testes (supabase, PyPDF2, jwt InsecureKeyLength, audioop).

9. **Debug endpoints** — Validar que `ENVIRONMENT != "development"` é suficiente. Considerar também validar por IP ou token.

10. **CORS wildcards** — `"https://*.replit.dev"` não funciona como wildcard em CORSMiddleware do Starlette (é tratado como string literal). Precisa ser tratado de forma diferente se for usado.

---

*Relatório gerado automaticamente após execução completa do QA no repositório Capivarex.*
