---
name: earned-length
description: Cut text that carries no information. Trim, tighten, shorten, remove filler, hedging, repetition and self-narration in code comments and authored prose alike. Use before writing or keeping a comment or docstring and before finalizing a response or report. Never use it to drop disclosure of failures, evidence, licences or warnings.
---

# Length is earned

Default to omitting. Text earns its place by carrying information a reader cannot get from the
code, the types, the structure, the tests, or the sentence before it.

## The test

Delete the sentence, comment or paragraph. If nothing a reader would do or decide changes, it was
junk. This is the only test; everything below is it applied to a recurring case.

## 1. Code comments

Default to adding none. Prefer self-explanatory code.

Add or keep a comment only when it preserves non-obvious, durable information that names, types,
structure, assertions or tests cannot carry:

- an external constraint or platform workaround;
- a security or concurrency invariant;
- a wire-format, API or persistence contract;
- why an obvious alternative would be unsafe.

Never write a comment that:

- paraphrases the code, the types, the tests or the configuration;
- labels an obvious section;
- narrates the current edit or the implementation history;
- names a previous value or implementation, such as changed from 22 to 24;
- refers to a task, a conversation, a diff, a finished migration or a temporary process;
- explains what the code already makes clear.

A comment must still be useful to a maintainer who reads only the current code in six months. Every
candidate comment starts at minus one hundred points and has to earn its way up. No docstrings on
self-explanatory APIs. When a comment is necessary, one or two sentences.

Receipt: before completing a change, read every comment added in it and delete each one that does
not satisfy the list above. Otherwise the change is not finished.

Preserve licences, generated-file markers, required directives and existing warnings that carry real
information.

## 2. Responses and reports

State the outcome, the files changed, and the verification. Nothing else unless it was asked for.

Do not narrate the history of the implementation. Do not recap work already visible. Do not restate
the request. Do not add alternatives, next steps or caveats that were not requested.

Receipt: every block of the response maps to something in the request, or to a required disclosure
under section 4. Otherwise cut the block.

## 3. The junk that arrives anyway

These pass a naive read because each sentence looks reasonable on its own. They are recognised by
position and repetition, not by wording.

| Pattern | What it looks like | Fix |
|---|---|---|
| Defensive hedging | a sentence whose job is to pre-empt a hypothetical misreading | one caveat, in one place |
| Repeated caveat | the same qualification in four sections | keep the strongest instance, delete the rest |
| Methodological footnote | how the number was derived, inside the artifact that reports it | the artifact carries the number; the method goes to the working file |
| Triple restatement | the numbers, then the conclusion, then the conclusion again in other words | numbers plus one line |
| Self-positioning | an opener that presents the author's sincerity, directness or diligence | delete the opener |
| Rhetorical flourish | a phrase that adds emphasis and no fact | delete |
| Rule-form padding | trigger, action, receipt and otherwise applied to a rule that needs one line | one line |

## 4. What brevity never buys

Length discipline applies to text that carries no information. It never removes:

- that something failed, was skipped, or is incomplete, with the evidence;
- a receipt that a closing claim depends on;
- a security, data-loss or correctness warning;
- a licence, a generated-file marker or a required directive.

If cutting makes an artifact shorter and less true, the cut was wrong. Say the bad news in one
sentence rather than removing it.

## 5. Controlled style for text a person acts on

Section 1 removes words. This section shapes the words that stay. It applies to text a person reads
to decide or to act: a report, a handover, a comprehension memo, the summary of a change. It takes a
checkable subset of ASD-STE100, a controlled language first written for aircraft maintenance
manuals, not the whole standard.

- An instruction: one action, in the imperative, with any condition first, in at most 20 words
  (rules 5.1 to 5.4).
- A description: at most 25 words, in the active voice. Use the passive only when the actor is
  unknown (rules 6.3, 3.6).
- A paragraph: one topic and at most six sentences. A longer sequence becomes a vertical list
  (rules 6.5, 6.6, 4.3).
- A term: one name for one thing, unchanged through the text (rules 1.11, 9.4). A term that crosses
  layers takes its canonical name from the vocabulary gate in `01-method.md` section 8.

Not taken: the approved-word dictionary and the limits on verb forms. Its maintainers say the
standard is not meant for general-purpose writing. Identifiers, error strings and quoted output keep
their exact form.

Receipt: a counter lists every sentence and paragraph over its limit, and each listed item is split
or kept with a stated reason. Passive voice and term drift are checked by reading, because a pattern
match misses both ways. Otherwise the text is not finished.

Do not call the result STE or STE-compliant. ASD-STE100 is a registered trademark, and its
maintenance group warns that model-written text can look compliant without being compliant. The
kit borrows the limits, not the claim.
