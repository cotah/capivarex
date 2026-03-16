# CAPIVAREX — Security & Quality Fix Roadmap

## Auditoria: Análise e Verificação

Relatório original do Claude Code foi verificado item a item. Abaixo está o resultado da investigação com status de cada vulnerabilidade.

---

## VULNERABILIDADES DE SEGURANÇA

### 🔴 CRÍTICAS (Confirmadas: 4 de 6)

| # | Vulnerabilidade | Ficheiro | Status | Severidade Real |
|---|----------------|----------|--------|-----------------|
| 1 | **JWT_SECRET_KEY vazio permitido em produção** | `api/dependencies/auth.py:27` | ✅ CONFIRMADO — `os.environ.get("JWT_SECRET_KEY", "")` aceita string vazia. Tem log de warning mas não bloqueia startup. | **CRÍTICO** |
| 2 | **Rate limiter decodifica JWT sem verificar assinatura** | `api/middleware/rate_limit.py:46` | ✅ CONFIRMADO — `verify_signature: False` permite tokens forjados com plano "everywhere" (bypass de rate limits). | **CRÍTICO** |
| 3 | **`/dev/test` permite execução de código por qualquer user** | `api/routes/dev.py:231` | ✅ CONFIRMADO — Usa `get_current_user` em vez de `get_admin_user`. Qualquer user autenticado pode executar código Python arbitrário. | **CRÍTICO** |
| 4 | **WebSocket JWT sem verificação de audience** | `api/routes/voice_ws.py:72-83` | ✅ CONFIRMADO — `verify_aud: False`. Risco baixo porque não usamos audience claims, mas deve ser corrigido. | **MÉDIO** (não crítico na prática) |
| 5 | **Webhook de email sem autenticação** | `api/routes/webhooks.py:21-62` | ✅ CONFIRMADO — Aceita POST de qualquer IP com qualquer `user_id` no payload. Atacante pode injectar emails falsos. | **CRÍTICO** |
| 6 | **Path traversal via glob** | `api/routes/webapp.py:172` | ❌ FALSO POSITIVO — `partial_id` extraído por regex `[a-f0-9\-]+` (só hex + hífens). `../` não pode ser injectado. | N/A |

### 🟡 ALTAS (Confirmadas: 3 de 5)

| # | Vulnerabilidade | Ficheiro | Status | Severidade Real |
|---|----------------|----------|--------|-----------------|
| 7 | **IDOR em notas — delete sem verificar user_id** | `api/routes/webapp.py:2053` | ❌ FALSO POSITIVO — O código já faz `.eq("user_id", user_id)` na query. Verificado no código. | N/A |
| 8 | **Admin token sem constant-time comparison** | `api/routes/admin.py:43` | ✅ CONFIRMADO — `if token != _ADMIN_SECRET` é vulnerável a timing attacks. Deve usar `hmac.compare_digest`. | **ALTO** |
| 9 | **CORS com `allow_headers=["*"]`** | `api/main.py:628` | ✅ CONFIRMADO — Mas `allow_origins` é restrito por regex a `capivarex.com`. Risco aceitável mas deve ser melhorado. | **MÉDIO** |
| 10 | **API keys podem vazar em stack traces** | `api/routes/upload.py, webapp.py` | ⚠️ PARCIAL — Sentry captura exceptions que podem conter secrets nos args. Loguru pode logar mensagens com tokens. | **ALTO** |
| 11 | **Subprocess herda variáveis de ambiente** | `services/infrastructure/code_executor.py:165` | ✅ CONFIRMADO — `subprocess.run()` sem `env={}`. User code pode acessar `OPENAI_API_KEY`, `SUPABASE_SERVICE_KEY`, etc. | **ALTO** |

### 🟢 MÉDIAS (Confirmadas: 3 de 4)

| # | Vulnerabilidade | Ficheiro | Status |
|---|----------------|----------|--------|
| 12 | Encryption key regenerada a cada deploy em dev | `utils/encryption.py:31-34` | ✅ CONFIRMADO — Gera key temporária se ENCRYPTION_KEY não existe. Dados encriptados ficam ilegíveis após redeploy. |
| 13 | IDs de conversação sem validação UUID | `api/routes/chat.py` | ⚠️ PARCIAL — Precisa verificar formato UUID antes de queries. |
| 14 | OAuth state sem assinatura CSRF | `services/auth/google_oauth_service.py` | ✅ CONFIRMADO — State é random mas não assinado. |
| 15 | Bcrypt trunca senhas > 72 bytes | `api/routes/auth.py:227-233` | ✅ CONFIRMADO — Comportamento padrão do bcrypt. Risco baixo na prática. |

---

## PROBLEMAS DE QUALIDADE DE CÓDIGO

### 🔴 CRÍTICOS

| # | Problema | Ficheiro | Status |
|---|---------|----------|--------|
| 1 | **Race condition no Timer Service** | `timer_service.py:192-194` | ✅ CONFIRMADO — read/modify/write sem lock atómico no Redis. |
| 2 | **Chamadas Supabase síncronas em async** | `api/main.py:527,659` | ✅ CONFIRMADO — `client.table().select()` bloqueia event loop. Deve usar `asyncio.to_thread`. |
| 3 | **Fire-and-forget tasks sem error handling** | `webapp.py, voice_ws.py` | ✅ CONFIRMADO — `asyncio.create_task()` sem exception handler. |

### 🟡 ALTOS

| # | Problema | Ficheiro | Status |
|---|---------|----------|--------|
| 4 | `except Exception: pass` em múltiplos locais | `main.py, webapp.py` | ✅ CONFIRMADO |
| 5 | Temp files não limpos em exceção | `voice_ws.py` | ✅ CONFIRMADO |
| 6 | Variáveis de ambiente não validadas no startup | `main.py` | ✅ CONFIRMADO |
| 7 | Dados sensíveis no log | `main.py, chat_service.py` | ⚠️ PARCIAL — Loguru pode logar user messages |

---

## PLANO DE EXECUÇÃO

### Sprint 1 — Segurança Crítica (AGORA)

| # | Fix | Esforço | Risco |
|---|-----|---------|-------|
| **F1** | JWT_SECRET_KEY: crash no startup se vazio em produção | 5 min | Zero |
| **F2** | Rate limiter: `verify_signature: True` + decode com SECRET_KEY | 10 min | Baixo |
| **F3** | `/dev/test`: mudar para `get_admin_user` | 2 min | Zero |
| **F4** | Webhook email: adicionar HMAC signature ou API key header | 15 min | Baixo |
| **F5** | Code executor: `env={}` no subprocess (sandbox isolado) | 5 min | Zero |
| **F6** | Admin token: `hmac.compare_digest` | 2 min | Zero |

### Sprint 2 — Segurança Alta

| # | Fix | Esforço |
|---|-----|---------|
| **F7** | CORS: restringir `allow_headers` a lista específica | 5 min |
| **F8** | Stack trace sanitization: filtrar secrets antes de Sentry | 15 min |
| **F9** | WebSocket: `verify_aud: True` ou remover option | 5 min |
| **F10** | OAuth state: HMAC-signed CSRF state | 20 min |

### Sprint 3 — Qualidade de Código

| # | Fix | Esforço |
|---|-----|---------|
| **F11** | Timer: Redis WATCH/MULTI ou Lua script para atomicidade | 30 min |
| **F12** | Supabase sync→async: wrap com `asyncio.to_thread` | 15 min |
| **F13** | Fire-and-forget: add exception handlers em `create_task` | 15 min |
| **F14** | `except Exception: pass` → logging adequado | 10 min |
| **F15** | Temp files: usar `try/finally` com cleanup | 10 min |
| **F16** | Env var validation no startup | 15 min |

### Sprint 4 — Frontend (Futuro)

| # | Fix | Esforço |
|---|-----|---------|
| **F17** | Content Security Policy | 20 min |
| **F18** | Markdown sanitization (DOMPurify) | 15 min |
| **F19** | Token refresh automático | 30 min |
| **F20** | CSRF protection | 20 min |
| **F21** | Memory leak ObjectURL | 5 min |

---

## SCORE AJUSTADO (após verificação)

| Categoria | Score Original | Score Real | Nota |
|-----------|---------------|------------|------|
| Segurança Backend | 4/10 | **5/10** | 2 falsos positivos removidos |
| Qualidade Backend | 6/10 | **6/10** | Confirmado |
| Arquitetura | 9/10 | **9/10** | Excelente |
| Testes Backend | 8/10 | **9/10** | Agora 3200+ testes, 79%+ |

**Após Sprint 1+2 (segurança): Score sobe para ~7/10**
**Após Sprint 3 (qualidade): Score sobe para ~8/10**
