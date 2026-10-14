---
name: cherny-workflow
description: Six rules for operating a coding session, from Boris Cherny's posts on how the Claude Code team works. Plan-mode default, subagents, lessons capture, verification before done, elegance pass, autonomous bug fixing, plus a tasks/todo.md and tasks/lessons.md convention. Use when starting a multi-step coding task, planning architectural changes, handling a bug report, or after a user correction.
---

# Cherny Workflow Orchestration

Six rules for how a coding agent operates across a session. Companion to behavioral principles like Karpathy guidelines (which cover how the agent thinks about each change). These cover how the agent operates the workflow.

**Tradeoff:** these rules bias toward planning, verification, and capturing learning. They cost some session latency in exchange for fewer surprises, fewer rollbacks, and compounding improvement across sessions. For trivial one-shot tasks, use judgment.

---

## 1. Plan Mode Default

**Plan before non-trivial work. Re-plan on deviation.**

- Enter plan mode for ANY non-trivial task (3+ steps or architectural decisions).
- If something goes sideways, STOP and re-plan immediately.
- Use plan mode for verification steps, not just building.
- Write detailed specs upfront to reduce ambiguity.

Mechanics: cycle into plan mode with `Shift+Tab`, or set `defaultMode: "plan"` in `~/.claude/settings.json`. In plan mode tools are read-only and the agent produces a plan; the user approves before any write.

## 2. Subagent Strategy

**Spawn subagents liberally to keep main context clean.**

- Use subagents liberally to keep the main context window clean.
- Offload research, exploration, and parallel analysis to subagents.
- For complex problems, throw more compute via subagents.
- One task per subagent for focused execution.

Mechanics: subagents live in `.claude/agents/<name>.md` (project) or `~/.claude/agents/<name>.md` (user). Each has its own context window. Write a clear `description` field so Claude routes correctly. Restrict `tools:` per subagent to the minimum surface.

## 3. Self-Improvement Loop

**Capture lessons after every correction. Read them at session start.**

- After ANY correction from the user, update `tasks/lessons.md` (or the project's equivalent like `memory/lessons_*.md`) with the pattern.
- Write rules that prevent the same mistake.
- Ruthlessly iterate until mistake rate drops.
- Review lessons at session start for the relevant project.

The point: a correction is data. Capture it. Forgetting the same correction is the most expensive failure mode for autonomous agents.

**On the second occurrence, promote the lesson to a check.** Trigger: the same correction or review
comment appears a second time. A lessons entry no longer counts as the fix. Action: move it into a
lint rule, hook, type, test or skill, and keep it as prose only when no mechanism can decide it,
with the reason written beside it. Receipt: the entry names the mechanism, and that mechanism goes
red on a deliberately reintroduced instance. Otherwise the status is "correction unenforced".

## 3b. Hold the Decision (repair is not adoption)

An architectural decision stays in force until it is **explicitly** revisited.
Repairing, diagnosing or benchmarking an alternative is a bounded subtask - it
does not select that alternative.

**Counterfactual trigger.** Before the first action that favours an alternative,
ask: *would this action be needed if the current decision definitely stands?*
If no, stop. Either return to the decision, or open an explicit revision:
`new fact -> which original criterion it changes -> full new tradeoff -> confirm`.

"It is already installed / it now works / its CLI is nicer" are not criteria
unless speed of adoption was a selection criterion in the first place.

**Why it needs a mechanical trigger:** drift does not feel like a decision, it
feels like work. Every step is locally sensible; there is no moment of "I am
switching". Attention does not catch it - a checkable question does.

## 4. Verification Before Done

**Never mark a task complete without proving it works.**

- Diff behavior between main and your changes when relevant.
- Ask: "Would a staff engineer approve this?"
- Run tests, check logs, demonstrate correctness.
- Show evidence (test output, log line, diff) before claiming done.

If the staff-engineer check returns "no", do another pass. If unsure, verify with evidence.

## 5. Demand Elegance (Balanced)

**Pause on non-trivial changes. Ask if there is a more elegant way.**

- For non-trivial changes, pause and ask "is there a more elegant way?"
- If a fix feels hacky: "Knowing everything I know now, implement the elegant solution."
- Skip this for simple, obvious fixes. Do not over-engineer.
- Challenge your own work before presenting it.

Trigger phrase: "Knowing everything I know now, implement the elegant solution." Forces a post-hoc rethink after the first working version. The first version often reveals the right shape; rebuild on that knowledge.

## 6. Autonomous Bug Fixing

**Given a bug report, just fix it.**

- Do not ask for hand-holding.
- Point at logs, errors, failing tests, then resolve them.
- Zero context switching required from the user.
- Fix failing CI tests without being told how.
- For a hard bug, follow `diagnosing-bugs`: no hypothesis and no fix before a red-capable loop exists.

Boundary: this assumes the repo is at Standardized level (tests gate merge, CI fails loud, branch protection prevents catastrophe). On an unsafe repo, autonomous fixing is the wrong default.

**Fixing a failing test never means editing the test until it passes.** The agent authors the code
and would then be authoring the proof of its own correctness, which is the first way an oracle stops
being one. If the test is genuinely wrong, that is a separate change with its own reason stated, and
it is not a change to make in the same breath as the fix it unblocks. Say which of the two you are
doing before you touch the file.

---

## Task Management Convention

Two files at `tasks/`:

**`tasks/todo.md`** (per-task, short-lived):

1. Plan First: write the plan with checkable items.
2. Verify Plan: check in with the user before implementing.
3. Track Progress: mark items complete as you go.
4. Explain Changes: high-level summary at each step.
5. Document Results: add a review section at the end.

**`tasks/lessons.md`** (persistent, compounding):

6. Capture Lessons: after corrections, log the pattern and a rule that prevents recurrence.

Adapt file paths to the project's convention if it uses something else (e.g., `memory/lessons_*.md`).

---

## Core Principles

- **Simplicity First.** Every change as simple as possible. Impact minimal code.
- **No Laziness.** Find root causes. No temporary fixes. Senior developer standards.
- **Minimal Impact.** Only touch what is necessary. No side effects, no new bugs.

---

## How to apply

These rules describe agent behavior, not user behavior. Once this skill is loaded:

- Enter plan mode automatically when a task is non-trivial; do not wait for the user to ask.
- Suggest spawning a subagent when work would flood main context (research, multi-file analysis, parallel review).
- After any user correction in this session, propose a `lessons.md` entry capturing the pattern.
- When a correction repeats one already logged, propose the check that refuses it (lint rule, hook, type, test or skill) instead of a second entry, and report "correction unenforced" until that check exists and goes red on a reintroduced instance.
- Before claiming a task is done, run the relevant checks and report evidence.
- For non-trivial changes, after the first working version, pause and ask the elegance question.
- For bug reports, attempt the fix end-to-end (find root cause, fix, verify) before asking the user.

If the user's project conventions conflict with any rule (e.g., "no autonomous commits on customer-facing repos"), the project convention wins. These rules are defaults to apply when no project rule overrides them.

---

## Attribution

The practices come from Boris Cherny's public posts about how the Claude Code team works: plan mode
for complex tasks, subagents such as `code-simplifier` and `verify-app`, a living `CLAUDE.md` updated
after every mistake, fixing bugs end to end from logs, and giving the agent a way to verify its work.
The six rule names, the `tasks/todo.md` and `tasks/lessons.md` convention and the "Core Principles"
block come from a community restructuring of those posts, not from him. Rule 3b and the paragraph on
never editing a test to make it pass are this kit's own. The paragraph in rule 3 on promoting a
lesson to a check on its second occurrence, and the matching "How to apply" bullet, come from Addy
Osmani, "Brownfield agentic engineering" (addyo.substack.com/p/brownfield-agentic-engineering),
2026-09-14, not from Cherny.
