# SuperBot God - Guia de Configuração Completo

Este guia irá ajudá-lo a configurar e executar o SuperBot God no seu computador.

---

## 📋 Pré-requisitos

Antes de começar, certifique-se de ter instalado:

- **Python 3.11+** ([Download](https://www.python.org/downloads/))
- **Git** ([Download](https://git-scm.com/downloads))
- Uma conta no **Supabase** ([Criar conta](https://supabase.com/))
- Uma conta no **Upstash Redis** ([Criar conta](https://upstash.com/))

---

## 🚀 Passo a Passo

### 1. Extrair o Projeto

Extraia o arquivo ZIP do projeto para uma pasta de sua escolha.

```bash
# Exemplo no Windows:
# Extrair para: C:\Projects\superbot-god\

# Exemplo no Linux/Mac:
# Extrair para: ~/Projects/superbot-god/
```

### 2. Criar Ambiente Virtual

Abra um terminal na pasta do projeto e crie um ambiente virtual Python:

```bash
cd "caminho/para/superbot god"

# Criar ambiente virtual
python -m venv .venv

# Ativar ambiente virtual
# No Windows:
.venv\Scripts\activate

# No Linux/Mac:
source .venv/bin/activate
```

### 3. Instalar Dependências

Com o ambiente virtual ativado, instale as dependências:

```bash
pip install -r requirements.txt
```

### 4. Configurar Variáveis de Ambiente

1. Copie o arquivo `.env.example` e renomeie para `.env`
2. Abra o arquivo `.env` e preencha suas credenciais:

```env
# Chaves de API de IA
OPENAI_API_KEY="sk-..."
ANTHROPIC_API_KEY="sk-ant-..."
SONAR_API_KEY="pplx-..."
GEMINI_API_KEY="..."
ELEVENLABS_API_KEY="..."

# Banco de Dados e Cache
SUPABASE_URL="https://seu-projeto.supabase.co"
SUPABASE_KEY="sua-chave-supabase"
REDIS_URL="redis://..."

# Telegram Bot
TELEGRAM_BOT_TOKEN="seu-token-do-telegram"

# Outros
WEATHER_API_KEY="..."
TWELVE_DATA_API_KEY="..."
```

### 5. Configurar Google Calendar (Opcional)

Se você deseja usar a integração com Google Calendar:

1. Acesse o [Google Cloud Console](https://console.cloud.google.com/)
2. Crie um novo projeto ou selecione um existente
3. Ative a **Google Calendar API**
4. Crie uma **Service Account**
5. Baixe o arquivo JSON de credenciais
6. Renomeie o arquivo para `service_account.json`
7. Coloque o arquivo na raiz do projeto (pasta "superbot god")
8. Compartilhe seu Google Calendar com o email da Service Account

### 6. Configurar Banco de Dados Supabase

1. Acesse seu projeto no [Supabase](https://supabase.com/)
2. Vá em **SQL Editor**
3. Execute o seguinte script para criar as tabelas:

```sql
-- Tabela de usuários
CREATE TABLE users (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    plan TEXT DEFAULT 'basic',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabela de conversas
CREATE TABLE conversations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id UUID REFERENCES users(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Tabela de mensagens
CREATE TABLE messages (
    id BIGSERIAL PRIMARY KEY,
    conversation_id UUID REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

-- Índices para performance
CREATE INDEX idx_messages_conversation ON messages(conversation_id);
CREATE INDEX idx_conversations_user ON conversations(user_id);
```

### 7. Criar um Bot no Telegram

1. Abra o Telegram e procure por **@BotFather**
2. Envie o comando `/newbot`
3. Siga as instruções para criar seu bot
4. Copie o **token** fornecido
5. Cole o token no arquivo `.env` na variável `TELEGRAM_BOT_TOKEN`

---

## ▶️ Executando o Projeto

### Opção 1: Executar Tudo de Uma Vez (Recomendado)

Use o script `start_all.sh` para iniciar backend e Telegram bot juntos:

```bash
# No Linux/Mac:
./start_all.sh

# No Windows (use Git Bash ou WSL):
bash start_all.sh
```

### Opção 2: Executar Separadamente

**Terminal 1 - Backend:**
```bash
# No Linux/Mac:
./start_backend.sh

# No Windows:
bash start_backend.sh

# Ou manualmente:
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000
```

**Terminal 2 - Telegram Bot:**
```bash
# No Linux/Mac:
./start_telegram.sh

# No Windows:
bash start_telegram.sh

# Ou manualmente:
python telegram_bot.py
```

---

## ✅ Verificando se Está Funcionando

1. **Backend:** Acesse http://localhost:8000/docs
   - Você deve ver a documentação interativa da API (Swagger)

2. **Telegram Bot:** Envie uma mensagem para seu bot no Telegram
   - Exemplo: "Olá!"
   - O bot deve responder

3. **Google Calendar:** Envie uma mensagem relacionada ao calendário
   - Exemplo: "O que tenho na minha agenda hoje?"
   - O bot deve consultar seu calendário

---

## 🐛 Problemas Comuns

### Erro: "Virtual environment not found"

**Solução:** Certifique-se de ter criado o ambiente virtual:
```bash
python -m venv .venv
```

### Erro: "Module not found"

**Solução:** Instale as dependências:
```bash
pip install -r requirements.txt
```

### Erro: ".env file not found"

**Solução:** Copie o arquivo `.env.example` para `.env` e preencha as credenciais.

### Erro: "Backend is not running"

**Solução:** Inicie o backend primeiro antes de iniciar o Telegram bot.

### Bot não responde no Telegram

**Soluções:**
1. Verifique se o token do bot está correto no `.env`
2. Verifique se o backend está rodando (http://localhost:8000/api/health)
3. Verifique os logs no terminal

---

## 📚 Próximos Passos

Após configurar tudo:

1. Teste todas as funcionalidades do bot
2. Personalize as respostas editando os agents
3. Adicione novas integrações conforme necessário
4. Leia o `ROADMAP_UPDATED.md` para ver o que está planejado

---

## 🆘 Precisa de Ajuda?

Se encontrar problemas:

1. Verifique os logs no terminal
2. Consulte a documentação da API em http://localhost:8000/docs
3. Revise este guia novamente
4. Entre em contato com o desenvolvedor

---

**Boa sorte e divirta-se com o SuperBot God! 🚀**
