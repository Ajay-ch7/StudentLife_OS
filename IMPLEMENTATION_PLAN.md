# Multi-Agent Orchestration Layer for StudentLife OS

> [!IMPORTANT]
> **Design Decisions Locked** — Two key decisions resolved before implementation begins:
> 1. **Fallback on failure**: If the Orchestrator fails (Gemini error, snapshot error, timeout), it silently falls through to the existing isolated agent workflow. No execution is blocked. A warning is logged to `ActivityLog` with `activity_type="orchestration_fallback"`.
> 2. **Approval gate**: High-impact orchestrated decisions (any plan involving ≥2 agent actions, or any rescheduling/task mutation) are **never executed autonomously**. The Orchestrator posts its full plan of action to Telegram and creates an `ApprovalRequest`, then waits. Execution only happens after the user sends `/approve <id>`.

## Overview

The four existing agents — **Inbox Agent**, **Management Agent**, **Job Agent**, and **DSA Agent** — each currently operate in complete isolation. Each has its own workflow, its own LLM call, and no awareness of the others. The Inbox Agent processes an email and creates tasks. The Job Agent evaluates a posting and pushes a DSA practice task. The DSA Agent tracks LeetCode progress. The Management Agent (via `EmailToActionWorkflow`) checks calendar and existing tasks — but only from its own perspective.

This plan adds a central **Orchestrator** that intercepts each agent's trigger event, determines which other agents' contexts are relevant, collects that context sequentially, and funnels the merged state into a **single combined LLM reasoning call** before any writes happen. The existing agent service code (services, workflows, tools) is **not touched**. Only a new orchestration layer is added on top.

---

## Proposed Changes

### 1. Agent Context Providers (New Layer)

Each agent exposes a new read-only "context snapshot" method — a pure function that queries its state from the database and returns a structured dictionary. These are **not** new classes; they are static methods added to each existing service.

---

#### [MODIFY] [`inbox_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/inbox_service.py)

Add a static method `get_context_snapshot(db, user_id)` to `InboxService`.

Returns:
```json
{
  "pending_tasks": [...],
  "recent_emails": [...],
  "upcoming_deadlines": [...],
  "conflict_windows": [...]
}
```

This is a read-only query — no writes. The Orchestrator calls this after Inbox extraction to let the Management Agent see what was just found, before anything is persisted.

---

#### [MODIFY] [`dsa_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/dsa_service.py)

Add a static method `get_context_snapshot(db, user_id)` to `DSAService`.

Returns:
```json
{
  "dsa_summary": { "total": 45, "streak": 6, "weak_topics": ["DP", "Graphs"] },
  "job_application_readiness": [...],
  "scheduled_dsa_sessions": [...],
  "active_dsa_tasks": [...]
}
```

The Orchestrator calls this when the event touches DSA sessions or job opportunities. Specifically: when an email deadline conflicts with a planned DSA session, or when a new job posting arrives.

---

#### [MODIFY] [`job_agent_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/job_agent_service.py)

Add a static method `get_context_snapshot(db, user_id)` to `JobAgentService`.

Returns:
```json
{
  "active_pipelines": [
    { "company": "Google", "match_score": 92, "readiness_score": 78, "sop_status": "drafted" }
  ],
  "pending_applications": 3,
  "weak_topics_across_roles": ["Dynamic Programming", "Graphs"]
}
```

Called by Orchestrator when a new email mentions a job or when a DSA update should trigger SOP readiness re-evaluation.

---

#### [MODIFY] [`scheduling_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/scheduling_service.py)

Add a standalone function `get_management_context_snapshot(db, user_id)` (not a class — consistent with existing file style).

Returns:
```json
{
  "upcoming_events": [...],
  "task_load": { "urgent": 2, "high": 4, "total_pending": 11 },
  "free_blocks_today": [["18:00", "20:00"]],
  "conflict_risk_level": "medium"
}
```

This is the "Management Agent" context. Called for every orchestrated event since schedule and task load always affect priority reasoning.

---

### 2. Orchestrator (New File)

#### [NEW] [`backend/app/services/orchestrator.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/orchestrator.py)

Central service class: `MultiAgentOrchestrator`.

**Key responsibilities:**
1. Receive an `OrchestratorEvent` (trigger type + raw payload).
2. Determine which agents are relevant using a routing table.
3. Call each relevant agent's `get_context_snapshot()` — **read-only, no side effects**.
4. Combine the snapshots into a unified `CombinedAgentContext` dict.
5. Build a **single merged prompt** via the new `build_orchestrated_reasoning_prompt()` function.
6. Call Gemini once with the full merged context.
7. Parse the `OrchestratedDecision` (which agents to execute, what to do, and why).
8. Dispatch execution commands back to each relevant agent's workflow `.run()`.
9. Log the reasoning, all agent actions, and the unified decision to `activity_logs` with a shared `orchestration_workflow_id`.

**Event routing table** (maps trigger type → relevant agents):

| Trigger Event | Inbox | Management | DSA | Job |
|---|---|---|---|---|
| `new_email` | ✅ primary | ✅ always | if DSA session conflict | if job-related email |
| `new_leetcode_solve` | — | ✅ always | ✅ primary | ✅ always (readiness update) |
| `new_job_posting` | — | ✅ always | ✅ always | ✅ primary |
| `calendar_conflict` | — | ✅ primary | if DSA session affected | — |
| `manual_task_create` | ✅ | ✅ primary | if DSA task | — |
| `morning_briefing` | ✅ | ✅ | ✅ | ✅ |

```python
class OrchestratorEventType(str, Enum):
    NEW_EMAIL = "new_email"
    NEW_LEETCODE_SOLVE = "new_leetcode_solve"
    NEW_JOB_POSTING = "new_job_posting"
    CALENDAR_CONFLICT = "calendar_conflict"
    MANUAL_TASK_CREATE = "manual_task_create"
    MORNING_BRIEFING = "morning_briefing"

@dataclass
class OrchestratorEvent:
    event_type: OrchestratorEventType
    user_id: int
    payload: dict[str, Any]
    workflow_id: str = field(default_factory=lambda: f"orch-{uuid.uuid4().hex[:8]}")
```

**`MultiAgentOrchestrator.run(event, db)` method flow:**

```
1. route_agents(event_type, payload) → list[AgentName]
2. try:
     for each agent in route → collect context snapshot (asyncio.gather in parallel)
   except Exception:
     log ActivityLog(activity_type="orchestration_fallback", reason=error)
     return OrchestratedResult(status="fallback")  ← caller uses isolated agent
3. merged_context = merge_contexts(snapshots)
4. prompt = build_orchestrated_reasoning_prompt(event, merged_context)
5. try:
     decision = await gemini.reason_orchestrated(prompt) → OrchestratedDecision
   except Exception:
     log orchestration_fallback
     return OrchestratedResult(status="fallback")
6. log_orchestration_decision(db, user_id, workflow_id, decision)
7. is_high_impact = len(decision.agent_actions) >= 2
                     or any action involves rescheduling / task mutation
   if is_high_impact:
     # APPROVAL GATE — post plan, do NOT execute
     approval_req = ApprovalService.create(
         action_type="orchestrated_plan",
         description=decision.telegram_summary,
         metadata_json=json.dumps(decision.agent_actions)
     )
     send_telegram_plan_preview(decision, approval_req.id)
     return OrchestratedResult(status="pending_approval", approval_id=approval_req.id)
   else:
     # LOW-IMPACT — single-agent, non-destructive action, execute autonomously
     for each agent action in decision.agent_actions:
         await dispatch_to_agent(agent, action, db, user_id, workflow_id)
     send_telegram_summary(decision)
     return OrchestratedResult(status="executed")
```

> [!IMPORTANT]
> **High-impact threshold**: An orchestrated decision is considered high-impact (requires approval) if it involves **2 or more agent actions**, OR if any single action is a `reschedule_event`, `update_task_priority` mutation, `push_dsa_practice_task`, or `trigger_sop_regen`. Low-impact actions (e.g., a single `create_task` from a clearly new email with no conflicts) are executed immediately without approval.

**Telegram Approval Plan Preview Format:**
```
🤖 Orchestrator Plan — Awaiting Your Approval
Approval ID: #42

📋 Reasoning:
New OS Assignment 3 (due Sep 10) conflicts with your DSA Graphs session
(Sep 10, 8PM). Rescheduling the session preserves your streak.

📌 Planned Actions:
  1. [Inbox]      Create task "OS Assignment 3" — priority URGENT, due Sep 10
  2. [Management] Reschedule "DSA Session - Graphs" → Sep 11, 6:00 PM
  3. [DSA]        Preserve streak — abbreviated 30-min session flagged

Reply /approve 42 to execute all actions, or /reject 42 to cancel.
```

**`OrchestratedDecision` schema (LLM output):**
```json
{
  "reasoning": "A clear multi-line explanation referencing all agent contexts",
  "priority_override": "urgent | high | medium | low | null",
  "agent_actions": [
    {
      "agent": "inbox",
      "action": "create_task",
      "parameters": { "title": "OS Assignment 3", "deadline": "2026-09-10T23:59:00Z", "priority": "urgent" },
      "rationale": "Extracted from email, confirmed no duplicate in management context"
    },
    {
      "agent": "management",
      "action": "reschedule_event",
      "parameters": { "event_title": "DSA Session - Graphs", "new_start": "2026-09-11T18:00:00Z" },
      "rationale": "DSA session conflicts with new assignment deadline window"
    },
    {
      "agent": "dsa",
      "action": "update_session_goal",
      "parameters": { "topic": "Graphs", "preserve_streak": true },
      "rationale": "Session moved; streak preservation requires a 30-min abbreviated session"
    }
  ],
  "skip_agents": ["job"],
  "skip_reason": "Email is not job-related; no pipeline changes needed",
  "telegram_summary": "📩 OS Assignment 3 detected (due Sep 10). Moved DSA Graphs session to Sep 11 6PM to avoid conflict."
}
```

---

### 3. Orchestrated Reasoning Prompt (New Function)

#### [MODIFY] [`backend/app/services/prompt_builder.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/prompt_builder.py)

Add `build_orchestrated_reasoning_prompt(event, merged_context)`.

The prompt structure:
```
You are the OpenClaw Multi-Agent Orchestrator for StudentLife OS.
An event has occurred that may affect multiple agents. You have been given
the complete, live context from all relevant agents. Reason across ALL agents
before deciding what each one should do.

== EVENT ==
Type: new_email
Payload: { "subject": "OS Assignment 3 Due", "deadline": "2026-09-10T23:59:00Z" }

== INBOX AGENT CONTEXT ==
Pending tasks: [...]
Upcoming deadlines: [...]
No duplicate found for "OS Assignment 3"

== MANAGEMENT AGENT CONTEXT ==
Task load: urgent=2, high=4, total=11
Upcoming events: [DSA Session Graphs — Sep 10, 8PM–10PM]
Free blocks today: [6PM–8PM]
Conflict risk: HIGH — New deadline (Sep 10) overlaps with DSA session (Sep 10, 8PM)

== DSA AGENT CONTEXT ==
Current streak: 6 days
Weak topics: Dynamic Programming, Graphs
Scheduled DSA sessions: [Graphs — Sep 10, 8PM]
Job application readiness: Google=78%, Microsoft=65%

== JOB AGENT CONTEXT ==
[SKIPPED — email is not job-related]

INSTRUCTIONS:
1. Do NOT make decisions for a single agent in isolation.
2. Consider all provided contexts before generating agent_actions.
3. If rescheduling is needed, prefer the next available free block.
4. Preserve the student's DSA streak wherever possible.
5. If a conflict is unresolvable, escalate with a Telegram alert and request approval.
6. Return ONLY valid JSON matching the OrchestratedDecision schema.
```

---

### 4. Gemini Service Extension

#### [MODIFY] [`backend/app/services/gemini_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/gemini_service.py)

Add method `reason_orchestrated(prompt: str) -> OrchestratedDecision`.

- Calls `self.client.generate_json(prompt, system_instruction=...)`.
- Validates and parses into `OrchestratedDecision` using `validate_structured_output`.
- System instruction: *"You are the OpenClaw Multi-Agent Orchestrator. Reason holistically across all agent contexts. Never act on a single agent's data alone. Return only valid JSON."*

---

### 5. Orchestration Schema (New File)

#### [NEW] [`backend/app/schemas/orchestration_schemas.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/schemas/orchestration_schemas.py)

Pydantic models:

```python
class AgentActionItem(BaseModel):
    agent: Literal["inbox", "management", "dsa", "job"]
    action: str
    parameters: dict[str, Any]
    rationale: str

class OrchestratedDecision(BaseModel):
    reasoning: str
    priority_override: str | None
    agent_actions: list[AgentActionItem]
    skip_agents: list[str] = []
    skip_reason: str | None = None
    telegram_summary: str

class OrchestratedResult(BaseModel):
    orchestration_id: str
    event_type: str
    agents_consulted: list[str]
    agents_executed: list[str]
    decision: OrchestratedDecision
    execution_log: list[dict[str, Any]]
    status: str
```

---

### 6. Workflow Dispatcher (Inside Orchestrator)

The `dispatch_to_agent()` method in `MultiAgentOrchestrator` maps each `AgentActionItem` to the correct existing workflow or service call:

| `agent` + `action` | Existing Entry Point |
|---|---|
| `inbox` + `create_task` | `InboxService.process_content()` or direct `Task` model write |
| `management` + `reschedule_event` | `scheduling_service.update_event()` |
| `management` + `create_event` | `scheduling_service.create_event()` |
| `management` + `update_task_priority` | Direct `Task` model update |
| `dsa` + `update_session_goal` | `DSAService.sync_progress()` + calendar event update |
| `dsa` + `reschedule_dsa_session` | `scheduling_service.update_event()` filtered for DSA events |
| `job` + `trigger_sop_regen` | `job_agent_service.regenerate_sop()` |
| `job` + `push_dsa_practice_task` | Direct `Task` model write (category=`dsa`, source=`orchestrator`) |

No existing service method signatures are changed. The dispatcher acts as a **thin adapter** calling them with the correct arguments extracted from `AgentActionItem.parameters`.

---

### 7. Integration into Existing Trigger Points

The Orchestrator is **wired into existing trigger points** — not replacing them, but being called before they execute:

#### [MODIFY] [`openclaw/workflows/email_to_action_workflow.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/openclaw/workflows/email_to_action_workflow.py)

After the email is normalized (step 2) and **before** the LLM call (step 3):

```python
# NEW: Trigger orchestrator for cross-agent context
orchestration_result = await orchestrator.run(
    OrchestratorEvent(
        event_type=OrchestratorEventType.NEW_EMAIL,
        user_id=user_id,
        payload=normalized.model_dump(),
    ),
    db=db,
)
# If orchestrator handled it, return orchestration_result and skip isolated execution
if orchestration_result.status == "orchestrated":
    return orchestration_result.to_workflow_result()
# Otherwise, fall through to existing isolated logic (backward compatibility)
```

This preserves full backward compatibility — if the Orchestrator raises or returns a non-orchestrated result, the existing workflow continues as-is.

#### [MODIFY] [`backend/app/services/realtime_sync_service.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/realtime_sync_service.py)

In `sync_gmail_inbox()`, replace direct `self.email_workflow.run()` call with `orchestrator.run(NEW_EMAIL event)` — the Orchestrator internally calls the email workflow after gathering cross-agent context.

#### [MODIFY] [`openclaw/workflows/dsa_workflow.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/openclaw/workflows/dsa_workflow.py)

After LeetCode solve detection, before sending the Telegram message:

```python
orchestration_result = await orchestrator.run(
    OrchestratorEvent(
        event_type=OrchestratorEventType.NEW_LEETCODE_SOLVE,
        user_id=user_id,
        payload={"newly_solved": newly_solved, "username": username},
    ),
    db=db,
)
```

#### [MODIFY] [`openclaw/workflows/job_workflow.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/openclaw/workflows/job_workflow.py)

Before calling `job_agent_service.process_job_posting()`:

```python
orchestration_result = await orchestrator.run(
    OrchestratorEvent(
        event_type=OrchestratorEventType.NEW_JOB_POSTING,
        user_id=user_id,
        payload={"job_text": job_text, ...},
    ),
    db=db,
)
```

---

### 8. Orchestration Log Model (New DB Column / Table)

#### [MODIFY] [`backend/app/models/activity_log.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/models/activity_log.py)

Add `orchestration_id: str | None` column to `ActivityLog`. This allows all activity_log entries generated during a single orchestrated workflow to be correlated by a shared `orchestration_id`.

All `AuditService.log_user_activity()` calls dispatched from the Orchestrator pass the shared `orchestration_id` in their `metadata` dict. No schema migration tooling needed — SQLite `ALTER TABLE` is run on startup via `init_db()`.

> [!NOTE]
> The existing `AgentAction` and `ActivityLog` tables are fully reused. No new tables are created. The Orchestrator's reasoning and decisions are stored as `activity_type="orchestration_decision"` entries in `ActivityLog`, with the full JSON decision in `metadata_json`.

---

### 9. API Endpoint (New Route)

#### [NEW] [`backend/app/api/v1/orchestrator.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/api/v1/orchestrator.py)

A new `POST /api/v1/orchestrate` endpoint that allows manual triggering of an orchestrated event from the frontend or Telegram:

```
POST /api/v1/orchestrate
{
  "event_type": "new_job_posting",
  "payload": { "job_text": "...", "company": "Google" }
}
→ OrchestratedResult
```

Also adds `GET /api/v1/orchestrate/history?limit=20` to retrieve recent orchestration decision logs.

#### [MODIFY] [`backend/app/main.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/main.py)

Register the new orchestrator router:
```python
from app.api.v1 import orchestrator
app.include_router(orchestrator.router, prefix="/api/v1")
```

---

### 10. Telegram Command Extension

#### [MODIFY] [`backend/app/services/telegram_bot_listener.py`](file:///c:/Users/kriti/.vscode/StudentLife_OS/backend/app/services/telegram_bot_listener.py)

Add `/orchestrate` command to `handle_command()`:

```
/orchestrate — Show the last orchestration decision and which agents were involved
/orchestrate job <text> — Manually trigger a job posting through the full orchestration pipeline
```

This surfaces orchestration transparency directly in Telegram alongside the existing `/explain` and `/why` commands.

---

## Detailed Cross-Agent Workflow Examples

### Example A: New Email with Assignment Deadline

```
Trigger: New Gmail email detected in RealtimeSyncService
↓
Orchestrator.run(NEW_EMAIL event)
↓
Route: Inbox ✅, Management ✅, DSA (if DSA session conflict), Job (if job-related)
↓
Parallel context gather:
  - InboxService.get_context_snapshot()     → pending tasks, recent deadlines
  - get_management_context_snapshot()       → free blocks, task load, calendar events
  - DSAService.get_context_snapshot()       → sessions, streak, weak topics
↓
Build merged prompt (all 3 contexts combined)
↓
Single Gemini call → OrchestratedDecision
  agent_actions:
    inbox:      create_task "OS Assignment 3"  (deadline Sep 10, priority urgent)
    management: reschedule DSA session          (Sep 10 8PM → Sep 11 6PM)
    dsa:        preserve streak flag            (30-min abbreviated session)
↓
Dispatch execution:
  InboxService.process_content()   → Task created
  scheduling_service.update_event() → DSA session rescheduled
  DSAService.sync_progress()        → Streak preservation noted
↓
AuditService logs all 3 actions with shared orchestration_id
↓
Telegram: "📩 OS Assignment 3 added (urgent, Sep 10). DSA Graphs session moved to Sep 11."
```

### Example B: New LeetCode Solve

```
Trigger: LeetCode watcher detects new accepted submission (Graphs - Medium)
↓
Orchestrator.run(NEW_LEETCODE_SOLVE event)
↓
Route: DSA ✅ primary, Management ✅, Job ✅ (readiness update)
↓
Context gather:
  - DSAService.get_context_snapshot()       → streak now 7, Graphs improving
  - get_management_context_snapshot()       → scheduled DSA session tonight?
  - JobAgentService.get_context_snapshot()  → Google readiness 78% → now 81%?
↓
Merged prompt → Gemini reasoning
↓
OrchestratedDecision:
  agent_actions:
    dsa:  sync_progress (update Graphs solved count)
    job:  update_readiness_note for Google pipeline (Graphs no longer weakest)
    management: (no rescheduling needed — existing session confirmed)
↓
Telegram: "🎉 Graphs problem solved! Streak: 7 days. Google readiness ↑ to ~81%. Tonight's session still on schedule."
```

### Example C: New Job Posting

```
Trigger: POST /api/v1/jobs or email with job keywords
↓
Orchestrator.run(NEW_JOB_POSTING event)
↓
Route: Job ✅ primary, Management ✅, DSA ✅, Inbox (no)
↓
Context gather:
  - JobAgentService.get_context_snapshot()  → existing pipelines, weak topics
  - DSAService.get_context_snapshot()       → current readiness for role
  - get_management_context_snapshot()       → task load, free blocks for prep
↓
Merged prompt → Gemini reasoning
↓
OrchestratedDecision:
  agent_actions:
    job:        process_job_posting → parse + SOP draft
    dsa:        push_dsa_practice_task for "Dynamic Programming" (identified gap)
    management: schedule_event "Amazon Interview Prep" in next free 2-hour block
↓
Telegram: "💼 Amazon SDE Intern (match 87%). SOP drafted. DP practice task added. Prep session scheduled Sat 4PM."
```

### Example D: Morning Briefing

```
Trigger: Scheduled morning_briefing workflow
↓
Orchestrator.run(MORNING_BRIEFING event)
↓
Route: ALL four agents
↓
All four context snapshots gathered in parallel
↓
Merged prompt → single Gemini call
↓
OrchestratedDecision:
  reasoning: "High task load (2 urgent), DSA streak active, Google SOP needs finalization, no calendar conflicts today"
  agent_actions:
    management: generate_briefing with consolidated priorities
    dsa:        flag top recommended problem for today
    job:        surface SOP requiring student review
    inbox:      flag 1 unread email with action needed
↓
Single consolidated morning briefing message via Telegram, not four separate ones
```

---

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────┐
│                    TRIGGER SOURCES                               │
│  Gmail Sync  │  LeetCode Watcher  │  Job POST  │  Telegram Cmd  │
└──────────────┴────────────────────┴────────────┴────────────────┘
                              │
                              ▼
                  ┌───────────────────────┐
                  │  MultiAgentOrchestrator│  (NEW)
                  │  orchestrator.py       │
                  └──────────┬────────────┘
                             │ 1. Route agents
                             │ 2. Gather contexts (parallel)
                             │ 3. Build merged prompt
                             │ 4. Single Gemini call
                             │ 5. Dispatch execution
                             │
          ┌──────────────────┼──────────────────┬────────────────────┐
          ▼                  ▼                  ▼                    ▼
  ┌──────────────┐  ┌────────────────┐  ┌────────────┐  ┌──────────────────┐
  │ Inbox Agent  │  │ Management     │  │ DSA Agent  │  │  Job Agent       │
  │ (UNCHANGED)  │  │ Agent          │  │ (UNCHANGED)│  │  (UNCHANGED)     │
  │              │  │ (UNCHANGED)    │  │            │  │                  │
  │ +get_context │  │ +get_context   │  │+get_context│  │  +get_context    │
  │ _snapshot()  │  │ _snapshot()    │  │_snapshot() │  │  _snapshot()     │
  └──────────────┘  └────────────────┘  └────────────┘  └──────────────────┘
          │                  │                  │                    │
          └──────────────────┴──────────────────┴────────────────────┘
                                       │
                                       ▼
                           ┌─────────────────────┐
                           │   SQLite (shared)    │
                           │   ActivityLog +      │
                           │   orchestration_id   │
                           └─────────────────────┘
```

---

## Resolved Design Decisions

> [!NOTE]
> **Fallback on Failure (Resolved ✅)**: If the Orchestrator fails at any point (context snapshot error, Gemini error, schema parse failure), it silently falls through to the existing isolated agent workflow. No execution is blocked. A `ActivityLog` entry with `activity_type="orchestration_fallback"` and the exception message is written for observability. The student will never see a broken experience because of the orchestration layer.

> [!NOTE]
> **Approval Gate (Resolved ✅)**: High-impact orchestrated decisions (≥2 agent actions, or any action of type `reschedule_event`, task mutation, `trigger_sop_regen`) are **never executed automatically**. The Orchestrator posts a structured plan-of-action preview to Telegram with the `ApprovalRequest` ID. The student must reply `/approve <id>` to execute all actions in sequence. Only single, non-destructive low-impact actions (e.g., creating one new task for a clearly new assignment with no conflicts) are executed autonomously without approval.

> [!NOTE]
> **Context Snapshot Freshness**: All snapshots are read at the moment the event fires, before any writes. This is safe — the pre-event database state is always the correct basis for cross-agent reasoning.

> [!NOTE]
> **Parallel Context Gathering**: `asyncio.gather()` is used for all snapshots simultaneously. Since the Orchestrator only reads state before any execution, there is no ordering dependency between snapshots.

---

## Verification Plan

### Automated Tests
- `pytest tests/test_orchestrator.py` — New unit tests for:
  - `route_agents()` routing logic for each event type
  - `merge_contexts()` context merging correctness
  - `dispatch_to_agent()` correct service mapping
  - Fallback behavior when Orchestrator raises

### Manual Verification
1. Send a test email with an assignment deadline that conflicts with an existing DSA calendar session → verify both a task is created AND the session is rescheduled in one coordinated action.
2. Submit a new LeetCode problem via the LeetCode watcher → verify the Job Agent's pipeline readiness score is updated in the same orchestration run.
3. POST a job posting via `/api/v1/jobs` → verify a DSA practice task AND a calendar prep event are created in the same orchestration run.
4. Run `/orchestrate` in Telegram → verify the last decision with all agents consulted is displayed.
5. Check `ActivityLog` in the database → all entries from a single orchestrated run should share the same `orchestration_id` in their metadata.
