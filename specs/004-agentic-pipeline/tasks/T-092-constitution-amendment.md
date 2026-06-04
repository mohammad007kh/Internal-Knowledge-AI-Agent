# T-092-constitution-amendment

**Status**: Pending
**Created**: 2026-06-04 | **Completed**: N/A

## Implementation Context

- **Platform**: web · **Task Target**: shared (governance docs)
- **Subagents Enabled**: yes · **Type**: governance task (amendment process)

## Requirement Mapping

| Requirement | Description | Priority |
|-------------|-------------|----------|
| FR-026 | Rollout completion (constitution must describe the shipped pipeline accurately) | P6 |

**User Story**: US-6 (governance closure; flagged in plan Constitution Check + research R11)

## 📋 Embedded Context (READ THIS FIRST)

### Why this task exists
`memory/constitution.md` Article IV says "The LangGraph **8-node pipeline**
is the only permitted code path" — a descriptive node-count that becomes
stale when the agentic graph ships. The PRINCIPLES are unchanged and were
verified in planning: single pipeline path, guardrail input/output wrap
every request and cannot be bypassed, reflector defaults OFF. Only the
wording needs amending — via the standard process, never silently.

### Amendment process (constitution Governance section — follow exactly)
1. Documented reason. 2. Impact analysis (what changes, what breaks).
3. Update `specs/_defaults/registry.yaml` + `changelog.md` if any registry
key is affected (none expected). 4. Explicit human approval.

## Task Objective

Amend Article IV's wording to describe the planner-based pipeline without
weakening any principle, via the standard amendment process.

## Technical Implementation Detail

### Files to Modify
- `memory/constitution.md` — Article IV: replace "8-node pipeline" phrasing
  with a topology-neutral statement, e.g. "The LangGraph agent pipeline
  (planner-based plan-and-execute as of feature 004) is the only permitted
  code path for answering user queries." Keep verbatim: guardrails on every
  request, no bypass, Reflection Node defaults OFF. Add: "All execution
  loops are bounded (steps, retries, revisions, token ceiling, deadline)" —
  codifying the 004 loop-safety rule as a principle.
- `specs/_defaults/changelog.md` — amendment entry (reason, impact, approval).

### Dependencies
- [T-058-agentic-graph-assembly](./T-058-agentic-graph-assembly.md) — amend only once the described reality exists

### Implementation Steps
1. Draft the amendment diff + one-paragraph impact analysis.
2. Present to the owner for explicit approval (HUMAN-GATE).
3. Apply; append changelog entry with approval record.

### Acceptance Criteria
- [ ] Article IV no longer states a fixed node count; principles intact verbatim
- [ ] Loop-bounding codified as a principle
- [ ] Changelog entry with documented reason + human approval
- [ ] No other constitution article touched

## Verification Command

```bash
grep -c "8-node" memory/constitution.md | grep -q "^0$" && grep -q "bounded" memory/constitution.md && grep -q "guardrail" memory/constitution.md && echo AMENDMENT-OK
```

**Expected Output**: `AMENDMENT-OK`

## Completion Checklist
- [ ] Implementation complete
- [ ] Acceptance criteria met (incl. human approval recorded)
- [ ] Verification passes
- [ ] Updated traceability.md
