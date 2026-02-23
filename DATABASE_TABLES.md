# Tabelas do Banco de Dados — Capivarex

Este documento lista **todas as 25 tabelas** que o repositório utiliza no banco de dados (Supabase / PostgreSQL).

> **SQL completo:** O arquivo [`migrations/000_all_tables.sql`](migrations/000_all_tables.sql) contém o `CREATE TABLE` de todas as 25 tabelas prontas para executar no SQL Editor do Supabase.

## Resumo

| #  | Tabela                     | Origem / Arquivo de referência                          |
|----|----------------------------|---------------------------------------------------------|
| 1  | `users`                    | `SETUP_GUIDE.md`, `services/infrastructure/database.py`, `api/routes/auth.py` |
| 2  | `conversations`            | `SETUP_GUIDE.md`, `api/routes/chat.py`                  |
| 3  | `messages`                 | `SETUP_GUIDE.md`, `api/routes/chat.py`, `services/infrastructure/database.py` |
| 4  | `user_vehicles`            | `migrations/001_create_user_vehicles.sql`, `services/business/vehicle_db_service.py` |
| 5  | `memories`                 | `migrations/002_create_memories.sql`, `bot/core/memory.py` |
| 6  | `memory_audit_log`         | `migrations/002_create_memories.sql`, `bot/core/memory.py` |
| 7  | `identity_map`             | `migrations/003_create_identity_map.sql`, `bot/core/tenancy.py` |
| 8  | `notes`                    | `services/business/notes_service.py`, `api/routes/notes.py` |
| 9  | `reminders`                | `services/business/reminder_service.py`                 |
| 10 | `proactivity_preferences`  | `services/infrastructure/database.py`                   |
| 11 | `user_context`             | `services/infrastructure/database.py`                   |
| 12 | `car_connections`          | `services/infrastructure/database.py`                   |
| 13 | `smartthings_connections`  | `services/infrastructure/database.py`                   |
| 14 | `calendar_connections`     | `services/infrastructure/database.py`                   |
| 15 | `github_connections`       | `services/infrastructure/database.py`                   |
| 16 | `smartthings_tokens`       | `api/routes/smartthings.py`, `services/business/proactivity_service.py` |
| 17 | `smartthings_devices`      | `api/routes/smartthings.py`                             |
| 18 | `email_inbox`              | `agents/specialized/email_agent.py`                     |
| 19 | `twilio_calls`             | `services/integrations/twilio_service.py`               |
| 20 | `tenant_subscriptions`     | `services/business/quota_service.py`                    |
| 21 | `tenant_usage`             | `services/business/quota_service.py`                    |
| 22 | `tenant_usage_log`         | `services/business/quota_service.py`                    |
| 23 | `mercado_compras`          | `services/business/mercado_service.py`                  |
| 24 | `mercado_itens`            | `services/business/mercado_service.py`                  |
| 25 | `projects`                 | `api/routes/workspace.py`                               |

---

## Detalhes por categoria

### 1. Tabelas principais (core)

#### `users`
- **Referência:** `SETUP_GUIDE.md` (linhas 105-111), `services/infrastructure/database.py`, `api/routes/auth.py`
- **Descrição:** Cadastro e autenticação de usuários.

#### `conversations`
- **Referência:** `SETUP_GUIDE.md` (linhas 114-120), `api/routes/chat.py`
- **Descrição:** Armazena as conversas dos usuários.

#### `messages`
- **Referência:** `SETUP_GUIDE.md` (linhas 123-129), `api/routes/chat.py`, `services/infrastructure/database.py`
- **Descrição:** Histórico de mensagens dentro de cada conversa.

### 2. Veículos / Smartcar

#### `user_vehicles`
- **Referência:** `migrations/001_create_user_vehicles.sql`, `services/business/vehicle_db_service.py`
- **Descrição:** Veículos vinculados via integração Smartcar. Tem migration SQL dedicada com RLS.

#### `car_connections`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Conexões OAuth (tokens) do Smartcar por usuário.

### 3. Memória e identidade

#### `memories`
- **Referência:** `migrations/002_create_memories.sql`, `bot/core/memory.py`
- **Descrição:** Memórias do bot (curto prazo, longo prazo, factual) por usuário. Tem migration SQL dedicada com RLS.

#### `memory_audit_log`
- **Referência:** `migrations/002_create_memories.sql`, `bot/core/memory.py`
- **Descrição:** Log de auditoria de acessos às memórias. Tem migration SQL dedicada com RLS.

#### `identity_map`
- **Referência:** `migrations/003_create_identity_map.sql`, `bot/core/tenancy.py`
- **Descrição:** Mapeamento de identidade multi-canal (telegram, webapp). Tem migration SQL dedicada com RLS.

### 4. Notas e lembretes

#### `notes`
- **Referência:** `services/business/notes_service.py`, `api/routes/notes.py`
- **Descrição:** Notas pessoais dos usuários (com tags, pin, arquivamento). Criada automaticamente pelo serviço.

#### `reminders`
- **Referência:** `services/business/reminder_service.py`
- **Descrição:** Lembretes agendados dos usuários.

### 5. Integrações IoT / Smart Home

#### `proactivity_preferences`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Preferências de proatividade do bot por usuário.

#### `user_context`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Dados de contexto do usuário (por tipo de contexto).

#### `smartthings_connections`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Conexões OAuth do SmartThings por usuário.

#### `smartthings_tokens`
- **Referência:** `api/routes/smartthings.py`, `services/business/proactivity_service.py`
- **Descrição:** Tokens de acesso do SmartThings.

#### `smartthings_devices`
- **Referência:** `api/routes/smartthings.py`
- **Descrição:** Dispositivos SmartThings cadastrados.

### 6. Integrações externas

#### `calendar_connections`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Credenciais do Google Calendar por usuário.

#### `github_connections`
- **Referência:** `services/infrastructure/database.py`
- **Descrição:** Conexões GitHub (username + token) por usuário.

#### `email_inbox`
- **Referência:** `agents/specialized/email_agent.py`
- **Descrição:** Caixa de entrada de e-mails processados pelo agente de e-mail.

#### `twilio_calls`
- **Referência:** `services/integrations/twilio_service.py`
- **Descrição:** Registro de chamadas telefônicas via Twilio.

### 7. Multi-tenancy e cotas

#### `tenant_subscriptions`
- **Referência:** `services/business/quota_service.py`
- **Descrição:** Assinaturas/planos dos tenants.

#### `tenant_usage`
- **Referência:** `services/business/quota_service.py`
- **Descrição:** Consumo de cotas dos tenants.

#### `tenant_usage_log`
- **Referência:** `services/business/quota_service.py`
- **Descrição:** Log detalhado de consumo de cotas.

### 8. Mercado (compras)

#### `mercado_compras`
- **Referência:** `services/business/mercado_service.py`
- **Descrição:** Registros de compras de supermercado.

#### `mercado_itens`
- **Referência:** `services/business/mercado_service.py`
- **Descrição:** Itens de cada compra de supermercado.

### 9. Workspace

#### `projects`
- **Referência:** `api/routes/workspace.py`
- **Descrição:** Projetos do workspace do usuário.
