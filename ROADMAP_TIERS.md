# CAPIVAREX — Intelligence Roadmap (All Tiers)

## Status: 🟢 Done | 🟡 In Progress | 🔴 Todo

---

## 🔒 SPRINT 0 — Security Fixes (BEFORE any new features)

| # | Fix | Prioridade | Status |
|---|-----|-----------|--------|
| F1 | JWT_SECRET_KEY crash se vazio em prod | CRÍTICO | 🔴 |
| F2 | Rate limiter verify_signature: True | CRÍTICO | 🔴 |
| F3 | /dev/test → get_admin_user | CRÍTICO | 🔴 |
| F4 | Webhook email + autenticação HMAC | CRÍTICO | 🔴 |
| F5 | Subprocess env={} (sandbox) | ALTO | 🔴 |
| F6 | Admin hmac.compare_digest | ALTO | 🔴 |
| F7 | CORS allow_headers restrito | MÉDIO | 🔴 |
| F8 | Timer race condition (Redis atomic) | ALTO | 🔴 |
| F9 | Supabase sync→async (to_thread) | ALTO | 🔴 |
| F10 | Fire-and-forget exception handlers | ALTO | 🔴 |
| F11 | Env var validation no startup | MÉDIO | 🔴 |

---

## ⭐ S-TIER — Core Intelligence (COMPLETO ✅)

| # | Feature | Descrição | Status |
|---|---------|-----------|--------|
| S1 | Morning Briefing | Weather + calendar + finance humanizado | 🟢 Done |
| S2 | Meeting Briefing | Prep 2h antes com RAG context | 🟢 Done |
| S3 | Finance Alerts | Alertas de preço stocks/crypto | 🟢 Done |
| S4 | Weekly Finance Recap | Resumo semanal + watchlist | 🟢 Done |
| S5 | Personalized News | News por interesses via RAG + Perplexity | 🟢 Done |
| S6 | Travel Planner | Detecção → preferências → roteiro → aprovação | 🟢 Done |
| S7 | Voice → Notes | "Nota que..." → auto-cria notes/reminders | 🟢 Done |
| S8 | Email Triage | "Trata da inbox" → categoriza + extrai acções | 🟢 Done |
| S9 | Meeting Orchestrator | "Marca reunião" → evento + Meet + invite + notes | 🟢 Done |

---

## 🅰️ A-TIER — High Value Features (PRÓXIMO)

| # | Feature | Descrição | Agentes | Esforço |
|---|---------|-----------|---------|---------|
| A1 | **Birthday + Action** (P02) | Detecta aniversários no calendário → sugere presente/mensagem | calendar, research, email | Médio |
| A2 | **Leaving Home Check** (P04) | "Vou sair" → verifica tempo, trânsito, agenda, dispositivos | weather, traffic, calendar, smart home | Médio |
| A3 | **Arriving Home Prep** (P05) | Detecta proximidade → liga luzes, aquecimento, resume | smart home, maps, music | Médio (precisa device) |
| A4 | **Payment Reminder** (P11) | Detecta contas mencionadas → lembra antes do vencimento | notes, reminder, email | Baixo |
| A5 | **Agenda Conflict Detection** (P15) | Detecta sobreposições no calendário → sugere resolução | calendar | Baixo |
| A6 | **Overdue Tasks** (P16) | Detecta tarefas/reminders atrasados → nudge humanizado | notes, reminder | Baixo |
| A7 | **Unexpected Weather Alert** (P17) | Mudança brusca de tempo → alerta proativo | weather, notification | Baixo |
| A8 | **Relationship Maintenance** (P20) | "Faz tempo que não falas com X" → sugere contacto | email, calendar, RAG | Médio |
| A9 | **Subscription Expiring** (P27) | Detecta subscrições a expirar nos emails → alerta | email, notes, reminder | Médio |
| A10 | **Package Tracking Central** (C18) | Tracking automático de encomendas mencionadas em emails | tracking, email | Médio |
| A11 | **Competitive Intelligence** (C23) | Monitora notícias de concorrentes do user | research, finance, RAG | Alto |
| A12 | **Content Creator Assistant** (NEW) | Ajuda a criar conteúdo para redes sociais | research, notes, image | Alto |

---

## 🅱️ B-TIER — Nice to Have

| # | Feature | Descrição | Esforço |
|---|---------|-----------|---------|
| B1 | **Sleep/Wake Routine** (P03) | Rotina nocturna + matinal adaptativa | Médio |
| B2 | **Commute Optimizer** (P06) | Melhor rota diária com trânsito real-time | Médio |
| B3 | **Exercise Reminder** (P07) | Sugere actividade baseado no tempo/agenda | Baixo |
| B4 | **Hydration/Break** (P08) | Lembretes de pausa e hidratação | Baixo |
| B5 | **Meal Planner** (P09) | Sugestões de refeição baseadas em preferências | Médio |
| B6 | **Focus Mode** (P12) | Silencia notificações durante deep work | Baixo |
| B7 | **Daily Summary** (P19) | Resumo do dia ao final da tarde | Baixo |
| B8 | **Weekly Planner** (P21) | Planeia a semana ao domingo | Médio |
| B9 | **Habit Tracker** (P22) | Acompanha hábitos diários | Médio |
| B10 | **Energy Advisor** (C15) | Monitora consumo energético da casa | Alto (precisa device) |
| B11 | **Recipe Suggestions** (C16) | Sugere receitas com ingredientes em casa | Médio |
| B12 | **Language Learning** (C20) | Pratica idiomas via conversa | Médio |
| B13 | **Meditation Guide** (C21) | Guia de meditação adaptativo | Baixo |
| B14 | **Joke/Fun** (C22) | Piadas e entretenimento contextual | Baixo |

---

## 🅲 C-TIER — Future / Low Priority

| # | Feature | Descrição | Esforço |
|---|---------|-----------|---------|
| C1 | **Laundry Reminder** (P23) | Lembra de tirar a roupa da máquina | Baixo |
| C2 | **Plant Watering** (P24) | Lembra de regar as plantas | Baixo |
| C3 | **Pet Care** (P25) | Lembretes de cuidados com animais | Baixo |
| C4 | **Car Maintenance** (P26) | Manutenção programada do carro | Médio |
| C5 | **Budget Tracker** (P28) | Acompanha gastos mensais | Alto |
| C6 | **Gift Ideas** (P29) | Sugere presentes para datas especiais | Médio |
| C7 | **Reading List** (P30) | Sugere livros/artigos baseados em interesses | Baixo |
| C8 | **Event Discovery** (P31) | Descobre eventos locais relevantes | Médio |
| C9 | **DIY Assistant** (C17) | Ajuda com projectos caseiros | Médio |
| C10 | **Music DJ** (C19) | Playlist contextual automática | Médio |

---

## 💡 NEW IDEAS — Sprinkle Across Sprints

| # | Ideia | Descrição | Tier Sugerido |
|---|-------|-----------|---------------|
| N1 | **Discovery Engine** | "Achei que te interessa..." — conteúdo personalizado | A |
| N2 | **Mood Detection** | Adapta tom baseado no mood do user | B |
| N3 | **Weekly Wins Recap** | Celebra conquistas da semana | B |
| N4 | **Smart Follow-up** | Lembra coisas mencionadas em conversas anteriores | A |
| N5 | **Context-aware Silence** | Sabe quando NÃO falar | B |

---

## 📊 Resumo

| Tier | Total Features | Completas | Pendentes |
|------|---------------|-----------|-----------|
| Sprint 0 (Security) | 11 fixes | 0 | 11 |
| S-TIER | 9 | 9 ✅ | 0 |
| A-TIER | 12 | 0 | 12 |
| B-TIER | 14 | 0 | 14 |
| C-TIER | 10 | 0 | 10 |
| New Ideas | 5 | 0 | 5 |
| **Total** | **61** | **9** | **52** |

---

## 📅 Ordem de Execução

1. **Sprint 0** — Security Fixes (obrigatório antes de tudo)
2. **A-TIER** — High value features
3. **B-TIER** — Nice to have
4. **C-TIER** — Future
5. **New Ideas** — Sprinkled along the way
