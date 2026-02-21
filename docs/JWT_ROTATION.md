# 🔐 Rotação do JWT_SECRET_KEY

## O que é e por que importa

`JWT_SECRET_KEY` é a chave usada pelo `api/dependencies/auth.py` para **assinar e verificar todos os tokens JWT** do projeto. Quem tiver essa chave consegue gerar tokens válidos para qualquer usuário — incluindo admins.

**Impacto de uma rotação:** todos os tokens emitidos com a chave antiga tornam-se inválidos imediatamente. Todos os usuários logados precisarão fazer login novamente.

---

## Quando rotacionar

| Situação | Urgência |
|---|---|
| Chave exposta em log, commit, Slack, e-mail, etc. | **Imediata** — rotacione agora |
| Suspeita de acesso não autorizado à API | **Imediata** |
| Saída de membro do time com acesso ao `.env` de produção | Dentro de 24h |
| Rotina de segurança periódica | A cada 90 dias (recomendado) |
| Upgrade de algoritmo (ex: HS256 → RS256) | Planejado, com aviso aos usuários |

---

## Como gerar uma nova chave segura

Use **qualquer um** dos métodos abaixo. A chave deve ter no mínimo 32 bytes (256 bits).

```bash
# Opção 1 — Python (recomendado, sem deps extras)
python -c "import secrets; print(secrets.token_hex(64))"

# Opção 2 — OpenSSL
openssl rand -hex 64

# Opção 3 — Python base64 (mais curto, igualmente seguro)
python -c "import secrets, base64; print(base64.urlsafe_b64encode(secrets.token_bytes(64)).decode())"
```

Exemplo de saída (NÃO use este valor):
```
a3f8c2e1d4b7...  # 128 chars hex = 64 bytes = 512 bits
```

---

## Rotação padrão (com downtime mínimo)

Esta é a forma mais simples. Todos os tokens existentes são invalidados no momento da troca.

### Passo a passo

**1. Gerar nova chave:**
```bash
python -c "import secrets; print(secrets.token_hex(64))"
# Copie o valor gerado — ex: NEW_KEY="a3f8c2e1..."
```

**2. Atualizar o `.env` local e de produção:**
```bash
# .env (desenvolvimento)
JWT_SECRET_KEY=<nova_chave_aqui>

# Produção: atualizar a variável de ambiente no seu provider
# (Railway, Render, Heroku, AWS, etc.) antes de reiniciar
```

**3. Reiniciar a API:**
```bash
# Docker Compose
docker-compose restart api

# Sem Docker
uvicorn api.main:app --reload ...

# Produção (ex: Railway)
railway up  # ou redeploy pelo dashboard
```

**4. Verificar que a API subiu com a nova chave:**
```bash
curl -s http://localhost:8000/health | python -m json.tool
# Deve retornar {"status": "ok", ...}
```

**5. Testar login com credenciais válidas:**
```bash
curl -X POST http://localhost:8000/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email": "seu@email.com", "password": "sua_senha"}' \
  | python -m json.tool
# Deve retornar {"access_token": "eyJ...", "token_type": "bearer"}
```

**6. Confirmar que tokens antigos são rejeitados:**
```bash
# Com um token gerado ANTES da rotação
curl -H "Authorization: Bearer eyJ_TOKEN_ANTIGO..." \
  http://localhost:8000/api/auth/me
# Deve retornar HTTP 401 Unauthorized
```

---

## Rotação sem downtime (grace period com dois tokens)

Para produção com usuários ativos, onde não é aceitável invalidar sessões abruptamente.

### Estratégia: aceitar tanto a chave antiga quanto a nova por um período

**1.** Adicione `JWT_SECRET_KEY_OLD` no `.env` com o valor atual antes de rotacionar:
```bash
JWT_SECRET_KEY_OLD=<chave_atual>  # ← adicionar
JWT_SECRET_KEY=<nova_chave>       # ← atualizar
```

**2.** Modifique temporariamente `api/dependencies/auth.py` para tentar as duas chaves:

```python
# api/dependencies/auth.py — TEMPORÁRIO durante grace period
SECRET_KEY: str = os.environ.get("JWT_SECRET_KEY", "")
SECRET_KEY_OLD: str = os.environ.get("JWT_SECRET_KEY_OLD", "")

async def get_current_user(token: ...) -> Dict[str, Any]:
    credentials_exception = HTTPException(status_code=401, ...)

    payload = None
    for key in filter(None, [SECRET_KEY, SECRET_KEY_OLD]):
        try:
            payload = jwt.decode(token, key, algorithms=[ALGORITHM])
            break
        except PyJWTError:
            continue

    if payload is None:
        raise credentials_exception
    # ... resto da função igual
```

**3.** Deploy com esse código. Agora:
- Novos logins geram tokens com a chave nova ✅
- Tokens antigos ainda são aceitos ✅

**4.** Após o período de grace (recomendado: 24–48h para expirar os tokens antigos):
- Remova `JWT_SECRET_KEY_OLD` do `.env`
- Remova o código de fallback do `auth.py`
- Redeploy

---

## Checklist de rotação

```
[ ] 1. Gerar nova chave (≥ 32 bytes, aleatória)
[ ] 2. Atualizar JWT_SECRET_KEY no .env de PRODUÇÃO
[ ] 3. Atualizar JWT_SECRET_KEY no .env de DESENVOLVIMENTO
[ ] 4. Atualizar JWT_SECRET_KEY em CI/CD (GitHub Secrets, etc.) se aplicável
[ ] 5. Reiniciar a API
[ ] 6. Testar login → novo token gerado com sucesso
[ ] 7. Confirmar token antigo retorna 401
[ ] 8. Comunicar usuários se impacto for significativo (opcional)
[ ] 9. Revogar/deletar a chave antiga de qualquer secret manager
```

---

## Onde a chave é usada no código

| Arquivo | Uso |
|---|---|
| `api/dependencies/auth.py` | `jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])` — verificação |
| `api/routes/auth.py` | `jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)` — geração |

Se adicionar novos pontos que usam a chave, documente aqui.

---

## Boas práticas permanentes

- **Nunca commite a chave real** no git — use apenas `sua_chave_jwt_secreta_aqui` no `.env.example`
- **Use um secret manager** em produção: AWS Secrets Manager, GCP Secret Manager, Doppler, ou equivalente
- **Defina JWT_EXPIRATION_MINUTES** adequadamente — padrão atual é 60 min. Tokens de vida curta reduzem o impacto de um vazamento
- **Alerte se `SECRET_KEY` estiver vazio** — o código em `auth.py` já faz isso via `logger.error`
- **Não use a mesma chave** em desenvolvimento e produção

---

## Algoritmo atual e evolução futura

O projeto usa **HS256** (HMAC-SHA256 — chave simétrica). É seguro para uso atual.

Se o projeto crescer para múltiplos serviços que precisam verificar tokens **sem** ter acesso à chave secreta (ex: microsserviços), considere migrar para **RS256** (RSA — chave assimétrica). A mudança requer:
1. Gerar par de chaves RSA: `openssl genrsa -out private.pem 2048`
2. Atualizar `JWT_ALGORITHM=RS256` no `.env`
3. Passar `private_key` para encode e `public_key` para decode em `auth.py`
