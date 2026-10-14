---
name: autoresearch
description: Run and manage autonomous LLM training experiments in a checkout of karpathy/autoresearch, with baseline measurement, iterative train.py edits, val_bpb comparison and results.tsv logging on a dedicated branch. Use when asked to set up, start, continue, inspect or summarize an autoresearch run.
---

# Autoresearch

Follow the research loop from `program.md` in `karpathy/autoresearch`, adapted for safe use as a Claude and Codex skill. The upstream repository publishes no licence: study the code, do not vendor or redistribute it inside a deliverable, and leave the decision to run it locally to the user.

## Confirm the target

Before probing, editing, or training:

1. Resolve the repository root with Git.
2. Verify the checkout contains `README.md`, `program.md`, `prepare.py`, `train.py`, and `pyproject.toml`.
3. Verify the Git remote identifies `karpathy/autoresearch` or a fork the user explicitly selected. Do not treat matching filenames alone as proof.
4. Read `README.md`, `program.md`, `prepare.py`, and `train.py` completely.
5. Inspect `git status` and preserve all pre-existing changes. Stop and report exact paths if user changes overlap files needed by the run.
6. Verify `uv`, Python 3.10 or newer, an NVIDIA GPU, and working CUDA access. The upstream project requires a single NVIDIA GPU. Do not silently fall back to CPU, Apple silicon, or an unrelated accelerator.

Use a platform-specific fork only when the user asks for it. Re-run the target checks against that fork instead of assuming upstream behavior.

## Set up a run

1. Propose a short date-based run tag such as `jul31`.
2. Verify that `autoresearch/<tag>` does not already exist locally or remotely.
3. Identify and update the intended base branch without discarding local work. Upstream currently uses `master`.
4. Create `autoresearch/<tag>` from the verified base commit.
5. Resolve the user cache directory and verify the `autoresearch` cache contains data shards and a tokenizer. The upstream default is `~/.cache/autoresearch/`. If artifacts are absent, tell the user to run `uv run prepare.py` and do not pretend setup succeeded.
6. If `results.tsv` is absent, create it with only this tab-separated header:

```text
commit	val_bpb	memory_gb	status	description
```

If it already exists, validate the header and existing rows. Never overwrite prior results.

7. Keep `results.tsv` and `run.log` untracked. Stage only `train.py`, never use broad commands such as `git add .`.
8. Summarize the verified setup and ask once for confirmation before consuming GPU time. Starting an autonomous loop requires an explicit user request. After confirmation, continue without routine check-ins until the user interrupts or a user-defined budget or target is reached.

## Protect experiment integrity

Treat these constraints as fixed:

- Modify only `train.py`.
- Do not modify `prepare.py`, the tokenizer, data loading, fixed training constants, or `evaluate_bpb`.
- Do not install packages or add dependencies. Use only `pyproject.toml`.
- Optimize for the lowest validation bits per byte, `val_bpb`. Lower is better.
- Treat video random access memory, VRAM, as a soft constraint. Reject dramatic memory growth unless the gain clearly justifies it.
- Prefer simpler code when results are equal. Keep a tiny gain only when its complexity cost is reasonable.
- Run the unchanged training code first to establish the baseline when no baseline row exists.

Before merging any experimental idea into the accepted state, state what the experiment tests and which material conditions it does not cover.

## Run one experiment

Repeat this process for each experiment:

1. Record the current accepted commit and the best valid `val_bpb`.
2. Form one testable hypothesis. Prefer a focused change whose result can be interpreted.
3. Edit only `train.py` and inspect the exact diff.
4. Run lightweight static checks that do not alter the experiment or add dependencies.
5. Commit only `train.py` with a concise description of the hypothesis.
6. Run training with output redirected away from the context:

```bash
uv run train.py > run.log 2>&1
```

Use the execution tool's timeout support where available. Expect about 5 minutes of training plus startup and evaluation. If total wall time exceeds 10 minutes, terminate the run and record a crash.

7. Extract only the summary fields first:

```bash
grep -E '^(val_bpb|peak_vram_mb):' run.log
```

If the summary is missing, inspect the final 50 lines of `run.log`. Fix an obvious implementation error and retry a few times. Abandon a fundamentally broken idea.

8. Append one tab-separated row to `results.tsv`:

```text
commit	val_bpb	memory_gb	status	description
a1b2c3d	0.997900	44.0	keep	baseline
b2c3d4e	0.993200	44.2	keep	increase LR to 0.04
c3d4e5f	1.005000	44.0	discard	switch to GeLU activation
d4e5f6g	0.000000	0.0	crash	double model width (OOM)
```

Use the 7-character experiment commit, six decimal places for `val_bpb`, and one decimal place for memory in GB calculated as `peak_vram_mb / 1024`. Use `0.000000` and `0.0` for crashes. Valid statuses are `keep`, `discard`, and `crash`.

9. Keep a valid experiment when it improves `val_bpb`, or when it is effectively equal and materially simplifies the code.
10. Discard a failed experiment without risking unrelated work. The safe default is to revert only the experiment commit and continue from the restored accepted code. Use branch rewinds or hard resets only when the user explicitly authorized canonical history rewriting for this dedicated branch, the target commit was recorded at the start of the same iteration, and a recovery reference exists.

## Continue autonomously

Once the user starts the loop, do not pause after each result to ask whether to continue. Generate new hypotheses from the code, prior results, referenced papers, near misses, and combinations of successful ideas. Continue until one of these conditions occurs:

- The user interrupts.
- A user-defined time, cost, experiment-count, or quality target is reached.
- The verified GPU or data becomes unavailable.
- A repeated failure prevents reliable evaluation and no safe in-scope recovery remains.

Do not change permission settings, expand scope, modify additional files, or bypass a failed precondition merely to keep the loop running.

## Report the run

When interrupted or finished, report:

- Baseline and best `val_bpb`.
- Absolute and percentage improvement.
- Best commit and branch.
- Experiment counts by `keep`, `discard`, and `crash`.
- Peak VRAM for the best run.
- The main successful ideas and notable failures.
- Exact current Git state and any untracked logs or result files.
- Conditions tested and material production configurations not covered.
