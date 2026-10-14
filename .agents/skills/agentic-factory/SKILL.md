---
name: agentic-factory
description: Method for agentic or AI factory work. Decide how much autonomy an agent loop has earned, set an evidence-based autonomy gate and change-size ceiling, audit agent readiness, diagnose why green checks failed to stop a break. Also for oracle quality, checker independence, autonomy pilots, and one canonical term for a value that crosses layers or repositories.
---

# Software factories with agents

An operational method for deciding, on evidence, how much autonomy a specific loop has earned.
It introduces **no new maturity scale**: scoring stays on the existing AI Agent Readiness model
(5 levels, 11 pillars). This tells you WHAT to measure; the scale is unchanged.

The full method, with its sources, the contradictions between them and what they do not answer, is
in `01-method.md`, and two completed audits are in `03-worked-example.md`. Both are in the kit
repository; neither is installed with the rule sets.

## 1. Three levels. Confusing them is the usual implementation error

| Level | What it is | Unit of work |
|---|---|---|
| **Loop** | one agent doing one job in a circle: gather context, act, check, repeat until a condition | one change |
| **Harness** | the walls around the loop: sandbox, available tools, memory between runs, and the gate that defines done | one session |
| **Factory** | many harnessed loops at once, fed by a queue, admitted to trunk through an enforced update protocol, watched by a recovery loop, a human owning the whole | a stream |

People tune the model when the bottleneck is the harness or the gate. Name the level first.

Rule sets operate on different units and therefore do not compete: `simplicity-ladder` governs one
change (minutes), `cherny-workflow` governs one session (hours), this method governs the stream
(weeks). A rule from one level does not fix a problem at another. Careful individual changes do not
pay down debt accumulated by the stream.

## 2. The oracle is the only thing that grants autonomy

An **oracle** is a fast, durable check that decides whether the task was done correctly.

A loop's right to run unattended comes from properties of the oracle, not from the quality of the
model. It must be all three at once:

- **cheap** - runs on every change without spending human attention,
- **frequent** - fires inside the short cycle,
- **unfakeable** - typed gates, property tests, invariants, or a reviewer bound to an external source
  of truth and an explicit rubric.

**Back pressure:** grant exactly as much autonomy as you can verify cheaply and reliably, and no
more.

### Four ways an oracle silently stops being one

More common than model failure.

1. **The oracle lives inside what the agent edits.** The agent authors both the code and the proof
   of its correctness. Remedy: put the check beyond the candidate's reach - a separate repository,
   holdout scenarios, a partner contract, a real device.
2. **The oracle checks something the consumer never sees.** Verification runs against the full
   artifact while the consumer receives a truncated one, so a test that searches the whole artifact
   and never looks at the limit cannot fail. Remedy: check the artifact the consumer receives, after
   truncation, serialization and transport.
3. **The oracle does not execute.** Tests silently skipped by a missing plugin or dependency report
   green. Remedy: prove the declared suite ran, with the number executed and the list skipped.

   For a candidate that asks to land unattended the proof is taken per landing: the protected check
   reads the runner's report, not the exit code, and compares executed test identifiers with the
   suite manifest, kept as a protected list of expected tests, not with the set executed at the base
   SHA, which inherits earlier omissions; the manifest changes only through a reviewed change, which
   is also how new tests enter it. Receipt, bound to the candidate SHA: expected and executed counts
   and every expected test missing or skipped, with a negative control in which a fixture candidate
   that skips one test or exits zero before its assertions turns the check red; otherwise the status
   is "suite execution not established" and a human lands the change. The check holds under either
   branch of G7: before the ref accepts the candidate, or under containment on the exact pushed SHA,
   where a red result triggers G9.
4. **The oracle measures a side effect of the repair instead of the goal.** A repair that recreates
   state can make the original symptom disappear while the goal state is absent, and the check stays
   true. Remedy: **the success criterion must name the goal state, not the absence of the original
   symptom.** The symptom is the right measure only until the repair starts destroying state, and
   nothing announces that moment.

   A code migration is the standing case: a behavioural suite stays green whether or not the code
   migration happened, so it cannot tell a finished replacement from one that copies, wraps or still
   calls the old implementation. Receipt, at the candidate SHA: the search command with zero
   references to the old implementation from the migrated unit (a re-exporting shim lowers the
   count without moving a call), the unit's tests passing with that implementation disabled, and as
   a negative control one reintroduced legacy call that reds the audit while the suite stays green;
   otherwise the status is "code-migration unit incomplete". Schema and data migrations stay
   excluded by G3. Where that zero rests on a search, also take the references to the old
   implementation that an independent source reports (compiler, type checker, import graph) and the
   reference kinds it covers, kinds it does not cover staying unknown; otherwise the status is
   "zero references established by search only", and a reference the search missed leaves the unit
   incomplete. It does not replace the negative control.

Local checks do not compose into a cross-layer oracle. If correctness includes a boundary contract,
test that contract explicitly; otherwise that criterion has no oracle and the absence will not
announce itself.

**How to test an oracle:** disable the behaviour in production code and run. Exactly the tests
about that behaviour must go red, and no others. Without that negative control, green is not
evidence.

**On existing code, pin what it does today before an agent changes it.** Trigger: a candidate
changes production code on a path no test pins at the base SHA, or one with consumers outside the
repository; action: land characterization tests first, in a separate candidate that touches no
production code, written by a person or by a run other than the one that will make the change.
Receipt: the pinning commit is an ancestor of the candidate's base SHA, its tests pass on the
unchanged code, their negative control goes red, and its author differs from the candidate's;
otherwise the status is "behaviour not pinned", tests added in the same candidate count as G6
evidence and not as a G4 oracle, and a human lands the change.

## 3. Where the human boundary sits, and why it does not move

Inner loop (agent): explore, diagnose, implement, run checks, report.
Outer loop (human): decide whether the approach is right, verify the diagnosis, approve, own the
consequences.

**The boundary is evidence, not another prompt:** a diff, tests, logs, and a short explanation
tying them to the task condition.

Splitting maker and checker yields **claims, not proofs**. A sub-agent checker on the same model
with the same context returns correlated confidence, not independent verification. A real checker
needs a source of truth outside the artifact it judges: a contract, a browser, a device, a scanner,
a production invariant.

**Why architecture stays human structurally.** Tests answer in seconds; architectural erosion shows
up over weeks. A check can only hold a gate against failures that appear no slower than it
measures. So intent and architecture stay with the human, not "until the model matures".

**Comprehension debt** is the gap between how much code exists and how much anyone understands. A
dark factory does not pay it down; it accrues it as fast as it can, with the suite green throughout.
No pillar of the readiness model measures it.

## 4. Two outcomes from an audit, not one

1. **A repository level** on the existing model: a number, the minimum across pillars. Nothing new.
2. **A binary decision for one workflow**: may this class of change update trunk unattended, under
   what limits. This is a **landing and release gate**, not a maturity level.

The second is granted to a **class of task**, never to a repository. An L5 repository may stay fully
"lit" by policy; an L3 repository may earn autonomy for exactly one narrow class of routine change.

**The grant is renewed on outcomes, not on volume.** At the landing decision's review date three
counts for the class, keyed by landed SHA, decide renewal: oracle mismatches (a landing the oracle
passed that was later reverted, escaped as a defect or was judged wrong by sampling), suppressions
added inside landed changes, and human interventions needed to get a landing through; lead time and
review minutes are recorded beside them as the price of the grant and never renew it on their own.
Receipt: the three counts with the SHA of every nonzero item and, for each suppression, its cause,
owner and review date; otherwise, or on any unexplained mismatch or ownerless suppression, the
status is "grant unrenewed" and the class returns to human landing.

A grant has a named grantor: the landing decision records a named person, not a role, who granted
it and answers for landings under it until its review date, and each unattended landing's record
of where the human decision was taken resolves to it; otherwise the status is "grant unowned" and
the class returns to human landing.

A new model or runtime version, a routed subtask model, or a changed tool set or permission is a
harness change: the harness regression suite runs before it serves the class and passing grants
nothing. At review the counts are read per model and runtime version; counts earned under one
version are not evidence for another.

Designed autonomy is a ceiling, not a grant: how far a design lets the model plan its own steps sets
what a loop may attempt and earns nothing. A published capability ladder for agent architectures
gives mechanisms, not levels; its levels do not enter G2.

### Nine gates. L3 is necessary and not sufficient

The landing event is **the trunk update**, not the merge. Under review-gated flow that moment is a
merge; under trunk-based development it is the push, and the recovery move after it is a revert.
The gates are written for the landing event, so they hold under both.

| Gate | Passes when | Otherwise |
|---|---|---|
| G1 Scope | one routine bounded task with a checkable completion condition | split it or give it to a human |
| G2 Maturity | repository is at least L3 on the applicable pillars, scored on branching-model-neutral criteria | human landing required: the agent may prepare the candidate and its evidence, nothing more |
| G3 Risk | the path is not auth, billing, a schema or data migration, or a public contract | leave the lights on |
| G4 Oracle | the check is cheap, frequent and unfakeable at once | a human reads the diff, or build a stronger oracle |
| G5 Harness | restricted tools, isolated candidate state, isolated external resources, durable state, recorded base SHA | do not run unattended |
| G6 Evidence | diff, checks, logs and an explanation, all bound to a frozen base SHA and candidate SHA; if trunk moved, rerun on the new candidate | candidate evidence stale or incomplete: return to the inner loop, do not push |
| G7 Independent landing check | either **prevention** (a protected check with an external source of truth passes on the exact candidate SHA before the ref accepts it) or **containment** (protected CI checks the exact pushed SHA, only one uncertified push range exists at a time, and failure triggers G9) | the human becomes the checker before the push. A local pre-push hook alone does not pass: `--no-verify` removes it and it lives on one machine |
| G8 Exposure authority | the principal that lands on trunk cannot, by itself, deploy production or enable a flag | treat the landing as a release and do not do it unattended |
| G9 Outcome and recovery | the exact landed SHA is observed, and on failure the line stops, an ordinary revert restores the last green SHA, and the same checks rerun | post-landing containment not established: no unattended landing |

**On G1 for a code-migration class.** The completion condition names the goal state: the old
implementation is unreachable from the migrated unit and its dependency is removed, and a unit whose
old path is deleted in a later ticket is not complete and does not widen the class. Schema and data
migrations stay excluded by G3.

**On G4's fallback.** "A human reads the diff" holds only where the diff can show the break; on a
surface several owners assemble with uneven coverage, or one only production traffic exercises, the
fallback is a person exercising the surface as its users do, with what was exercised recorded for
each landing. Where no trustworthy suite pins such a surface, the old path can be the oracle: old
and new run on the same recorded inputs with the new responses served to no one, and this counts
under G4 only when the corpus, normalizer and accepted differences are frozen outside the
candidate's edit surface, replays are idempotent or isolated, an injected divergence goes red, and
every undeclared difference blocks promotion. A match proves equivalence on observed traffic only
and lifts neither G2 nor G3; receipt: corpus source, window and request count, comparator version
and ignore list, mismatch rows bound to the candidate SHA, and the request classes absent from the
window named as having no oracle.

**On G4's fallback, measured.** For a class landing on "a human reads the diff", list at the review
date its landings a person read and approved that were later reverted or escaped, and record for
each whether the diff showed the break, judged from the review-time record and the reproduced
failure, not from hindsight opinion. Receipt: the landed SHAs, the reproduction, each verdict and
who gave it; otherwise the status is "diff read unmeasured". Where the diff did not show the break,
the fallback on that path is a person exercising the surface.

**On G5 and untrusted input.** A per-agent working copy isolates changes, not behaviour: it can
share credentials and network access with the operator, which is acceptable only while the loop
reads content the team controls. A loop that reads content the team does not control (an external
issue body, a fetched page, a third-party package) passes G5 only in a sandbox that shares none of
those resources and holds credentials scoped to its one task. Receipt: from inside the sandbox, a
read of an operator credential, a call to a host-local service and a request to an unlisted
destination each fail. Content derived from uncontrolled content (a summary, memory entry, lesson or
retrieval index) keeps that status for later runs, judged by the source identifiers kept with it. A
loop that can add tools or widen its own permissions during a run does not have restricted tools.

**On G8.** For a class whose changes reach users and that asks for unattended landing, name the
production signal that shows it failing, its control band in monitoring, the watch window after each
exposure, and limits in minutes to detection and to restored state, and record both durations for a
failure fixture traced from base commit to production outcome, showing the line stopping and the
revert to the last green commit, and for each real breach of the band. Receipt: signal identifier,
band, window, limits, fixture run identifier and each real breach with both durations, keyed by
landed SHA; otherwise the status is "post-exposure containment unmeasured" and a named person
watches each exposure. A duration over its limit is read beside the three renewal counts at the
review date, and an unexplained one leaves the grant unrenewed. Who may expose is unchanged.

**The nine gates decide whether a candidate may land, not how it is made.** On an existing codebase
G3 and G4 are answered for each area of code, not once for each class of change. Where no check
pins what a path does today, the first class admitted there is characterization tests, and a class
that already lands unattended elsewhere covers that path only after those tests exist and the
path's owner has read a pre-agreed number of the agent's first landings there, each with a recorded
verdict, a refusal counting as a missing pin; where G3 fails, a person approves each step on the
record before the next starts, or the work does not happen. A rewrite is never the first class on a
path.

### Under trunk-based development the guarantee moves, it does not disappear

Direct pushes to trunk are a branching model, not a deficiency. What they remove is the pre-merge
review gate, and four things are usually named as paying for it: a green trunk, checks before the
push, a size ceiling, and shipping unfinished work dark behind a flag. Those four are necessary and
**not sufficient**, because none of them establishes who controls the checker. Add two:

- the checker and the recovery path sit outside the authority of the thing being checked (G7),
- uncertified trunk transitions are serialized, one at a time, and production exposure stays a
  separate authority (G8).

Each of the four is falsifiable, so each gets a receipt:

| Payment | Trigger | Receipt | Status without it |
|---|---|---|---|
| Green trunk | any update to the trunk ref, or a required result for its tip going failed, cancelled, timed out or absent | base SHA, pushed range, suite manifest, run ids, completion status of every required job, and on failure the revert SHA and the restored green SHA | trunk state unknown or trunk red: no new work, push or deploy starts |
| Pre-push checks | any attempted trunk update | observed base SHA, candidate SHA, hook version, commands, exit codes, tool versions | pre-push verification not established: no unattended push |
| Size ceiling | a candidate asks to land unattended | base and candidate SHA, the counting command and its exclusions, changed files, changed lines, the repository ceiling with the history window it was measured over, and the verdict | change-size eligibility not established; over the ceiling means human landing required |
| Dark shipping | the change carries incomplete behaviour | flag key, config source, per-environment defaults, off-path and on-path test results, a runtime read showing off, and who may flip it | dark shipping not established: it may not land unattended |

**The smallest control that actually binds** is not a hook on the developer's machine and not a
pull-request gate. It is a server-side check bound to the exact SHA: push the candidate to a
short-lived preflight ref, require a protected check on it, then fast-forward the same SHA onto
trunk. No pull request, no reviewer, no merge commit, no long-lived branch, so the model is intact,
and the ref still refuses a SHA the suite has not passed.

### What the eleven pillars do not ask

Three gaps worth naming when scoring, as additions to existing pillars rather than new ones:

1. Pillar 4, an L4 item: the share of code changed this quarter and never read by a human is
   measured (comprehension debt).
2. Pillar 3, an L4 item: checks run against the same artifact the consumer receives, accounting for
   truncation, serialization and transport.
3. Pillar 11, an L5 item: the review agent has a source of truth outside the artifact it judges.

## 5. Two ladders, and the size ceiling

| | Simplicity ladder | Maturity ladder (L1-L5) |
|---|---|---|
| Constrains | the **size** of a change | the **right** of a change to leave without a human |
| Applies | before writing code | when trying to land a candidate |

The link runs one way: **the lower the maturity, the stricter the simplicity ladder must be.** At
L1-L2 there is no proof of correctness, so smallness and reversibility are the only protection. At
L4-L5 a large change is acceptable because there is something to check it with.

**Set the ceiling from the repository's own p75 of changed files, not from a book.** Repositories of
one team differ by a factor of two or more, so a single number is wrong for most of them. The ceiling
is neither a target nor a prohibition: a larger change is allowed, it simply loses the right to land
without a human reading it.

**The ceiling is a dated measurement, not a constant.** Record the history window it was measured
over, and measure it again at the decision's review date and whenever the codebase or the number of
committers has grown: the largest change that can land atomically shrinks as both grow (Hyrum
Wright, "Large-Scale Changes", Software Engineering at Google, ch. 22), a direction observed at very
large scale rather than a number, so the number still comes from the repository. An unattended code
migration over the ceiling lands as shards, each under the ceiling, each passing the gates on its
own SHA and reverting on its own.

## 6. Audit checklist, in terms of the existing pillars

Answer each by looking at the repository, not by opinion.

**Pillar 1, Style & Validation**
- [ ] A deterministic correctness validator exists per main language. A documented N/A is fine.
- [ ] It runs automatically and fails on violations.
- [ ] It runs on **every path into the protected branch**. A workflow on a branch anyone can push to
      is a detector, not a gate.

**Pillar 3, Testing**
- [ ] The suite executes fully, with no tests silently skipped by a missing plugin.
- [ ] The declared suite runs against the exact candidate or landed SHA on every path into trunk,
      and failure either refuses the ref or triggers a protected stop-line and restores the last
      green SHA. A notification-only workflow does not count.
- [ ] Checks run against the artifact the consumer receives, not the full internal one.
- [ ] Critical modules have a negative control: disabling the behaviour reds exactly its own tests.
- [ ] Known failures are strict `xfail` with cause, owner and a review date, never a bare skip.

**Pillar 4, Documentation & Agent Context**
- [ ] Project context lives in the repository; the agent does not re-derive it each run.
- [ ] A rule learned from a defect is written where the next run will read it.
- [ ] A value crossing layers uses one canonical term, with only mechanical variants or classified,
      tested boundary mappings. The vocabulary receipt below is present.

**Pillar 7, Security & Governance**
- [ ] Autonomy is tied to reversibility and blast radius by a deterministic rule, not by discretion.
- [ ] Paths with irreversible cost (money, auth, migrations, public contract) are excluded explicitly.
- [ ] A kill switch exists and fails closed.

**Pillar 11, Multi-Agent Coordination**
- [ ] Parallel workers are isolated by external resources, not only by files.
- [ ] The checker has a source of truth outside the artifact it checks.

### Cross-layer vocabulary gate

The unit is **one semantic contract, one canonical term**, not one identifier repeated verbatim
everywhere. This is a Pillar 4 guard and it produces G6 evidence, not G4 autonomy: an agent-authored
inventory can omit a repository or an alias, so it earns a human reading unless a protected schema,
vocabulary manifest, or contract test validates it from outside.

Four shapes one semantic value takes across layers, none visible to a check confined to a single
layer:

- **Two terms on one surface**: the field that starts work and the endpoint that lists its permitted
  values use different names for the same thing.
- **A value mapping mistaken for a name mapping**: helpers resolve the *values* and their aliases,
  and are read as though they reconciled the field *name*.
- **A name that narrows its own value**: a field that may hold any vendor's model, named after one
  vendor.
- **A term that stops**: the column exists and the receiving schema has no such field, so the value
  disappears before an intended consumer. That is a defect, not an absence.

**Trigger.** A change introduces, renames, or adds another representation of an identifier for the
same semantic value in two or more active layers or repositories.

**Action.** Name the semantic value, its canonical term, its sources and its terminal consumers, and
derive the in-scope repositories from the task requirements and the actual deployment, route, import
or call edges. Cite the evidence for each repository included and for each plausible one excluded as
off-path. A repository manifest is optional.

Trace the candidate through every boundary on those paths: request schemas, serializers, dispatch
payloads, adapters, domain models, repository calls, database models and migrations, response
schemas, and the runtime or display consumers this task touches. Record the identifier at each
boundary and classify it as canonical, mechanical, allowed exception, missing, or defect. A value
that disappears before an intended consumer is a defect, not an absence.

Search each observed identifier and only the casing, separator, singular or plural, and role-modifier
forms that are observed or mechanically derived under a cited rule. `git grep -nE "\bname\b"` returns
nothing in current Git: use `git grep -n -w -F 'name' <sha> -- '*.py'`. While the candidate is
uncommitted add `--untracked`, record `HEAD` plus `git status --short`, and mark the receipt
provisional; repeat at the candidate SHA before unattended merge. Do not invent synonyms from
neighbouring nouns: an agent cannot prove it searched for a name it never saw.

Syntax, cardinality and role modifiers may vary without changing the canonical term: `llm_model`,
`llmModel`, `LlmModel`, `default_llm_model`, `supported_llm_models`. Cite the language rule or
serializer configuration that makes the transformation mechanical.

A different semantic term is allowed only at an immutable external contract, a compatibility surface,
a localized display boundary, or a distinct bounded context. Put the mapping in the narrowest
explicit boundary component (serializer, compatibility adapter, presenter) and test both names there.
For a bounded-context exception, state the different meaning or invariant; local preference does not
qualify. Do not edit historical migrations, and call a historical name inactive only when a later
migration or the current schema proves it off the active path. An assignment or a helper is not an
exception by itself, and neither is a name that narrows the value: a field that may hold any vendor's
model is not named after one vendor.

**Receipt.** The semantic value and its canonical term; sources and terminal consumers; each in-scope
repository with its scope evidence and candidate SHA; each plausible off-path repository with its
exclusion evidence; the exact search commands; and one row per boundary:
`direction | boundary | identifier or missing | classification | file:line | mapping or test`.
Account for every intended boundary. A provisional `HEAD` plus diff receipt cannot authorize an
unattended merge.

**Otherwise.** Status is "vocabulary not reconciled". Do not report the inventory complete and do
not merge unattended.

Local style rules apply only after this gate and do not license a semantic rename at a boundary.

## 7. Apply it to your own session, not only to repositories

A session in which an agent edits someone else's code IS a factory. Loop = one turn; harness =
permissions, tools, memory files, session status; factory = **many concurrent sessions in one
working tree**; evidence boundary = run output bound to a SHA.

**The oracle for your own work is not a test.** It answers "did I run the check I was obliged to
run". The failures here are skipped steps, not bad formatting: did not run it, did not compare, did
not establish ownership, did not save the source.

Layers a factory-of-sessions usually lacks:

1. **Isolation.** Sessions share a working tree and a git identity, so one session's commit can
   sweep up files another has just written.
2. **Awareness of neighbours.** A session listing exists and goes unread.
3. **Binding a measurement to a state.** Results reported without a SHA go stale silently when the
   tree moves underneath the run.
4. **Independence of the checker.** An external reviewer whose answer may belong to someone else's
   question is not a checker.

Rules that follow:

- Before the first write to a shared tree: list active sessions and publish your own **with the
  paths you intend to touch**.
- Every measurement carries a SHA and is rechecked afterwards; if it moved, the result is void.
- Accept an external checker's answer only if it contains specifics from the question you asked. A
  reasonable-sounding text on an adjacent topic is not evidence of relevance.
- Authorship is always established, never described as "someone". That is one `git log -S`.

### The oracle for a sentence: type the evidence, not just the result

Most false closing statements are one mistake, an evidence type silently widening into a claim of
another type:

| What was observed | What it was turned into |
|---|---|
| A note about a former version | The behaviour of the current one |
| A command that failed to execute | A negative answer about the subject |
| A check that was started | A check that had finished |
| One route unreachable | The whole machine unreachable |
| A log event at time T | The state right now |
| A comment string in a key file | The identity of the key's owner |
| Four ports probed | The whole port space |
| TLS working for the watchdog's own child | The applications running |

A mental procedure does not catch this. There is no `about_to_make_a_claim` event, the checker and
the claimant are the same process, and finishing a turn is free while "unknown" costs another tool
call, so every error lands on the same side: the question looks closed. A check compiled into the
runtime, a hook that reads the finished text and rejects the turn, does fire.

Two practices that survive without runtime support:

- **State the type with the result.** Not "there is no internet", but "one ping, one device, one
  address, and the command itself failed to run". The widening becomes visible while writing.
- **A caveat is not a status.** "Confirmed, the check is still finishing in the background" is the
  same defect as claiming it outright: the reader has already acted. If the discriminating check
  has not returned, the only permitted status is unknown.
