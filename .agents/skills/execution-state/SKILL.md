---
name: execution-state
description: Keep a long agent run's prompt bounded by carrying a structured execution state instead of an accumulating transcript. Use when a run spans many steps, context fills or compacts mid-task, the agent repeats a failed command or acts on a contradicted fact, or when truncation, summarization or prompt compression is proposed as the fix. Not for runs where the history is the deliverable.
---

# Execution state, not conversation history

One rule set, one artifact: a structured execution state that the runtime owns, and a prompt that
never grows with the number of steps already taken.

Source: **SKILL.state: Scalable Long-Horizon Agent Skills**, Sanket Badhe, Priyanka Tiwari and
Jonghyun Chung, arXiv:2608.26263, CC BY 4.0. Every number here is the paper's. Section 7 is what it
does not cover.

## 1. The claim

At step `t` the model receives exactly three things: `P` the immutable procedural specification,
`S_t` the structured execution state, `O_t` the latest observation. No previous observation, no
previous action, no previous reasoning trace. It returns reasoning, a state patch and one action. The
runtime validates the patch and merges it; **the reasoning is then discarded and never appears in a
later prompt.**

Prompt footprint becomes O(1) in the number of steps, cumulative tokens O(T) instead of the O(T^2)
any append-only transcript produces.

A structured state block added *alongside* a rolling transcript is the LangGraph-style baseline in
the source, and it still paid the quadratic bill. The discard is the mechanism.

## 2. The measurements that decide adoption

Warehouse domain, 500 shelves, Gemini-3-Flash, temperature 0.0, top_p 1.0, five seeds, means.

| Horizon | Runtime | Score | Avg prompt | Total tokens |
|---|---|---|---|---|
| 50 | ReAct (append all) | 0.88 | 11,931 | 171,658 |
| 50 | Memory (rolling 3 plus summary) | 0.93 | 7,582 | 131,455 |
| 50 | Stateful (state plus full transcript) | 0.94 | 11,594 | 170,992 |
| 50 | Execution state | 0.96 | 1,773 | 30,151 |
| 200 | ReAct | 0.74 | 48,007 | 2,608,755 |
| 200 | Memory | 0.84 | 84,364 | 6,175,509 |
| 200 | Stateful | 0.88 | 72,305 | 5,041,164 |
| 200 | Execution state | 0.94 | 1,811 | 122,384 |

The paper defines the prompt column for this table as the mean string length in characters per
model call; its public-benchmark table reports prompt tokens instead. Compare within a table, not
across the two.

**Compression is not the mechanism.** Same budget, Warehouse T=100:

| Configuration | Avg prompt | Score |
|---|---|---|
| Sliding-window truncation | 1,800 | 0.18 |
| Summary with a hard token ceiling | 1,840 | 0.52 |
| ReAct plus LLMLingua perplexity compression | 1,810 | 0.22 |
| Structured execution state | 1,905 | 0.94 |
| Full unbounded ReAct, for reference | 36,362 | 0.84 |

Truncation evicted early inventory allocations; statistical compression removed slot identifiers that
looked redundant and were semantically vital. A proposal to summarize the history has to beat 0.52
before it counts as the fix.

**Cheaper is not smaller per step.** On tau-Bench Retail the winner had the largest average prompt of
the four, 3,325 tokens, the highest pass rate, 58.3%, and the lowest total tokens, 3.47M. Optimize the
cumulative curve.

Public benchmarks, same model. InterCode CTF pass@1 54.2% for execution state against 46.4% for the
summary-memory baseline, 43.2% for ReAct and 41.8% for the stateful runtime, with total tokens 387k
against 1.03M, 977k and 1.13M respectively. tau-Bench Airline 32.4% against 28.1% for the stateful
baseline and 21.8% for ReAct, with per-step prompts flat near 2,800 against baseline peaks above
11,000.

## 3. The rules

Trigger, action, receipt, and the status when the receipt is missing.

**Rule 1. Schema once per domain, not once per task.**
Trigger: a run starts and the state has no declared shape. Action: author a named, fixed schema for
the domain and reuse it across every task in that domain. The source reused one five-field schema
(`discovered_flags`, `tested_hypotheses`, `active_files`, `working_dir`, `cmd_summary`) across all 100
InterCode CTF instances. Receipt: the schema is a file, the run references it, and its field list did
not change between two tasks in the same domain. Otherwise: no domain-level reuse, and if no fixed
schema can be known in advance this is limitation 1.

**Rule 2. The state holds only what a future step needs.**
Trigger: a field is being added. Action: name what will read it. Receipt: a named future decision,
action, invariant or completion condition that may read the field. Otherwise: the field is history,
and history goes to the audit log, not the prompt.

**Rule 3. Patches merge into the state; they do not replace the whole state.**
Trigger: the model returns a state update. Action: recursive dictionary merge with null-deletion, so
`{"inventory": {"shelf_42": null}}` removes one key and leaves the other 499. Receipt: a test where a
patch touching one key leaves every sibling present. Otherwise: expect the 68% failure in section 5.

**Rule 4. The runtime owns the schema and the validation, never the model.**
Trigger: a patch arrives. Action: validate against the schema in deterministic code, merge, validate
the merged state, check the domain invariants; on failure roll back and retry under a bounded count.
Receipt: an injected malformed patch leaves the persisted state byte-identical and produces a retry.
Otherwise: a bad generation corrupts the only surviving record of the run.

**Rule 5. Reasoning leaves the prompt; the audit log keeps everything else.**
Trigger: a validated patch has been applied. Action: exclude the reasoning from every later prompt,
and append one log row: observation, patch, validation result, action, state hash before and after. Do
not require or retain hidden model reasoning. Receipt: the next prompt has no previous reasoning and
the log gained a complete row. Otherwise: the run is not auditable and rule 5 is unmet.

**Rule 6. Distractors enter once, because only committed facts survive.**
Trigger: an observation carries background telemetry or unrelated chatter. Action: let it reach one
step; anything not committed to the state is gone at the next step by construction. Receipt: a noise
test reports the score change against its control, inside an agreed tolerance. Measured at T=50: plain
ReAct fell 0.68 to 0.53 from 5 to 50 injected events per turn; execution state stayed between 1.00 and
0.97, and so did the other two structured baselines. Otherwise: irrelevant text competes for attention
at every later step.

**Rule 7. External drift is absorbed on the next observation.**
Trigger: the world changed outside the agent's action loop. Action: apply the corrective observation
to the state directly. Receipt: steps between the corrective observation and correct behaviour.
Measured: 0 for execution state, 5 to 8 turns of hallucination for every history-based runtime, whose
obsolete prompt facts outvoted the new observation. One scenario failed under all four runtimes, so
this buys recovery speed, not immunity.

## 4. Where it does not hold

Pure state-only prompting is insufficient in each of these. Use a hybrid or keep the history.

1. **No schema known in advance**, structure has to be discovered while running.
2. **Retroactive relevance**: the correct update depends on an earlier observation whose significance
   was invisible when it arrived, so it was never committed.
3. **The trajectory is the deliverable**: auditing, provenance, explaining past actions.
4. **Multi-agent concurrent writes**: the single-agent merge operator has no conflict resolution.
5. **Short runs.** On the relational Software Repository domain execution state scored 0.88 at horizon
   25, below Memory at 0.89 and Stateful at 0.94, then led from horizon 50 (0.86 against 0.74) and at
   100 (0.78 against 0.63). On Warehouse three of four runtimes scored 1.00 at horizon 10. The
   evidence lives at long horizons.

## 5. Small-model failures are structured-output failures

Gemma-4-31B-it at horizon 100 scored 0.42:

| Failure mode | Share |
|---|---|
| Premature state overwrite or deletion, omitting existing keys instead of merging in place | 68% |
| Schema comprehension and type coercion, nested lists against dictionaries | 20% |
| JSON syntax slips, malformed delimiters or trailing commas | 12% |

Rules 3 and 4 stop invalid output from corrupting the state, and grammar-constrained decoding removes
the syntax and shape errors. Neither establishes semantic correctness: a patch can be schema-valid and
delete the wrong key, so the domain invariants stay required at every model size. The same model beat
every history-based baseline at horizons 10 and 25, so this is a runtime problem, not a model verdict.

## 6. What this changes in the method

**G4 Oracle: the validator is not one.** A deterministic schema validator is cheap, frequent and
unfakeable at once, which is the G4 wording, and it decides only that the state is well formed. Score
it as instrumentation and keep the task oracle separate, or it becomes the decoration failure from
`07-human-boundary.md`.

**G5 Harness: this is what durable state means.** A schema-validated state file with atomic writes
satisfies G5's durable-state requirement; a scratchpad the model rewrites in place does not.

**G6 Evidence: bounded prompt, complete log.** Dropping reasoning from the prompt is the mechanism.
Dropping it from disk instead hits limitation 3 and leaves G6 unmet. Rule 5 keeps the two apart.

**Set the budget from your own run.** The 1,800-token footprint is a property of the Warehouse setup.
Take the number from the run's own distribution the way `agentic-factory` takes the change-size
ceiling, and report p50, p75, p95, maximum and the prompt-token slope by step before naming a ceiling.

**Level.** `simplicity-ladder` governs one change, `cherny-workflow` one session, `agentic-factory`
the stream. This governs one long-horizon run inside a session, tens to hundreds of steps.

**Rehearse it.** Under `08-measured-loop.md`, log prompt tokens per step and cumulative tokens across
at least two horizons. Per-step size should stay bounded while cumulative tokens grow roughly
linearly; cumulative growth is the expected shape, not the failure. If per-step size grows, inspect
prompt composition first: a growing state or observation gives the same curve as leaked reasoning.

## 7. What is not measured

The source evaluated Gemini-3-Flash, Gemma-4-31B-it and Qwen-3-8B-it on a purpose-built runtime. It
did not evaluate the models or the CLIs in `agents/`, and its differences are significant from horizon
50 (paired t-test, p < 0.01). The mechanism and the failure taxonomy are the transferable candidates,
to be tested locally. The numbers above are the source's and are not ours until a rehearsal says so.

## 8. Doing this with the CLI routes

Runtime-specific material, isolated here as it is in `INSTALL.md` and `agents/`.

No CLI route replaces the conversational substrate of the main session. What you control is the state
file, which inputs each child receives, and who validates the patch.

| Route | What its contract gives you | What it does not give you |
|---|---|---|
| `codex-thinking` | `--ephemeral` prevents child-session persistence, `-s read-only` stops the child writing the state file, `--ignore-user-config` isolates user MCP servers and plugins | any schema on the returned text |
| `gemini-thinking` | `agy -p` runs once in print mode with no resume identifier passed, allowlist exactly `read_file(*)` | whether conversations persist server-side, or that each `conversation_id` is fresh |
| a host-runtime subagent | its transcript does not enter the parent context, only the return value | that the child made exactly one model call |

Read-only stops the child mutating the state file. It does not move schema ownership into
deterministic code; only section 9 does that.

**Build the payload from `P`, `S_t` and `O_t` alone.** Both children keep file-reading tools and can
gather further observations inside one invocation, so treat extra tool observations as a nested sub-run
rather than one paper step.

**Do not pass transcript history to a stateless child.** Both wrappers take the prompt as one blob,
which makes pasting the session transcript trivial and restores the quadratic bill under the
appearance of state discipline. The Gemini route refuses to run above half of `ARG_MAX`; read that
guard as a budget signal, because a step prompt near it means the state is not a state.

**Extend the adapters before measuring.** Neither enforces a `state_patch` and `action` object. Token
counts for each child run are in the second-opinion usage ledger described in `monitoring/README.md`,
reported for the Codex route and partial for the Gemini route. Add the parser from section 9 and read
the counts from the ledger.

**Model routing is untested here.** Patch generation looks like format adherence and relational step
reasoning does not, which suggests `flash` for the first and the `max` effort route for the second.
Benchmark both roles before either becomes a default.

## 9. The deterministic part you have to build

1. **Extract** the JSON object from the child's output; fail the step rather than guess.
2. **Validate** the patch, **merge** recursively with null-deletion, **validate** the merged state,
   then check the domain invariants.
3. **Persist atomically**: new state and one audit row together, with the state hash before and after.
4. **Retry** an invalid patch a bounded number of times against the unchanged state, then stop with a
   terminal status. Never retry against a partially applied merge.
5. **Account**: prompt, output and total tokens per step, so the curve in section 6 exists.

Three files: `schema.json` the fixed domain schema, `state.json` the current state, `events.jsonl` one
append-only row per step with `run_id`, schema version, step number, observation, patch, validation
result, action, state hash before and after, and usage.

One step, in the shape the source uses:

```
Observation:  Customer ordered item_12.
Prompt sent:  P, state.json, that one observation. Nothing else.
Returned:     {"state_patch": {"inventory": {"shelf_42": null}},
               "action": "Ship item_12 shelf_42"}
Runtime:      validate patch, merge (shelf_42 removed, 499 keys untouched),
              validate merged state, write state.json and one events.jsonl row,
              execute the action, discard the reasoning.
Next prompt:  P, the new state.json, "Success: Shipped item_12 from shelf_42."
              The previous observation, patch and reasoning are absent.
```

A patch of `{"inventory": null}` is schema-shaped and wipes the domain. Rule 4 catches it only if an
invariant says that key may not be deleted wholesale. Write the invariants down with the schema.
