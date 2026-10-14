---
name: grilling
description: Grill the user relentlessly about a plan, decision or idea, a round of questions at a time, to stress-test their thinking. Use on any 'grill' trigger phrase such as grill me, grill this, stress-test this plan, tear this plan apart, interview me on this.
---

Interview the user relentlessly until you reach a shared understanding. Map this as a **design tree**: every decision branches into the decisions that hang off it.

Work the tree in **rounds**. The **frontier** is every decision whose prerequisites are already settled: the questions you can ask _now_ without guessing at answers you haven't heard yet. Ask the whole frontier in one round: number each question and give your recommended answer. Then wait for the user's answers before the next round.

Format a round like so:

```
❓ **Q1** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>

---

❓ **Q2** - **<question title>**: <question body, might be multiple paragraphs, including multiple choices>

➡️ <your recommended answer>
```

Word each question so "yes" accepts your recommended answer.

Each round the user answers reshapes the tree: settled decisions push the frontier outward and unblock questions that depended on them. Recompute the frontier and ask the next round. A question whose answer depends on another question still open in this round belongs to a _later_ round, not this one.

Finding _facts_ is your job, never the user's. When a frontier question needs a fact from the environment (filesystem, tools, etc.), dispatch a sub-agent to find it; don't ask the user for anything you could look up yourself. Don't block on it: a running exploration is an unsettled prerequisite, so only the questions downstream of it wait for the sub-agent to report; ask the rest of the frontier now. The _decisions_ are the user's: put each to them and wait.

The session is done when the frontier is empty: every branch of the design tree visited, nothing left silently assumed. Do not act on it until the user confirms you have reached a shared understanding.

Use a professional, technical register. No slang, no filler, no hedging. Frame each question
precisely and give the recommendation with its concrete reason: a constraint, a trade-off, prior art
in the environment, or a principle. If there is no basis for a recommendation, say so and name what
would have to be read or checked to form one, then go and check it rather than handing the decision
back without a signal.

## Attribution

The body above is the `grilling` rule set from `mattpocock/skills` by Matt Pocock, MIT licence,
commit 49dd158 on `main` (2026-10-09, after release 1.3.1),
read on 2026-10-10. The register paragraph is this kit's.
