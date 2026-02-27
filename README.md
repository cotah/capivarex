# Capivarex — Your Proactive AI Life Assistant

Capivarex is a "Jarvis-like" proactive AI assistant that integrates multiple services and provides contextual, intelligent assistance across various interfaces. It manages your daily life — from scheduling meetings and booking flights to controlling your smart home and making phone calls.

## 🚀 Features

### Core
- **Multi-Agent System**: Sophisticated orchestrator routes requests to 12+ specialized AI agents
- **Proactive Assistance**: Initiates conversations and provides briefings based on your context
- **Multi-Language**: Full i18n support for English, Portuguese, and Spanish
- **Persistent Memory**: Remembers your name, preferences, and personal info across all conversations
- **Multi-Interface**: Telegram Bot, REST API, WebSocket — designed for future WebApp (PWA) and smartwatch

### ✅ Implemented Agents & Services

| Agent | Description | Integration |
|-------|-------------|-------------|
| 💬 **Chat** | Conversational AI | OpenAI GPT-4.1-mini / GPT-5-mini |
| 📅 **Calendar** | Read/create events, scheduling | Google Calendar API |
| 🏠 **SmartHome** | Control lights, sensors, locks | SmartThings OAuth2 (auto-refresh) |
| ✈️ **Travel** | Flight search with booking links | Duffel API + Google Flights |
| 🏨 **Hotels** | Hotel search with pre-filled links | Booking.com |
| 🚗 **Car** | EV battery, location, charging, locks | Smartcar API |
| 🌤 **Weather** | Real-time forecasts | OpenWeatherMap |
| 💰 **Finance** | Real-time stock quotes | Finance APIs |
| 🔍 **Research** | Web search & synthesis | Perplexity AI |
| 💻 **Dev** | Code generation & explanation | Anthropic Claude |
| 🐙 **GitHub** | Create repos, manage code | GitHub API |
| 📞 **Twilio** | Make phone calls via Telegram | Twilio API |
| 🖼 **Image** | Generate images from text | Google Gemini |
| 🎬 **Video** | Generate videos from text | Google Gemini Veo 3.1 |
| 🗣 **Voice** | Text-to-speech | ElevenLabs |
| 🚌 **Transport** | Public transport info | Transport APIs |

### ⏳ Planned
- **Google Maps Traffic**: Real-time traffic alerts
- **Spotify**: Music control
- **Gmail**: Email management
- **WhatsApp Business**: Messaging
- **Virtual Avatar**: D-ID powered web avatar
- **WebApp (PWA)**: Full dashboard with settings

## 🔧 Tech Stack

| Layer | Technology |
|-------|-----------|
| **Backend** | Python 3.11, FastAPI |
| **Database** | Supabase (PostgreSQL) |
| **Cache** | Upstash Redis |
| **Auth** | JWT (JSON Web Tokens) |
| **AI Models** | OpenAI GPT-4.1-mini/GPT-5-mini, Anthropic Claude, Perplexity, Google Gemini |
| **Interfaces** | Telegram Bot, REST API, WebSockets |
| **Deploy** | Railway |
| **CI/Testing** | pytest (1700+ tests, ~79% coverage), ruff |

## 🏗 Architecture

```mermaid
flowchart LR
    A["Entry Point\n(API / Telegram Bot)"] --> B["Gateway\n(RequestProcessor)"]
    B --> C["OrchestratorAgent"]
    C --> D["Specialized Agent"]
    D --> E["Infrastructure Service"]
    E --> F["Response"]
```

### Directory Structure

| Layer | Directory | Responsibility |
|-------|-----------|---------------|
| API | `api/` | REST endpoints & WebSocket (FastAPI), JWT auth |
| Telegram Bot | `telegram_bot/` | Telegram interface, message handlers |
| Gateway | `utils/request_processor.py` | Request ID, rate limiting, user context |
| Orchestrator | `agents/specialized/orchestrator_agent.py` | Intent analysis, agent routing |
| Specialized Agents | `agents/specialized/` | One agent per domain (calendar, car, chat, dev, etc.) |
| Business Services | `services/business/` | ChatService, ProactivityService, UserProfileService, PromptCleaner |
| Infrastructure | `services/infrastructure/` | Database (Supabase), Redis, Git, FileManager, Notifications |
| Integrations | `services/integrations/` | Google Calendar, Smartcar, Weather, SmartThings, Duffel, Traffic |
| AI Services | `services/ai/` | OpenAI, Anthropic (Claude), Perplexity, ElevenLabs |
| Media Services | `services/media/` | Image, Video, Whisper (transcription) |
| i18n | `services/i18n/` | Internationalization (EN/PT/ES) |
| Autofix | `autofix/` | Autonomous bug triage and patching |
| Worker | `worker.py` | Async task processing via arq + Redis |

### Architectural Patterns
- **Service Registry** — All services register via `@register_service` and are accessed by `get_service(name)`
- **Agent Registry** — Agents register via `@register_agent` and are accessed by `get_agent(name)`
- **Circuit Breaker** — External integrations protected by `pybreaker`
- **Strategy Pattern** — Dictionary-based dispatch in ChatService and autofix
- **RequestProcessor** — Unified gateway for rate limiting, context, and observability

## 🚀 Getting Started

### Prerequisites
- Python 3.11+
- Supabase account
- Upstash Redis account
- API keys for services (OpenAI, Google, Perplexity, etc.)

### Installation

```bash
# Clone the repository
git clone https://github.com/cotah/capivarex.git
cd capivarex

# Create virtual environment
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Configure environment
cp .env.example .env
# Edit .env with your API keys

# Configure Google credentials
cp credentials.example.json credentials.json
cp service_account.example.json service_account.json
# Edit JSON files with your Google Cloud Console credentials
```

> ⚠️ **Never commit** `.env`, `credentials.json`, or `service_account.json` to Git.

### Running with Docker (Recommended)

```bash
./start_all.sh
```
API available at `http://localhost:8000` — docs at `http://localhost:8000/docs`.

### Running without Docker

```bash
# API server
uvicorn api.main:app --reload --host 0.0.0.0 --port 8000

# Telegram bot
python telegram_bot/main.py

# Background worker (optional, requires Redis)
arq worker.WorkerSettings
```

### Running Tests

```bash
pytest tests/ -v
```

## 🔒 Security

### JWT Authentication
All API endpoints are protected by JWT. Generate a secure key:
```bash
python -c "import secrets; print(secrets.token_hex(64))"
```

Rotate the key if: exposed in a commit/log, suspected unauthorized access, team member leaves, or every 90 days. See `docs/JWT_ROTATION.md` for zero-downtime rotation.

### Environment Variables
All credentials stored via environment variables. For production, use a secret manager (AWS Secrets Manager, GCP Secret Manager, Doppler).

| Variable | Description |
|----------|-------------|
| `JWT_SECRET_KEY` | Signs/verifies JWT tokens (≥ 32 bytes random) |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | Supabase service role key |
| `REDIS_URL` | Upstash Redis URL |
| `SMARTTHINGS_CLIENT_ID` | SmartThings OAuth2 client ID |
| `SMARTTHINGS_CLIENT_SECRET` | SmartThings OAuth2 client secret |
| `DUFFEL_ACCESS_TOKEN` | Duffel API token (flights) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |

See `.env.example` for the full list.

## 🤝 Contributing

1. Fork the project
2. Create your feature branch (`git checkout -b feature/AmazingFeature`)
3. Commit your changes (`git commit -m 'Add some AmazingFeature'`)
4. Push to the branch (`git push origin feature/AmazingFeature`)
5. Open a Pull Request

Please follow the existing code style and add tests for new functionality.

## 📄 License

MIT License — see [LICENSE](LICENSE) for details.
