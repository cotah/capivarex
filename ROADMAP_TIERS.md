# CAPIVAREX — Intelligence Roadmap (All Tiers)

## Status: 🟢 Done | 🟡 In Progress | 🔴 Todo

---

## 🔒 SPRINT 0 — Security Fixes ✅ COMPLETE

| # | Fix | Status |
|---|-----|--------|
| F1 | JWT_SECRET_KEY crash se vazio em prod | 🟢 Done |
| F2 | Rate limiter verify_signature: True | 🟢 Done |
| F3 | /dev/test → get_admin_user | 🟢 Done |
| F4 | Webhook email + autenticação HMAC | 🟢 Done |
| F5 | Subprocess env={} (sandbox) | 🟢 Done |
| F6 | Admin hmac.compare_digest | 🟢 Done |
| F7 | CORS allow_headers restrito | 🟢 Done |
| F8 | Timer race condition (Redis atomic) | 🟢 Done |
| F9 | Supabase sync→async (to_thread) | 🟢 Done |
| F10 | Fire-and-forget exception handlers | 🟢 Done |
| F11 | Env var validation no startup | 🟢 Done |

---

## 🔐 FRONTEND SECURITY — ✅ COMPLETE

| # | Fix | Status |
|---|-----|--------|
| FS1 | Content Security Policy (CSP) + 7 security headers | 🟢 Done |
| FS2 | Markdown sanitization (rehype-sanitize) | 🟢 Done |
| FS3 | WebSocket token — moved from URL to first message | 🟢 Done |
| FS4 | Token storage — sessionStorage instead of localStorage | 🟢 Done |
| FS5 | YouTube iframe sandbox | 🟢 Done |
| FS6 | HSTS, X-Frame-Options, Referrer-Policy | 🟢 Done |

---

## ⚡ PERFORMANCE OPTIMIZATIONS — ✅ COMPLETE

| # | Fix | Impact |
|---|-----|--------|
| P1 | LazyMotion — framer-motion bundle -60% | Mobile INP 680ms → <200ms |
| P2 | framer-motion removed from 13 pages → CSS animations | Less JS per page |
| P3 | Dynamic imports: ServiceGrid, Settings sections, Landing, Onboarding | Faster LCP |
| P4 | Next.js compiler: removeConsole, optimizePackageImports | Smaller bundle |
| P5 | Middleware skip for public pages | TTFB -200~500ms |
| P6 | Multi-region deployment (US + São Paulo + Dublin) | Brazil TTFB ~5s → <1s |
| P7 | Aggressive caching for static pages | TTFB ~0ms cached |
| P8 | Node.js engine 20.x → 24.x (Vercel warning fix) | Clean builds |

---

## ⭐ S-TIER — Core Intelligence ✅ COMPLETE

| # | Feature | Status |
|---|---------|--------|
| S1 | Morning Briefing | 🟢 Done |
| S2 | Meeting Briefing | 🟢 Done |
| S3 | Finance Alerts | 🟢 Done |
| S4 | Weekly Finance Recap | 🟢 Done |
| S5 | Personalized News | 🟢 Done |
| S6 | Travel Planner | 🟢 Done |
| S7 | Voice → Notes | 🟢 Done |
| S8 | Email Triage | 🟢 Done |
| S9 | Meeting Orchestrator | 🟢 Done |

---

## 🅰️ A-TIER — High Value Features ✅ COMPLETE (9/12)

| # | Feature | Status |
|---|---------|--------|
| A1 | Birthday + Action | 🟢 Done |
| A2 | Leaving Home Check | 🟢 Done |
| A3 | Arriving Home Prep | ⏸️ Needs physical device |
| A4 | Payment Reminder | 🟢 Done |
| A5 | Agenda Conflict Detection | 🟢 Done |
| A6 | Overdue Tasks | 🟢 Done |
| A7 | Unexpected Weather Alert | 🟢 Done |
| A8 | Relationship Maintenance | ⏭️ Skipped (low utility) |
| A9 | Subscription Expiring | 🟢 Done |
| A10 | Package Tracking Central | 🟢 Done |
| A11 | Competitive Intelligence | 📦 Work Pack (future) |
| A12 | Content Creator Assistant | 📦 Work Pack (future) |

---

## 🅱️ B-TIER — Nice to Have (6/14 Done)

| # | Feature | Nota | Status |
|---|---------|------|--------|
| B1 | **Sleep/Wake Routine** | 8/10 | 🟢 Done |
| B2 | **Commute Optimizer** | 8/10 | 🟢 Done |
| B3 | Exercise Reminder | 7/10 | 🔴 Future |
| B4 | Hydration/Break | 6/10 | 🔴 Future |
| B5 | Meal Planner | 7/10 | 🔴 Future |
| B6 | **Focus Mode** | 8/10 | 🟢 Done |
| B7 | **Daily Summary** | 8/10 | 🟢 Done |
| B8 | **Weekly Planner** | 9/10 | 🟢 Done |
| B9 | Habit Tracker | 7/10 | 🔴 Future |
| B10 | Energy Advisor | 7/10 | 🔴 Future (needs device) |
| B11 | Recipe Suggestions | 7/10 | 🔴 Future |
| B12 | Language Learning | 6/10 | 🔴 Future |
| B13 | Meditation Guide | 6/10 | 🔴 Future |
| B14 | Joke/Fun | 5/10 | 🔴 Future |

---

## 🅲 C-TIER — Future / Low Priority (1/10 Done)

| # | Feature | Nota | Status |
|---|---------|------|--------|
| C1 | Laundry Reminder | 4/10 | 🔴 Future |
| C2 | Plant Watering | 3/10 | 🔴 Future |
| C3 | Pet Care | 5/10 | 🔴 Future |
| C4 | Car Maintenance | 6/10 | 🔴 Future |
| C5 | **Budget Tracker** | 8/10 | 🟢 Done |
| C6 | Gift Ideas | 5/10 | 🔴 Future |
| C7 | Reading List | 5/10 | 🔴 Future |
| C8 | Event Discovery | 6/10 | 🔴 Future |
| C9 | DIY Assistant | 4/10 | 🔴 Future |
| C10 | Music DJ | 6/10 | 🔴 Future |

---

## 💡 NEW IDEAS (3/5 Done)

| # | Feature | Nota | Status |
|---|---------|------|--------|
| N1 | **Discovery Engine** | 9/10 | 🟢 Done |
| N2 | **Mood Detection** | 8/10 | 🟢 Done |
| N3 | **Weekly Wins Recap** | 8/10 | 🟢 Done |
| N4 | **Smart Follow-up** | 10/10 | 🟢 Done |
| N5 | Context-aware Silence | 7/10 | 🔴 Future |

---

## 🔗 INTEGRATIONS — Done

| Integration | Status |
|------------|--------|
| WhatsApp Business (Cloud API) | 🟢 Done — onboarding, FOMO, plan-gating |
| GitHub OAuth (user connects) | 🟢 Done — OAuth App + admin token |
| DevGit Bridge (Dev → GitHub push) | 🟢 Done — code preview + batch push |
| Phone registration + auto welcome | 🟢 Done — WhatsApp/Telegram welcome |

---

## 📦 WORK PACK (Future Add-on — +€9.99/mês)

Professional features for work:
- A11 Competitive Intelligence
- A12 Content Creator Assistant
- Meeting Summaries
- CRM Lite
- Invoice Generator
- LinkedIn Assistant

---

## 📊 Resumo

| Tier | Total | Done | Pendentes |
|------|-------|------|-----------|
| Sprint 0 (Security) | 11 | 11 ✅ | 0 |
| Frontend Security | 6 | 6 ✅ | 0 |
| Performance | 8 | 8 ✅ | 0 |
| S-TIER | 9 | 9 ✅ | 0 |
| A-TIER | 12 | 9 ✅ | 1 ⏸️ + 2 📦 |
| B-TIER | 14 | 6 ✅ | 8 (future) |
| C-TIER | 10 | 1 ✅ | 9 (future) |
| New Ideas | 5 | 4 ✅ | 1 (future) |
| Integrations | 4 | 4 ✅ | 0 |
| **Total** | **79** | **58 ✅** | **21** |

---

## 🧪 Test Metrics

| Metric | Value |
|--------|-------|
| Tests passing | 3825 |
| Tests failing | 0 |
| Coverage | 79.31% |
| Ruff errors | 0 |

---

## 📅 Próximos Passos

1. **Device Android** — RK3566 chegou, configurar kiosk + WebSocket + wake word
2. **19 features restantes** (nota ≤7) — quando app estiver rodando em produção
3. **Work Pack** — módulo profissional como add-on pago
4. **Business verification** — Meta/WhatsApp live mode

---

## 🔧 PROACTIVE INTEGRATIONS — ✅ COMPLETE

| Integration | Status |
|------------|--------|
| 17TRACK API fix — removed RealTime, uses /register + /gettrackinfo | 🟢 Done |
| 17TRACK Webhook — push notifications on status change | 🟢 Done |
| Email → Auto-detect tracking numbers from shipping emails | 🟢 Done |
| Proactive tracking loop — scan emails + check updates + alert | 🟢 Done |
| Webhook → Notification — 17TRACK push → proactivity_feed | 🟢 Done |
| Notification Triggers — daily limit 50, push error 10, min quota 20 | 🟢 Done |
