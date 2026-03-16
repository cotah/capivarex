# CAPIVAREX — Intelligence Roadmap
# Status: 🔴 Todo | 🟡 In Progress | 🟢 Done

## S-TIER — Sprint 1 (activate now, agents exist)

### S1. Morning briefing (P01 + C01)
- [ ] Trigger: first message of the day per user
- [ ] Combine: weather + calendar + finance + news
- [ ] Output: one rich message, not 4 separate
- [ ] Store in proactivity_feed for bell icon
- Agents: weather ✅ calendar ✅ finance ✅ research ✅

### S2. Meeting briefing (P14)
- [ ] Trigger: 2h before calendar event
- [ ] Combine: calendar context + notes from past meetings + research
- [ ] Output: "You have meeting with X in 2h. Key points to discuss: ..."
- Agents: calendar ✅ notes ✅ research ✅ email ✅

### S3. Finance alerts (P10) — ALREADY DONE ✅
- finance_alert_service.py exists and runs in proactivity loop

### S4. Weekly finance recap (P13 + C31)
- [ ] Trigger: Monday 09:00 UTC
- [ ] Combine: finance summary + crypto + spending from email
- [ ] Output: weekly report in chat + store in feed
- Agents: finance ✅ crypto ✅ email ✅ notes ✅

### S5. Sector news personalized (P32 + C35)
- [ ] Trigger: daily 08:00 + 18:00 UTC
- [ ] Use RAG interests to personalize query
- [ ] Parse into individual articles (parser already fixed)
- Agents: research ✅ search ✅ notes ✅

### S6. Travel planner proactive (P33)
- [ ] Trigger: detect trip in calendar (location abroad)
- [ ] Phase 1: detect + first contact message
- [ ] Phase 2: ask preferences (3-4 questions)
- [ ] Phase 3: build itinerary with research + weather + maps
- [ ] Phase 4: send summary, let user adjust
- [ ] Phase 5: generate PDF document
- [ ] Phase 6: during-trip alerts (day before each city)
- Agents: calendar ✅ travel ✅ weather ✅ maps ✅ research ✅ notes ✅ reminder ✅

### S7. Voice to notes+reminders (C07)
- [ ] Parse voice transcription for action items
- [ ] Auto-create notes for "note that..." 
- [ ] Auto-create reminders for "remind me..."
- [ ] Auto-add calendar for "schedule..."
- Agents: voice ✅ notes ✅ reminder ✅ calendar ✅

### S8. Email triage (C08)
- [ ] User says "trata da minha inbox"
- [ ] Categorize emails by urgency
- [ ] Extract action items → notes
- [ ] Extract meetings → calendar
- [ ] Draft replies for approval
- Agents: email ✅ calendar ✅ notes ✅ reminder ✅

### S9. Meeting orchestrator (C04)
- [ ] User says "marca reunião com X sobre Y"
- [ ] Check calendar availability
- [ ] Create Meet/Zoom link
- [ ] Draft + send invite email
- [ ] Create meeting notes with agenda
- Agents: calendar ✅ meeting ✅ email ✅ research ✅ notes ✅

## A-TIER — Sprint 2 (high value, moderate effort)

### A1. Birthday + full action (P02)
### A2. Leaving home check (P04) — needs device
### A3. Arriving home prep (P05) — needs device
### A4. Payment reminder (P11)
### A5. Agenda conflict detection (P15)
### A6. Overdue tasks (P16)
### A7. Unexpected weather alert (P17)
### A8. Relationship maintenance (P20)
### A9. Subscription expiring (P27)
### A10. Travel planner full (C05)
### A11. Home automation (C13) — needs device
### A12. Package tracking central (C18)
### A13. Competitive intelligence (C23)
### A14. Smart news feed (C35)

## B-TIER — Sprint 3

### B1-B14. (see ranking document)

## NEW IDEAS — Sprinkle across sprints

### N1. Discovery engine ("achei que te interessa")
### N2. Mood detection (adapta tom)
### N3. Weekly wins recap
### N4. Smart follow-up (lembra coisas mencionadas)
### N5. Context-aware silence (sabe quando não falar)
