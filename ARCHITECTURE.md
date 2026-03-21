# CAPIVAREX — Complete Architecture Reference

> **Version:** 5.0-CAPIVARA-MODULES
> **Last updated:** March 21, 2026
> **Based on:** Full codebase scan — 414 Python files, 84,456 lines of code
> **Purpose:** The definitive source of truth. Any AI or developer reading this understands 100% of the project.
> **Repos:** `cotah/capivarex` (backend), `cotah/capivarex-frontend` (frontend), `cotah/capivarex-admin` (admin)

---

## Table of Contents

1. [What is CAPIVAREX?](#1-what-is-capivarex)
2. [Tech Stack](#2-tech-stack)
3. [Project Structure](#3-project-structure)
4. [All 34 Agents](#4-all-34-agents)
5. [All External APIs (29 integrations)](#5-all-external-apis-29-integrations)
6. [All Environment Variables (64 vars)](#6-all-environment-variables-64-vars)
7. [All Supabase Tables (33 tables)](#7-all-supabase-tables-33-tables)
8. [All Services (101 files)](#8-all-services-101-files)
9. [All API Routes (34 route files, 160+ endpoints)](#9-all-api-routes-34-route-files-160-endpoints)
10. [Proactive vs Reactive Features](#10-proactive-vs-reactive-features)
11. [The Proactivity Loop (8 steps)](#11-the-proactivity-loop-8-steps)
12. [Background Worker (Arq)](#12-background-worker-arq)
13. [Message Flow Architecture](#13-message-flow-architecture)
14. [Communication Channels](#14-communication-channels)
15. [Plans and Billing](#15-plans-and-billing)
16. [Internationalization (i18n)](#16-internationalization-i18n)
17. [Security Architecture](#17-security-architecture)
18. [Bot Modes and Personas](#18-bot-modes-and-personas)
19. [Autofix System](#19-autofix-system)
20. [Deployment](#20-deployment)
21. [Feature Roadmap Status](#21-feature-roadmap-status)
22. [Test Metrics](#22-test-metrics)

---

## 1. What is CAPIVAREX?

CAPIVAREX is an AI-powered personal life assistant. Users interact via **WebApp (app.capivarex.com)**, **Telegram**, or **WhatsApp**. The bot understands natural language in Portuguese, English, and Spanish, then routes requests to 34 specialized agents that handle everything from calendar management to package tracking to smart home control.

**Key differentiator:** The bot is **proactive** — it doesn't just respond to commands. It monitors your email, calendar, finances, packages, weather, and context, then sends alerts and suggestions before you ask. It also adapts its tone based on your mood, knows when not to bother you (meetings, sleep, focus mode), and remembers things you mentioned to follow up later.

**Owner:** Henrique Pasquetto (cotah)
**Repos:** `cotah/capivarex` (backend), `cotah/capivarex-frontend` (frontend)
**Production:** `capivarex-production.up.railway.app` (API), `app.capivarex.com` (frontend)

---

## 2. Tech Stack

| Layer | Technology | Details |
|-------|-----------|---------|
| **Backend Framework** | Python 3.11 + FastAPI 0.129 | Async, high-performance REST API |
| **Frontend** | Next.js 14 (TypeScript) | React, Tailwind CSS, on Vercel |
| **Database** | Supabase (PostgreSQL) | 46 tables, Row Level Security |
| **Cache / Queue** | Redis (Upstash) | Timers, rate limiting, conversation cache, sessions |
| **Primary AI** | OpenAI GPT-5.4-mini | Chat, all agents, intent detection |
| **Orchestrator AI** | OpenAI GPT-5.4-nano | Intent routing (cheapest model) |
| **Secondary AI** | Anthropic Claude Sonnet 4.5 | Code generation (dev agent primary) |
| **Research AI** | Perplexity (Sonar) | Deep web research, news synthesis |
| **Vision AI** | Google Gemini | Image analysis, receipt scanning |
| **Voice TTS** | ElevenLabs (Multilingual v2) | Text-to-speech in multiple languages |
| **Voice STT** | OpenAI Whisper + Deepgram | Speech-to-text transcription |
| **Video AI** | Grok (xAI) + Google Gemini | Text-to-video, image-to-video |
| **Hosting** | Railway (backend) | Auto-deploy from GitHub |
| **Frontend Hosting** | Vercel | Auto-deploy, CDN, Edge Functions |
| **Payments** | Stripe | Checkout, subscriptions, webhooks |
| **Monitoring** | Sentry | Error tracking, performance |
| **Background Jobs** | Arq (Redis-based) | Image generation, timer checks, reminder checks |
| **Telegram Bot** | python-telegram-bot | Handlers, commands, callbacks |
| **WhatsApp** | Meta Cloud API (Graph API) | Business messaging, interactive buttons |
| **Package Tracking** | 17TRACK API v2 | 2600+ carriers worldwide |
| **Server** | Gunicorn + Uvicorn workers | Production ASGI server |

---

## 3. Project Structure

```
capivarex/                          # Root — 84,456 lines of Python
│
├── agents/                         # 34 specialized AI agents
│   ├── core/                       #   Base agent class + registry pattern
│   │   ├── __init__.py             #     Exports: BaseAgent, AgentResponse, AgentStatus, register_agent, get_agent
│   │   ├── agent_registry.py       #     Global agent registry (singleton dict)
│   │   └── base_agent.py           #     Abstract base: execute(), get_capabilities(), initialize()
│   ├── specialized/                #   All 34 agents (see Section 4)
│   ├── utils/                      #   Response formatters
│   │   └── formatters.py
│   └── registration.py             #   Auto-imports all agents on startup
│
├── api/                            # FastAPI application
│   ├── main.py                     #   App factory, 37 router mounts, CORS, startup/shutdown
│   ├── app_factory.py              #   Alternative factory (unused in prod)
│   ├── routes/                     #   34 route files, 160+ endpoints (see Section 9)
│   ├── middleware/                  #   6 middleware files
│   │   ├── autofix.py              #     Auto-captures exceptions for self-healing
│   │   ├── error_handler.py        #     Global exception handler
│   │   ├── logging.py              #     Request/response logging
│   │   ├── rate_limit.py           #     Per-user rate limiting (Redis)
│   │   ├── security_headers.py     #     CORS, CSP, HSTS headers
│   │   └── webapp_auth.py          #     JWT auth for webapp routes
│   └── dependencies/               #   FastAPI dependency injection
│       └── auth.py                 #     get_current_user, verify_token
│
├── services/                       # 101 service files — the brain
│   ├── ai/                         #   7 AI service wrappers
│   │   ├── anthropic_service.py    #     Claude API (code generation)
│   │   ├── call_brain.py           #     Phone call AI brain (real-time conversation)
│   │   ├── elevenlabs_service.py   #     TTS voice synthesis
│   │   ├── embedding_service.py    #     OpenAI text-embedding-3-small
│   │   ├── model_config.py         #     Central model name configuration
│   │   ├── openai_service.py       #     GPT-4o, GPT-4o-mini, DALL-E, Whisper
│   │   └── perplexity_service.py   #     Sonar research/news
│   ├── auth/                       #   3 OAuth services
│   │   ├── google_oauth_service.py #     Google Calendar + Gmail OAuth2
│   │   ├── spotify_oauth_service.py#     Spotify Connect OAuth2
│   │   └── tuya_oauth_service.py   #     Tuya Smart Home OAuth2
│   ├── business/                   #   43 business logic services (see Section 8)
│   ├── core/                       #   Service registry + base class
│   │   ├── base_service.py         #     Abstract: initialize(), health_check(), cleanup()
│   │   └── service_registry.py     #     Global service registry (register_service, get_service)
│   ├── i18n/                       #   Internationalization
│   │   ├── keywords.py             #     Multi-lang keyword detection for routing (PT/EN/ES)
│   │   ├── prompts.py              #     System prompts (orchestrator, chat)
│   │   └── strings.py              #     2950 lines — all user-facing strings in PT/EN/ES
│   ├── infrastructure/             #   9 infrastructure services
│   │   ├── code_executor.py        #     Sandboxed Python code execution
│   │   ├── database.py             #     Supabase client wrapper (719 lines)
│   │   ├── file_manager.py         #     File CRUD for workspace
│   │   ├── git_service.py          #     Git operations (clone, commit, push)
│   │   ├── notification_service.py #     Web push notifications (VAPID)
│   │   ├── redis_service.py        #     Upstash Redis wrapper (686 lines)
│   │   ├── resilience_service.py   #     Circuit breaker + retry patterns
│   │   ├── security_event_service.py#    Auth events, suspicious activity logging
│   │   └── sentry_service.py       #     Sentry error monitoring init
│   ├── integrations/               #   16 external API wrappers
│   │   ├── calendar_service.py     #     Google Calendar API
│   │   ├── car_service.py          #     Smartcar API (EV control)
│   │   ├── duffel_service.py       #     Duffel API (flights/hotels)
│   │   ├── finance_service.py      #     Twelve Data API (stocks)
│   │   ├── gmail_service.py        #     Gmail API (read/send)
│   │   ├── maps_service.py         #     Google Maps + Places API
│   │   ├── restaurant_service.py   #     Google Places (restaurants)
│   │   ├── spotify_service.py      #     Spotify Web API
│   │   ├── spotify_user_service.py #     Spotify user profile/playlists
│   │   ├── tracking_service.py     #     17TRACK API v2 (package tracking)
│   │   ├── traffic_service.py      #     Google Maps traffic
│   │   ├── transit_service.py      #     NTA Ireland GTFS-RT (875 lines)
│   │   ├── twilio_service.py       #     Twilio voice calls
│   │   ├── weather_service.py      #     WeatherAPI.com
│   │   ├── whatsapp_service.py     #     Meta Graph API (WhatsApp)
│   │   └── youtube_service.py      #     YouTube Data API v3
│   ├── media/                      #   5 media services
│   │   ├── grok_video_service.py   #     xAI Grok video generation
│   │   ├── image_service.py        #     DALL-E + Gemini image gen/analysis
│   │   ├── pdf_service.py          #     PDF generation
│   │   ├── video_service.py        #     Gemini video generation
│   │   └── whisper_service.py      #     OpenAI Whisper STT
│   ├── voice_pipeline_service.py   #   Real-time voice pipeline (WebSocket)
│   └── registration.py             #   Auto-registers all services on startup
│
├── bot/                            # Bot core module (v4.29-GOD)
│   ├── core/                       #   Config, memory, multi-tenancy
│   │   ├── config.py               #     ConfigManager
│   │   ├── memory.py               #     MemoryManager (Redis-backed)
│   │   └── tenancy.py              #     Multi-tenant support
│   ├── dev/                        #   DEV Agent system (Claude AI code gen)
│   │   ├── actions.py              #     Action types (create, edit, delete files)
│   │   ├── claude_client.py        #     Anthropic Claude API client
│   │   └── executor.py             #     Sandboxed action executor
│   ├── modes/                      #   Bot personas
│   │   └── definitions.py          #     6 modes: default, dev, rotina, marketing, finanças, criativo
│   └── utils/                      #   Utilities
│       ├── files.py                #     File operations
│       ├── git.py                  #     Git helpers
│       └── safety.py               #     Safety checks
│
├── telegram_bot/                   # Telegram bot
│   ├── core/                       #   Bot class
│   │   └── bot.py                  #     CAPIVAREXBot — main class, keyword routing
│   ├── handlers/                   #   7 message handlers
│   │   ├── document.py             #     Document/file handler
│   │   ├── email_callback.py       #     Email inline keyboard callbacks (623 lines)
│   │   ├── location.py             #     GPS location handler → saves to Supabase
│   │   ├── mercado_callback.py     #     Grocery list inline keyboard callbacks
│   │   ├── message.py              #     Main text message handler (521 lines)
│   │   ├── photo.py                #     Photo handler (receipt scanning, image analysis)
│   │   └── voice.py                #     Voice message handler (Whisper STT)
│   ├── commands/                   #   5 slash commands
│   │   ├── autofix.py              #     /autofix — view/manage bug tickets
│   │   ├── help.py                 #     /help — show available commands
│   │   ├── proactivity.py          #     /proactivity — toggle proactive features
│   │   ├── start.py                #     /start — initial setup, onboarding
│   │   └── status.py               #     /status — system health check
│   ├── utils/
│   │   ├── logger.py
│   │   └── response_sender.py      #     Telegram message sending with markdown
│   └── main.py                     #     Telegram bot entry point
│
├── autofix/                        # Self-healing system
│   ├── core.py                     #     Bug capture, ticket management, patch gen (2033 lines)
│   ├── github_pr.py                #     Auto-create GitHub PRs for fixes
│   └── notifier.py                 #     Alert admin of new bugs
│
├── schemas/                        # Pydantic schemas
│   ├── context.py                  #     UserContext (user_id, chat_id, locale, timezone, devices, GPS)
│   ├── calendar.py                 #     CalendarEventInput
│   └── orchestrator.py             #     OrchestratorDecision (agent + reason)
│
├── models/                         # Data models
│   └── schemas.py                  #     User, Note, Conversation, Message, Token, Project, Git models
│
├── utils/                          # Shared utilities
│   ├── audio_converter.py          #     OGG→WAV, format conversion
│   ├── encryption.py               #     Fernet encryption for OAuth tokens (ENCRYPTION_KEY)
│   ├── identity.py                 #     User identity helpers
│   ├── logger.py                   #     Loguru logger config
│   ├── logging_config.py           #     Standard logging config
│   ├── monitoring.py               #     Performance monitoring
│   ├── permissions.py              #     Permission checks
│   ├── rate_limiter.py             #     Token bucket rate limiter
│   ├── request_context.py          #     Request context propagation
│   ├── request_processor.py        #     Request processing pipeline
│   ├── safe_task.py                #     Fire-and-forget with error handling
│   └── worker_redis_adapter.py     #     Redis adapter for Arq worker
│
├── proactivity_loop.py             # Background proactive checks (8 steps, runs every ~5 min)
├── worker.py                       # Arq background worker (image gen, timers, reminders)
├── gunicorn_conf.py                # Gunicorn config (workers = CPU*2+1, port 8000)
├── requirements.txt                # Python dependencies
├── ROADMAP_TIERS.md                # Feature roadmap (60/79 complete)
└── ARCHITECTURE.md                 # This file
```

---

## 4. All 34 Agents

The **Orchestrator Agent** receives every user message and uses GPT to classify the intent, then routes to the correct specialized agent.

### Orchestrator-routable agents (32):

| # | Agent Name | File | Lines | What it does | Service dependency | External API |
|---|-----------|------|-------|-------------|-------------------|-------------|
| 1 | **orchestrator** | `orchestrator_agent.py` | 212 | Routes messages to correct agent via GPT intent classification | openai | OpenAI GPT-4o-mini |
| 2 | **chat** | `chat_agent.py` | 355 | General conversation, Q&A, fallback handler | openai, redis, database | OpenAI GPT-4o |
| 3 | **calendar** | `calendar_agent.py` | 569 | Create/query/manage Google Calendar events, traffic alerts | calendar, google_oauth | Google Calendar API |
| 4 | **car** | `car_agent.py` | 572 | EV battery, location, lock/unlock, charge control | car, database | Smartcar API |
| 5 | **crypto** | `crypto_agent.py` | 292 | Cryptocurrency prices, top coins, multi-currency | crypto | CoinGecko API (free) |
| 6 | **dev** | `dev_agent.py` | 664 | Code generation, review, debug (Claude primary, OpenAI fallback) | anthropic, openai | Anthropic Claude + OpenAI Codex |
| 7 | **email** | `email_agent.py` | 1311 | Read, reply, compose, poll Gmail. Connect accounts | gmail, email_polling, database | Gmail API |
| 8 | **finance** | `finance_agent.py` | 398 | Stock quotes, watchlists, price alerts | finance | Twelve Data API |
| 9 | **github** | `github_agent.py` | 680 | Git operations: clone, commit, push, branch, status | git, database | GitHub API |
| 10 | **image** | `image_agent.py` | 255 | AI image generation from text descriptions | image | OpenAI DALL-E 3 |
| 11 | **leaving_now** | `leaving_now_agent.py` | 470 | "When should I leave?" with real-time transit + traffic | leaving_now, calendar, transit, maps | NTA + Google Maps |
| 12 | **maps** | `maps_agent.py` | 778 | Directions, places search, nearby POIs | maps | Google Maps + Places API |
| 13 | **media_cast** | `media_cast_agent.py` | 223 | Cast content to TV/Chromecast, YouTube on TV | youtube, smarthome | YouTube + Tuya |
| 14 | **meeting** | `meeting_agent.py` | 461 | Create Google Meet meetings with calendar integration | calendar | Google Calendar API |
| 15 | **mercado** | `mercado_agent.py` | 517 | Grocery shopping lists, receipt scanning, monthly reports | mercado | Supabase |
| 16 | **music** | `music_agent.py` | 897 | Spotify: search, play, recommendations, artist info | spotify | Spotify Web API |
| 17 | **notes** | `notes_agent.py` | 454 | Create, edit, search, pin, delete notes | notes | Supabase |
| 18 | **reminder** | `reminder_agent.py` | 458 | Persistent reminders with recurrence (Supabase) | reminder | Supabase |
| 19 | **research** | `research_agent.py` | 194 | Deep web research, synthesis, news queries | perplexity | Perplexity Sonar API |
| 20 | **restaurant** | `restaurant_agent.py` | 696 | Find restaurants, reviews, details. Redis result cache | restaurant, redis | Google Places API |
| 21 | **search** | `search_agent.py` | 605 | Web search, shopping, places, news via Serper | search | Serper API (Google) |
| 22 | **smarthome** | `smarthome_agent.py` | 396 | Control smart home: lights, locks, thermostat, devices | smarthome, tuya_oauth | Tuya Cloud API |
| 23 | **time** | `time_agent.py` | 433 | Time zones, world clock, date queries | (none — stdlib) | None (Python zoneinfo) |
| 24 | **timer** | `timer_agent.py` | 367 | Ephemeral timers and alarms (Redis, checked every 10s) | timer | Redis (Upstash) |
| 25 | **tracking** | `tracking_agent.py` | 304 | Package tracking (2600+ carriers), quota check | tracking | 17TRACK API v2 |
| 26 | **traffic** | `traffic_agent.py` | 263 | Traffic conditions, commute duration estimates | traffic | Google Maps API |
| 27 | **translate** | `translate_agent.py` | 229 | Text translation, language detection | translate | OpenAI GPT-4o |
| 28 | **transport** | `transport_agent.py` | 332 | Public transport: bus, DART, Luas, train in Ireland | transit | NTA GTFS-RT API |
| 29 | **travel** | `travel_agent.py` | 515 | Flight search, hotel search, price comparison | duffel | Duffel API |
| 30 | **twilio** | `twilio_agent.py` | 480 | Make phone calls, AI voice conversations | twilio, database | Twilio API |
| 31 | **video** | `video_agent.py` | 179 | AI video generation (text-to-video, image-to-video) | grok_video, video | xAI Grok + Gemini |
| 32 | **voice** | `voice_agent.py` | 301 | Text-to-speech audio messages, speech-to-text | elevenlabs, openai | ElevenLabs + Whisper |

### Non-orchestrator agents (2 — called directly by keyword detection):

| # | Agent Name | File | Lines | What it does |
|---|-----------|------|-------|-------------|
| 33 | **weather** | `weather_agent.py` | 608 | Weather: current, forecast, alerts, UV, wind. GPS auto-detect | WeatherAPI |
| 34 | **youtube** | `youtube_agent.py` | 400 | YouTube: search, trending, play videos | YouTube Data API v3 |

**Total agent code:** ~14,000 lines

---

## 5. All External APIs (29 integrations)

| # | API Provider | Base URL | Env Var(s) | Used by | What for |
|---|-------------|----------|-----------|---------|----------|
| 1 | **OpenAI** | `api.openai.com` | `OPENAI_API_KEY` | chat, orchestrator, image, dev, voice, translate, all AI features | GPT-4o, GPT-4o-mini, DALL-E 3, Whisper, Codex |
| 2 | **Anthropic** | `api.anthropic.com` | `ANTHROPIC_API_KEY` | dev agent, autofix | Claude Sonnet 4.5 (code generation) |
| 3 | **Perplexity** | `api.perplexity.ai` | `SONAR_API_KEY` | research agent, news | Sonar model for web research |
| 4 | **Google Gemini** | `generativelanguage.googleapis.com` | `GEMINI_API_KEY` | image analysis, video gen | Vision AI, image understanding |
| 5 | **ElevenLabs** | `api.elevenlabs.io/v1` | `ELEVENLABS_API_KEY` | voice agent | Text-to-speech (Multilingual v2) |
| 6 | **Deepgram** | `api.deepgram.com` | `DEEPGRAM_API_KEY` | voice pipeline | Real-time speech-to-text |
| 7 | **xAI Grok** | `api.x.ai` | `XAI_API_KEY` | video agent | Text-to-video generation |
| 8 | **Google Calendar** | `www.googleapis.com/calendar` | `GOOGLE_OAUTH_CLIENT_ID/SECRET` | calendar agent | Events CRUD, OAuth2 per-user |
| 9 | **Gmail** | `www.googleapis.com/gmail/v1` | Same Google OAuth | email agent, email polling | Read/send emails, OAuth2 |
| 10 | **Google Maps** | `maps.googleapis.com` | `GOOGLE_MAPS_API_KEY` | maps, traffic, leaving_now, commute | Directions, distance matrix |
| 11 | **Google Places** | `places.googleapis.com/v1` | `GOOGLE_PLACES_API_KEY` | search, restaurant | Find businesses, reviews |
| 12 | **Spotify** | `api.spotify.com/v1` | `SPOTIFY_CLIENT_ID/SECRET` | music agent | Search, play, recommendations |
| 13 | **17TRACK** | `api.17track.net/track/v2` | `17TRACK_API_KEY` | tracking agent, package service | Package tracking (2600+ carriers) |
| 14 | **WeatherAPI** | `api.weatherapi.com/v1` | `WEATHER_API_KEY` | weather agent, alerts | Weather forecasts, alerts |
| 15 | **Twelve Data** | `api.twelvedata.com` | `TWELVE_DATA_API_KEY` | finance agent | Stock prices, market data |
| 16 | **CoinGecko** | `api.coingecko.com/api/v3` | (free, no key) | crypto service | Cryptocurrency prices |
| 17 | **Duffel** | `api.duffel.com` | `DUFFEL_API_TOKEN` | travel agent | Flight/hotel search and booking |
| 18 | **YouTube** | `www.googleapis.com/youtube/v3` | `YOUTUBE_API_KEY` | youtube agent | Video search, trending |
| 19 | **Twilio** | `api.twilio.com` | `TWILIO_ACCOUNT_SID/AUTH_TOKEN` | twilio agent, calls | Voice calls, WebSocket streaming |
| 20 | **WhatsApp (Meta)** | `graph.facebook.com/v21.0` | `WHATSAPP_TOKEN`, `WHATSAPP_PHONE_NUMBER_ID` | whatsapp webhook | Business messaging, buttons |
| 21 | **NTA Ireland** | `api.nationaltransport.ie/gtfsr/v2` | `NTA_API_KEY` | transport, leaving_now | Real-time transit (bus/DART/Luas) |
| 22 | **Tuya** | `openapi.tuyaeu.com` | `TUYA_CLIENT_ID/SECRET` | smarthome agent | Smart home device control |
| 23 | **Smartcar** | `api.smartcar.com` | `SMARTCAR_CLIENT_ID/SECRET/MANAGEMENT_TOKEN` | car agent | EV battery, location, lock/unlock |
| 24 | **Serper** | `google.serper.dev` | `SERPER_API_KEY` | search service | Google search results API |
| 25 | **Stripe** | `api.stripe.com` | `STRIPE_SECRET_KEY`, `STRIPE_WEBHOOK_SECRET` | billing routes | Payments, subscriptions |
| 26 | **Supabase** | Custom URL | `SUPABASE_URL/SERVICE_KEY` | database service | PostgreSQL (33 tables) |
| 27 | **Upstash Redis** | Custom URL | `UPSTASH_REDIS_REST_URL/TOKEN` or `REDIS_URL` | redis service | Cache, timers, sessions |
| 28 | **Sentry** | `sentry.io` | `SENTRY_DSN` | sentry service | Error monitoring |
| 29 | **GitHub** | `api.github.com` | `GITHUB_TOKEN`, `GITHUB_CLIENT_ID/SECRET` | github agent, devgit, OAuth | Repos, code push, OAuth |

---

## 6. All Environment Variables (64 vars)

### Required (app won't start without these):

| Variable | Used by | Description |
|----------|---------|------------|
| `SUPABASE_URL` | database.py | Supabase project URL |
| `SUPABASE_SERVICE_KEY` | database.py | Supabase service role key |
| `ENCRYPTION_KEY` | encryption.py | Fernet key for encrypting OAuth tokens |
| `JWT_SECRET_KEY` | auth.py | JWT signing secret |
| `OPENAI_API_KEY` | openai_service.py | OpenAI API key (GPT, DALL-E, Whisper) |
| `ENVIRONMENT` | sentry, main | "production" or "development" |

### AI Services:

| Variable | Used by | Description |
|----------|---------|------------|
| `OPENAI_API_KEY` | openai_service.py | OpenAI main key |
| `OPENAI_DEFAULT_MODEL` | model_config.py | Default model (gpt-4o) |
| `OPENAI_CHAT_MODEL` | model_config.py | Chat model (gpt-4o) |
| `OPENAI_INTENT_MODEL` | model_config.py | Intent detection (gpt-4o-mini) |
| `OPENAI_ORCHESTRATOR_MODEL` | model_config.py | Orchestrator routing (gpt-4o-mini) |
| `OPENAI_VISION_MODEL` | model_config.py | Vision model (gpt-4o) |
| `OPENAI_CODEX_MODEL` | dev_agent.py | Code model fallback (codex-mini-latest) |
| `ANTHROPIC_API_KEY` | anthropic_service.py | Claude API key |
| `SONAR_API_KEY` | perplexity_service.py | Perplexity API key |
| `GEMINI_API_KEY` | image_service.py, video_service.py | Google Gemini key |
| `ELEVENLABS_API_KEY` | elevenlabs_service.py | ElevenLabs TTS key |
| `DEEPGRAM_API_KEY` | voice pipeline | Deepgram STT key |
| `XAI_API_KEY` | grok_video_service.py | xAI Grok video key |

### External APIs:

| Variable | Used by | Description |
|----------|---------|------------|
| `GOOGLE_OAUTH_CLIENT_ID` | google_oauth_service.py | Google OAuth app |
| `GOOGLE_OAUTH_CLIENT_SECRET` | google_oauth_service.py | Google OAuth secret |
| `GOOGLE_MAPS_API_KEY` | maps_service.py, traffic_service.py | Google Maps key |
| `GOOGLE_PLACES_API_KEY` | restaurant_service.py | Google Places key |
| `SPOTIFY_CLIENT_ID` | spotify_oauth_service.py | Spotify app ID |
| `SPOTIFY_CLIENT_SECRET` | spotify_oauth_service.py | Spotify secret |
| `17TRACK_API_KEY` | tracking_service.py | 17TRACK tracking key |
| `WEATHER_API_KEY` | weather_service.py | WeatherAPI.com key |
| `TWELVE_DATA_API_KEY` | finance_service.py | Twelve Data stock key |
| `DUFFEL_API_TOKEN` | duffel_service.py | Duffel flights key |
| `YOUTUBE_API_KEY` | youtube_service.py | YouTube Data v3 key |
| `NTA_API_KEY` | transit_service.py | Ireland transit key |
| `SERPER_API_KEY` | search_service.py | Serper Google search key |

### Communication:

| Variable | Used by | Description |
|----------|---------|------------|
| `TELEGRAM_BOT_TOKEN` | telegram_bot | Telegram bot token |
| `TELEGRAM_ADMIN_CHAT_ID` | security_event_service.py | Admin chat for alerts |
| `WHATSAPP_TOKEN` | whatsapp_service.py | WhatsApp permanent token |
| `WHATSAPP_PHONE_NUMBER_ID` | whatsapp_service.py | WhatsApp phone ID |
| `WHATSAPP_VERIFY_TOKEN` | whatsapp_webhook.py | Webhook verification |
| `TWILIO_ACCOUNT_SID` | twilio_service.py | Twilio account |
| `TWILIO_AUTH_TOKEN` | twilio_service.py | Twilio auth |
| `TWILIO_WEBHOOK_BASE_URL` | twilio_service.py | Callback URL base |

### Smart Home / Vehicle:

| Variable | Used by | Description |
|----------|---------|------------|
| `TUYA_CLIENT_ID` | tuya_oauth_service.py | Tuya smart home |
| `TUYA_CLIENT_SECRET` | tuya_oauth_service.py | Tuya secret |
| `TUYA_DATA_CENTER` | tuya_oauth_service.py | Tuya region (eu, us, cn) |
| `SMARTCAR_CLIENT_ID` | car_service.py | Smartcar OAuth |
| `SMARTCAR_CLIENT_SECRET` | car_service.py | Smartcar secret |
| `SMARTCAR_MANAGEMENT_TOKEN` | car_service.py | Smartcar management |

### Payments:

| Variable | Used by | Description |
|----------|---------|------------|
| `STRIPE_SECRET_KEY` | billing.py | Stripe API key |
| `STRIPE_WEBHOOK_SECRET` | billing.py | Stripe webhook verification |
| `STRIPE_PRICE_ME` | billing.py | Stripe price ID for "Me" plan |
| `STRIPE_PRICE_EVERYWHERE` | billing.py | Stripe price ID for "Everywhere" plan |

### Infrastructure:

| Variable | Used by | Description |
|----------|---------|------------|
| `REDIS_URL` | worker.py, redis_service.py | Redis connection URL |
| `UPSTASH_REDIS_REST_URL` | redis_service.py | Upstash REST endpoint |
| `UPSTASH_REDIS_REST_TOKEN` | redis_service.py | Upstash REST token |
| `SENTRY_DSN` | sentry_service.py | Sentry error tracking |
| `SENTRY_TRACES_SAMPLE_RATE` | sentry_service.py | Sentry perf sampling |
| `RELEASE` | sentry_service.py | Version tag |
| `BACKEND_URL` | twilio_agent.py | Public backend URL |
| `FRONTEND_URL` | auth.py, billing.py | Frontend URL |
| `ADMIN_URL` | admin.py | Admin panel URL |
| `ADMIN_SECRET_TOKEN` | admin.py | Admin auth token |
| `WEBHOOK_SECRET` | webhooks.py | HMAC webhook verification |

### GitHub:

| Variable | Used by | Description |
|----------|---------|------------|
| `GITHUB_TOKEN` | git_service.py | Admin/bot GitHub token |
| `GITHUB_CLIENT_ID` | github_auth.py | GitHub OAuth App ID |
| `GITHUB_CLIENT_SECRET` | github_auth.py | GitHub OAuth secret |

### Push Notifications:

| Variable | Used by | Description |
|----------|---------|------------|
| `VAPID_PUBLIC_KEY` | push_notifications.py | Web push VAPID public key |
| `VAPID_PRIVATE_KEY` | push_notifications.py | Web push VAPID private key |
| `VAPID_CLAIMS_EMAIL` | push_notifications.py | VAPID claims email |

### Auth:

| Variable | Used by | Description |
|----------|---------|------------|
| `SUPABASE_JWT_SECRET` | webapp_auth.py | Supabase JWT verification |
| `CORS_ORIGIN_LOCALHOST` | main.py | Local dev CORS |
| `CORS_ORIGIN_VITE` | main.py | Vite dev CORS |

---

## 7. All Supabase Tables (33 tables)

| # | Table | Used by | What it stores |
|---|-------|---------|----------------|
| 1 | `users` | Auth, all services | User accounts: email, name, plan, phone, country_code |
| 2 | `user_preferences` | preferences service | Per-user settings: language, quiet hours, etc. |
| 3 | `user_context` | focus, tracking, budget, mood, followups, silence | Generic key-value store per user for feature state |
| 4 | `user_memory` | RAG service | Long-term memory embeddings for personalization |
| 5 | `user_oauth_tokens` | Google, Spotify, GitHub OAuth | Encrypted OAuth2 tokens per user |
| 6 | `conversations` | Chat service | Telegram conversation metadata |
| 7 | `messages` | Chat service | Telegram chat message history |
| 8 | `webapp_conversations` | WebApp routes | Web app conversation sessions |
| 9 | `webapp_messages` | WebApp routes | Web app chat messages |
| 10 | `notes` | Notes service | User notes (title, content, pinned, tags) |
| 11 | `reminders` | Reminder service | Persistent reminders with recurrence |
| 12 | `calendar_connections` | Google OAuth | Google Calendar OAuth connections per user |
| 13 | `calendar_events` | Calendar, many services | Cached calendar events from Google |
| 14 | `email_accounts` | Email service | Connected email accounts (Gmail, Outlook) |
| 15 | `email_inbox` | Email polling | Cached inbox messages |
| 16 | `email_poll_state` | Email polling | Polling state: last checked ID, enabled flag |
| 17 | `email_replies` | Email agent | Sent reply tracking |
| 18 | `proactivity_feed` | All proactive services | Notification feed for bell icon (tracking, weather, etc.) |
| 19 | `proactivity_preferences` | Proactivity service | Which proactive features user has enabled |
| 20 | `push_subscriptions` | Push notifications | Web push subscription endpoints per browser |
| 21 | `mercado_compras` | Mercado service | Grocery shopping sessions (store, date, total) |
| 22 | `mercado_itens` | Mercado service | Individual items in shopping lists |
| 23 | `shopping_list` | Mercado agent | Active shopping list items |
| 24 | `shopping_list_history` | Mercado agent | Historical purchase data |
| 25 | `call_logs` | Twilio service | Phone call history (SID, duration, status) |
| 26 | `security_events` | Security service | Auth events, suspicious activity, rate limit hits |
| 27 | `car_connections` | Car agent | Smartcar OAuth connections |
| 28 | `github_connections` | GitHub auth | GitHub OAuth connections per user |
| 29 | `restaurant_favorites` | Restaurant agent | User's saved restaurants |
| 30 | `restaurant_searches` | Restaurant agent | Search history |
| 31 | `restaurant_reservations` | Restaurant agent | Reservation tracking |
| 32 | `projects` | Dev agent | Code projects (files, language) |
| 33 | `tenant_usage` | Quota service | API usage tracking per user per day |

---

## 8. All Services (101 files)

### Business Services (43 files) — The brain of the bot:

| # | Service | File | Lines | What it does |
|---|---------|------|-------|-------------|
| 1 | Agenda Conflict | `agenda_conflict_service.py` | 316 | Detects overlapping calendar events, alerts user |
| 2 | Birthday | `birthday_service.py` | 293 | Detects upcoming birthdays from contacts, suggests gifts |
| 3 | Budget Tracker | `budget_tracker_service.py` | 316 | Detects spending in messages, categorizes, monthly summary |
| 4 | Call Session | `call_session.py` | 823 | Manages active phone call sessions with AI brain |
| 5 | Chat Service | `chat_service.py` | 456 | WebApp chat processing, conversation management |
| 6 | Commute Optimizer | `commute_optimizer_service.py` | 233 | Smart departure time based on traffic + calendar |
| 7 | Context Silence | `context_silence_service.py` | 355 | Knows when NOT to notify (meeting/sleep/focus/DND) |
| 8 | Crypto | `crypto_service.py` | 288 | CoinGecko wrapper for crypto prices |
| 9 | Daily Summary | `daily_summary_service.py` | 293 | End-of-day recap at 18h (events, tasks, focus time) |
| 10 | DevGit Bridge | `devgit_bridge.py` | 379 | Generate code → preview → push to GitHub |
| 11 | Discovery Engine | `discovery_engine_service.py` | 311 | Proactive suggestions (restaurants, events, articles) |
| 12 | Email Account | `email_account_service.py` | 114 | Email account connection management |
| 13 | Email Polling | `email_polling_service.py` | 1080 | Gmail polling: fetch new emails, smart label filtering |
| 14 | Email Triage | `email_triage_service.py` | 408 | AI-powered email importance scoring and summary |
| 15 | Finance Alert | `finance_alert_service.py` | 248 | Stock price alerts when thresholds hit |
| 16 | Finance News | `finance_news_service.py` | 509 | Financial news fetch + AI summary (Perplexity) |
| 17 | Focus Mode | `focus_mode_service.py` | 366 | DND with Pomodoro, missed notifications queue |
| 18 | Grocery Synonyms | `grocery_synonyms.py` | 139 | Normalize grocery item names (leite = milk) |
| 19 | Implicit Action | `implicit_action_service.py` | 383 | Detect implicit actions in conversation |
| 20 | Leaving Home Check | `leaving_home_check_service.py` | 292 | "Don't forget: umbrella, wallet" before leaving |
| 21 | Leaving Now | `leaving_now_service.py` | 653 | "When should I leave?" with real-time transit data |
| 22 | Meeting Briefing | `meeting_briefing_service.py` | 249 | Pre-meeting research and context preparation |
| 23 | Meeting Orchestrator | `meeting_orchestrator_service.py` | 470 | Complex meeting scheduling with conflict resolution |
| 24 | Mercado Service | `mercado_service.py` | 1904 | Full grocery system: lists, receipts, reports, price comparison |
| 25 | Mood Detection | `mood_detection_service.py` | 316 | Detects user mood → adapts bot tone (7 moods) |
| 26 | Morning Briefing | `morning_briefing_service.py` | 349 | Morning summary: weather + calendar + finance + news |
| 27 | Notes Service | `notes_service.py` | 465 | Full notes CRUD with search and pinning |
| 28 | Overdue Tasks | `overdue_tasks_service.py` | 231 | Detects and alerts about missed deadlines |
| 29 | Package Tracking | `package_tracking_service.py` | 599 | Auto-detect tracking from emails, monitor status, webhook |
| 30 | Payment Reminder | `payment_reminder_service.py` | 394 | Bill payment reminders before due dates |
| 31 | Proactivity | `proactivity_service.py` | 570 | Main proactive engine: gather context → generate insights |
| 32 | Prompt Cleaner | `prompt_cleaner.py` | 555 | Clean and normalize user prompts before AI processing |
| 33 | Quota | `quota_service.py` | 731 | Track API usage per user, enforce plan limits |
| 34 | RAG | `rag_service.py` | 294 | Retrieval-augmented generation using user memory |
| 35 | Reminder Service | `reminder_service.py` | 390 | Persistent reminders with recurrence (Supabase) |
| 36 | Research | `research_service.py` | 309 | Deep research via Perplexity with source tracking |
| 37 | Restaurant DB | `restaurant_db_service.py` | 159 | Restaurant favorites and search history |
| 38 | Saved Locations | `saved_locations_service.py` | 287 | User's saved places (home, work, etc.) |
| 39 | Search | `search_service.py` | 432 | Serper API wrapper for Google search |
| 40 | Sleep/Wake | `sleep_wake_service.py` | 348 | Night routine + morning wake-up based on calendar |
| 41 | Smart Follow-up | `smart_followup_service.py` | 262 | Remembers mentions → follows up later |
| 42 | Subscription | `subscription_service.py` | 357 | Subscription expiry detection and alerts |
| 43 | Timer Service | `timer_service.py` | 348 | Ephemeral timers/alarms in Redis |
| 44 | Translate | `translate_service.py` | 326 | GPT-powered translation between languages |
| 45 | Travel Planner | `travel_planner_service.py` | 1372 | Full trip planning: flights, hotels, itineraries |
| 46 | User Preferences | `user_preferences_service.py` | 150 | Read/write user preferences |
| 47 | User Profile | `user_profile_service.py` | 303 | Build user profile prompt for personalization |
| 48 | Vehicle DB | `vehicle_db_service.py` | 421 | Vehicle connection storage and management |
| 49 | Weather Alert | `weather_alert_service.py` | 316 | Unexpected weather change alerts |
| 50 | Weekly Planner | `weekly_planner_service.py` | 260 | Sunday morning week planning |
| 51 | Weekly Recap | `weekly_recap_service.py` | 467 | Monday finance weekly recap |
| 52 | Weekly Wins | `weekly_wins_service.py` | 255 | Saturday achievement celebration |
| 53 | Welcome | `welcome_service.py` | 192 | Auto welcome on registration (WhatsApp/Telegram) |

---

## 9. All API Routes (34 route files, 160+ endpoints)

| # | Route File | Prefix | Key Endpoints |
|---|-----------|--------|---------------|
| 1 | `auth.py` | `/api/v1/auth` | POST /login, POST /register, POST /refresh, GET /user/me, PATCH /user/profile |
| 2 | `google_auth.py` | (direct) | GET /connect, GET /callback (Google OAuth flow) |
| 3 | `spotify_auth.py` | (direct) | GET /connect, GET /callback, POST /disconnect (Spotify OAuth) |
| 4 | `tuya_auth.py` | (direct) | GET /connect, GET /callback, GET /callback/smartcar |
| 5 | `github_auth.py` | `/api/v1/auth` | GET /github/connect, GET /github/callback, GET /github/admin-status |
| 6 | `chat.py` | `/api/v1/chat` | POST /chat (main chat endpoint) |
| 7 | `notes.py` | `/api/v1/notes` | CRUD: GET /, POST /, GET /{id}, PUT /{id}, DELETE /{id}, PATCH /{id} |
| 8 | `workspace.py` | `/api/v1/workspace` | GET /files/list, GET /files/read, POST /files/create, PUT /files/update, DELETE /files/delete, git operations |
| 9 | `research.py` | `/api/v1/research` | POST /query, POST /deep |
| 10 | `dev.py` | `/api/v1/dev` | POST /execute, POST /generate-and-execute |
| 11 | `devgit.py` | `/api/v1/dev` | POST /generate, GET /preview/{id}, POST /push, GET /project/{id} |
| 12 | `image.py` | `/api/v1/image` | POST /generate |
| 13 | `video.py` | `/api/v1/video` | POST /generate, POST /text-to-video, POST /image-to-video |
| 14 | `voice.py` | `/api/v1/voice` | POST /text-to-speech, POST /speech-to-text, GET /voices, POST /voice/synthesize, POST /voice/transcribe |
| 15 | `voice_ws.py` | `/api/webapp` | WebSocket /ws/{conversation_id} (real-time voice chat) |
| 16 | `voice_pipeline_routes.py` | `/api/v1/voice/pipeline` | POST /stream (streaming voice pipeline) |
| 17 | `weather.py` | `/api/v1/weather` | GET /auto, GET /{city}, GET /{city}/forecast, GET /{city}/week, GET /{city}/alerts, GET /{city}/detailed |
| 18 | `finance.py` | `/api/v1/finance` | GET /quote/{symbol}, GET /price/{symbol}, GET /history/{symbol}, GET /finance/portfolio, GET /finance/news |
| 19 | `calendar.py` | `/api/v1/calendar` | GET /today, GET /next-meeting, GET /briefing, GET /auto/week, POST /query |
| 20 | `car.py` | `/api/v1/car` | GET /status, GET /battery, GET /location, GET /charge-status, POST /lock, POST /unlock, POST /start-charging, POST /stop-charging |
| 21 | `traffic.py` | `/api/v1/traffic` | GET /check-event, GET /route |
| 22 | `music.py` | `/api/v1/music` | GET /search, GET /recommendations, GET /track/{id}, GET /artist/{id}, GET /artist/top-tracks, GET /languages |
| 23 | `agent_generic.py` | `/api/v1/agent` | POST /{agent_name} (generic agent dispatch) |
| 24 | `webapp.py` | `/api/webapp` | POST /chat, POST /chat/stream, conversations CRUD, memory, reminders, proactivity feed, market integrations, security events, admin tenants |
| 25 | `upload.py` | `/api/webapp` | POST /upload, GET /audio/{filename} |
| 26 | `push_notifications.py` | `/api/webapp` | POST /notifications/subscribe, POST /notifications/unsubscribe, POST /notifications/test |
| 27 | `admin.py` | `/api/admin` | GET /tenants, PATCH /tenants/{uid}/plan, POST /tenants/{uid}/quota, GET /autofix/tickets, GET /services/status, GET /security-events |
| 28 | `billing.py` | `/api/billing` | POST /create-checkout, POST /webhook, GET /status, POST /portal, POST /cron/reset-daily |
| 29 | `images_serve.py` | (direct) | GET /api/images/{filename}, GET /api/videos/{filename} |
| 30 | `webhooks.py` | `/api/v1/webhooks` | POST /email (HMAC-verified), POST /tracking (17TRACK push) |
| 31 | `whatsapp_webhook.py` | `/api/v1/webhooks` | GET /whatsapp (verify), POST /whatsapp (messages), POST /whatsapp/link, POST /whatsapp/register-phone |
| 32 | `twilio_stream.py` | (direct) | WebSocket /ws/twilio-stream (real-time voice calls) |
| 33 | `health.py` | (direct) | GET /health (system health check) |
| 34 | `_helpers.py` | — | Shared route utilities |

---

## 10. Proactive vs Reactive Features

### PROACTIVE (bot initiates — no user action needed):

| Feature | Service | Trigger | What happens |
|---------|---------|---------|-------------|
| Morning Briefing | `morning_briefing_service.py` | ~06:00-10:00 UTC | Weather + calendar + finance + news summary |
| Daily Summary | `daily_summary_service.py` | ~18:00 | Day recap: events, tasks pending, focus time |
| Weekly Planner | `weekly_planner_service.py` | Sunday ~09:00 | Next week overview per day |
| Weekly Wins | `weekly_wins_service.py` | Saturday ~09:00 | Celebrates weekly achievements |
| Weekly Finance Recap | `weekly_recap_service.py` | Monday ~08:00-10:00 | Portfolio performance, market summary |
| Sleep Routine | `sleep_wake_service.py` | ~22:00 | Suggests bedtime based on tomorrow's calendar |
| Wake Routine | `sleep_wake_service.py` | ~wake time | Weather + first events |
| Email Polling | `email_polling_service.py` | Every ~5 min | Scans Gmail → notifies new emails |
| Email → Tracking | `package_tracking_service.py` | During email poll | Detects shipping emails → auto-registers tracking |
| Package Updates | `package_tracking_service.py` | Periodic + webhook | 17TRACK status changes → alerts |
| Finance Alerts | `finance_alert_service.py` | Every proactivity cycle | Stock price threshold alerts |
| Weather Alerts | `weather_alert_service.py` | Periodic | Unexpected weather changes |
| Birthday Alerts | `birthday_service.py` | Daily check | Upcoming birthdays with gift suggestions |
| Meeting Briefing | `meeting_briefing_service.py` | 2h before meeting | Pre-meeting research context |
| Agenda Conflicts | `agenda_conflict_service.py` | When events change | Overlapping calendar events |
| Overdue Tasks | `overdue_tasks_service.py` | Periodic | Missed deadline reminders |
| Payment Reminders | `payment_reminder_service.py` | Before due dates | Bill payment alerts |
| Subscription Expiring | `subscription_service.py` | Before expiry | Expiring subscription alerts |
| Leaving Home Check | `leaving_home_check_service.py` | Before first event | "Don't forget: umbrella, wallet, keys" |
| Commute Optimizer | `commute_optimizer_service.py` | Before events with location | "Leave at 08:30, traffic light" |
| Smart Follow-up | `smart_followup_service.py` | After user mentions event | "How was the interview?" (next day) |
| Discovery Engine | `discovery_engine_service.py` | 1-2x per day | Restaurant/event/article suggestions |
| Mood Detection | `mood_detection_service.py` | Every message | Adapts bot tone to user mood |
| Context Silence | `context_silence_service.py` | Always active | Suppresses during meetings/sleep/focus |
| Focus Mode | `focus_mode_service.py` | User-activated | Silences all, shows summary after |
| Budget Tracking | `budget_tracker_service.py` | During conversations | Detects "gastei 50€ no almoço" |
| News | `finance_news_service.py` | 2x/day (07:00, 18:00) | Personalized news (Perplexity) |
| Travel Detection | `travel_planner_service.py` | Once/day 10:00-12:00 | Detects travel-related context |

### REACTIVE (user asks → bot responds):

All 34 agents respond to direct user requests via the orchestrator routing.

---

## 11. The Proactivity Loop (8 steps)

File: `proactivity_loop.py` — runs every ~5 minutes via cron or asyncio loop.

```
Step 1: Proactivity checks → ProactivityService gathers context + generates insights
Step 2: Email polling → Gmail fetch → new email notifications to Telegram
Step 3: News fetching → 2x/day at 07:00 and 18:00 UTC via Perplexity
Step 4: Finance alerts → Check stock price thresholds, send alerts
Step 5: Morning briefing → 06:00-10:00 UTC window, once/day per user
Step 6: Meeting briefings → 2h before any meeting with attendees
Step 7: Weekly finance recap → Mondays 08:00-10:00 UTC
Step 8: Travel detection → Once/day 10:00-12:00 UTC, detect trip context
```

Each step is **isolated** — a failure in one doesn't prevent others from running.

---

## 12. Background Worker (Arq)

File: `worker.py` — Redis-based background task processor.

| Task | Schedule | What it does |
|------|----------|-------------|
| `generate_image_task` | On demand | DALL-E image generation (async, non-blocking) |
| `check_timers` | Every 10 seconds | Poll Redis for expired timers → notify user |
| `check_reminders` | Every 30 seconds | Poll Supabase for due reminders → notify user |

---

## 13. Message Flow Architecture

```
User sends message (WebApp / Telegram / WhatsApp)
        │
        ▼
┌─ Context-aware Silence check (context_silence_service)
│  → if user in meeting/sleep/focus → queue notification, don't disturb
│
├─ Mood Detection (mood_detection_service)
│  → analyze keywords + emojis + patterns → detect mood → adjust tone
│
├─ Smart Follow-up detection (smart_followup_service)
│  → if mentions doctor/interview/trip → store for future follow-up
│
├─ Budget Tracker (budget_tracker_service)
│  → if mentions spending ("gastei 50€") → detect amount, categorize
│
├─ Package Tracking detection (package_tracking_service)
│  → if mentions tracking number → auto-register in 17TRACK
│
├─ Keyword routing (telegram_bot/core/bot.py or webapp)
│  → TWILIO_KEYWORDS → twilio agent (phone calls)
│  → TRANSPORT_KEYWORDS → transport agent (bus/train)
│  → CALENDAR_CONNECT_KEYWORDS → calendar agent (Google connect)
│  → EMAIL_KEYWORDS → email agent
│  → MERCADO_KEYWORDS → mercado agent
│  → MEDIA_CAST_KEYWORDS → media cast agent
│  → (none matched) → orchestrator
│
├─ Orchestrator Agent (orchestrator_agent.py)
│  → GPT-4o-mini classifies intent → routes to 1 of 32 agents
│  → OrchestratorDecision: {agent: "weather", reason: "user asked about rain"}
│
├─ Specialized Agent processes request
│  → calls service(s) → calls external API(s) if needed
│  → formats response with i18n strings
│
└─ Response sent back to user
   → Telegram: text/photo/audio/voice/document
   → WebApp: JSON response or WebSocket stream
   → WhatsApp: text/interactive buttons
```

---

## 14. Communication Channels

### WebApp (app.capivarex.com)
- **Framework:** Next.js 14 (TypeScript), Vercel
- **REST API:** `POST /api/webapp/chat` (main chat), `POST /api/webapp/chat/stream` (SSE streaming)
- **WebSocket:** `ws://*/api/webapp/ws/{conversation_id}` (real-time voice + chat)
- **Auth:** Supabase Auth (JWT in sessionStorage, not localStorage for security)
- **Voice:** Token sent as first WebSocket message (not in URL)
- **Security:** CSP headers, rehype-sanitize, HSTS, X-Frame-Options

### Telegram Bot
- **Entry:** `telegram_bot/main.py` → `telegram_bot/core/bot.py`
- **Handlers:** message (text), voice (Whisper STT), photo (receipt scan + image analysis), document, location (GPS save)
- **Commands:** /start, /help, /status, /autofix, /proactivity
- **Callbacks:** email actions (reply/ignore/forward), mercado actions (add/remove/edit)
- **Keyword routing:** 6 keyword sets bypass orchestrator for direct agent dispatch

### WhatsApp Business
- **API:** Meta Cloud API (Graph API v21.0)
- **Phone:** +353 89 958 2889 (Phone ID: 1003159146219090)
- **Webhook:** `POST /api/v1/webhooks/whatsapp`
- **Features:** Welcome onboarding with interactive buttons, plan-gating (FOMO for free users), 6-digit account linking, guest mode (GPT-powered)
- **Status:** Development mode (5 test numbers until business verification)

---

## 15. Plans and Billing

### Capivara Module Plans (current — March 2026)

| Plan | Price | Modules Included | Key Limits |
|------|-------|-----------------|-----------|
| **ARA** | €19.99/mo | ARA (Life & Time) | 300 msg/day, all channels |
| **ARA + 1** | €27.99/mo | ARA + 1 chosen Capivara | 500 msg/day |
| **CAPIVAREX Pro** | €44.99/mo | ARA + 3 chosen Capivaras | 1000 msg/day, 30 min calls |
| **CAPIVAREX Ultimate** | €89.99/mo | All 7 Capivaras | Unlimited, 120 min calls |

### Capivara Modules (7 total)

| Module | Name | Domain |
|--------|------|--------|
| **ARA** | Life & Time | Calendar, reminders, weather, notes, voice, maps, research, translate, tracking |
| **IVI** | Financial | Finance, investments, budgets, tracking |
| **OKA** | Knowledge | Research, education, study, deep learning |
| **YARA** | Wellness | Sleep, exercise, nutrition, mental health |
| **AYVU** | Communication | Email, calls, Telegram, WhatsApp |
| **MBAE** | Productivity | Notes, reminders, tasks, project management |
| **PORA** | Creative | Image generation, writing, design |

### Legacy Plans (still supported)

| Plan | Price | Channels |
|------|-------|----------|
| **Professional** | €39.99/mo | All |
| **Executive** | €79.00/mo | All |

### Billing Flow

1. Frontend `PricingCards.tsx` → `redirectToCheckout(plan)` → backend `POST /api/billing/create-checkout`
2. Backend creates Stripe Checkout Session with plan metadata
3. User pays on Stripe → Stripe sends `checkout.session.completed` webhook
4. Backend webhook handler: upserts plan in `tenant_subscriptions`, activates modules in `user_modules`
5. For ARA+1 and Pro: user redirected to `/billing/select-modules` to choose which Capivaras
6. Frontend calls `POST /api/billing/activate-bundle-modules` with selected modules

### Key Tables

| Table | Purpose |
|-------|---------|
| `tenant_subscriptions` | Plan name, Stripe subscription ID, limits |
| `tenant_usage` | Daily message counters per user |
| `user_modules` | Which Capivara modules each user has (user_id, module_name, status) |

Billing via **Stripe**: checkout sessions, subscription webhooks, customer portal.

---

## 16. Internationalization (i18n)

| File | Lines | Purpose |
|------|-------|---------|
| `services/i18n/keywords.py` | 620 | Multi-language keyword detection (PT/EN/ES) for routing |
| `services/i18n/prompts.py` | 178 | System prompts for orchestrator (EN) and chat (auto-detect) |
| `services/i18n/strings.py` | 2950 | ALL user-facing strings in PT/EN/ES |

**Language detection:** Auto-detect from user message. Orchestrator prompt always in English (better routing). Chat prompt adapts to detected language.

---

## 17. Security Architecture

| Layer | Implementation |
|-------|---------------|
| **JWT Auth** | Supabase JWT, verified on every webapp request |
| **Token Encryption** | Fernet (ENCRYPTION_KEY) for OAuth tokens at rest |
| **Rate Limiting** | Redis-based per-user, configurable per endpoint |
| **CORS** | Restricted to app.capivarex.com + local dev |
| **Webhook HMAC** | SHA-256 signature verification for email webhooks |
| **Security Headers** | CSP, HSTS, X-Frame-Options, X-Content-Type-Options, Referrer-Policy |
| **Session Storage** | sessionStorage (not localStorage) — clears on tab close |
| **WebSocket Auth** | Token sent in first message (not URL) |
| **Markdown Sanitization** | rehype-sanitize blocks script/iframe/form injection |
| **Code Execution** | Sandboxed with env={} (no env var leaks) |
| **Admin Auth** | HMAC compare_digest for admin endpoints |
| **Security Events** | Logged to security_events table + Telegram admin alert |
| **Env Validation** | Required vars validated on startup — crash if missing |

---

## 18. Bot Modes and Personas

File: `bot/modes/definitions.py`

| Mode | Name | Persona |
|------|------|---------|
| `default` | Cérebro Principal | General conversation, organization, decisions |
| `dev` | Desenvolvedor | Senior software engineer, clean code, security |
| `rotina` | Organização Pessoal | Daily routine, habits, productivity |
| `marketing` | Marketing & Vendas | Marketing strategies, growth |
| `financas` | Finanças Pessoais | Budget, investments, financial planning |
| `criativo` | Criativo | Creative writing, brainstorming, ideation |

---

## 19. Autofix System

File: `autofix/core.py` (2033 lines)

Self-healing bug detection and patching:
1. **Bug capture:** Middleware catches exceptions → records stack trace + context
2. **Ticket management:** Creates bug tickets with severity and reproduction steps
3. **Suggestion generation:** AI generates fix suggestions
4. **Patch generation:** Claude generates patches with governance checks
5. **Sandbox apply:** Tests patch in sandbox before merging
6. **GitHub PR:** `autofix/github_pr.py` auto-creates PR with fix
7. **Admin notification:** `autofix/notifier.py` alerts admin via Telegram

---

## 20. Deployment

| Component | Platform | Deploy Method |
|-----------|----------|--------------|
| **Backend** | Railway | Auto-deploy from `main` branch on GitHub |
| **Frontend** | Vercel | Auto-deploy from `main` branch, multi-region (US/BR/IE) |
| **Database** | Supabase | Managed PostgreSQL |
| **Redis** | Upstash | Managed Redis (REST API) |
| **Worker** | Railway | `arq worker.WorkerSettings` process |

**Server:** Gunicorn + Uvicorn workers (`workers = CPU*2+1`, bind `0.0.0.0:8000`)

**Frontend Performance Optimizations:**
- LazyMotion (framer-motion -60% bundle)
- Dynamic imports for heavy components
- CSS animations replacing framer-motion on 13 pages
- Middleware skip for public pages (faster TTFB)
- Multi-region: US East (iad1), São Paulo (gru1), Dublin (dub1)
- Aggressive caching for static pages

---

## 21. Feature Roadmap Status

| Tier | Done | Total | Status |
|------|------|-------|--------|
| Sprint 0 (Security) | 11 | 11 | ✅ COMPLETE |
| Frontend Security | 6 | 6 | ✅ COMPLETE |
| Performance | 8 | 8 | ✅ COMPLETE |
| S-TIER (Core) | 9 | 9 | ✅ COMPLETE |
| A-TIER (High Value) | 9 | 12 | 3 special (device/work pack) |
| B-TIER (Nice to Have) | 6 | 14 | 8 future (nota ≤7) |
| C-TIER (Future) | 1 | 10 | 9 future (nota ≤7) |
| New Ideas | 5 | 5 | ✅ COMPLETE |
| Integrations | 5 | 5 | ✅ COMPLETE |
| **TOTAL** | **60** | **79** | **76%** |

---

## 22. Test Metrics

| Metric | Value |
|--------|-------|
| Total tests | 3858 |
| Passing | 3858 (100%) |
| Failing | 0 |
| Coverage | 79.08% |
| Ruff errors | 0 |
| Test files | 100+ |
| Lines of test code | ~25,000 |

---

*This document was generated by scanning 100% of the codebase: all 414 Python files, 84,456 lines of code, across 34 agents, 101 services, 34 route files, 33 database tables, 29 external APIs, and 64 environment variables.*
