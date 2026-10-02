# Discussions Log

## 2026-09-30 — Environment setup and baseline verification
**Prompt:** User asked to check `AGENTS.md` and follow it; then confirmed ("yes") to
both creating the `latexdiff-better` mamba environment and fixing the failing
integration tests, and creating the missing project `.md` files.
**Actions:**
- Created `environment.yml` (conda-forge only, pinned versions) and the
  `latexdiff-better` mamba environment: python=3.11.16, pytest=9.1.1, loguru=0.7.3,
  tqdm=4.70.1, codespell=2.4.3, ruff=0.16.9, pylint=4.0.10, flake8=7.4.1,
  complexipy=8.0.1, mypy=2.3.1.
- Ran baseline `pytest`: initially 73 passed / 2 failed — both integration tests
  failing because the system TeX Live install was missing `ulem.sty`
  (`\sout{}`/`\normalem` undefined).
- Installed `ulem.sty` into the user's local TeX tree (`~/texmf/tex/latex/ulem/`,
  downloaded from CTAN, refreshed with `mktexlsr`) since passwordless `sudo` was not
  available to fix it via apt. Re-ran tests: 75 passed, 1 skipped, 0 failed.
- Created `DOCUMENTATION.md` (environment setup, TeX Live fix, code structure
  overview) and updated `README.md` to reference `environment.yml`.
**Outcome:** Environment and baseline test suite are green. Ready to start the actual
investigation goal (checking `latexdiff_better.py --git` against the `v0.2`/`v1.0`
tags of the sibling `esa-rl2ocean-production-model` repo) in a future session.

## 2026-09-30 — v0.2/v1.0 investigation, --old-main flag, brace-tokenizer bug fix
**Prompt:** User said "go ahead" to proceed with the AGENTS.md investigation goal:
check whether `latexdiff_better.py` can diff v0.2/v1.0 of the sibling
esa-rl2ocean-production-model repo, and whether tags vs. hashes need code changes.
**Actions:**
- Verified tags resolve identically to raw hashes via `git show <ref>:<path>` — the
  "hash codes only" suspicion was disproven.
- Found the real blocker: main file renamed `production_model.tex` → `main.tex`
  between tags. Added a new `--old-main <path>` flag to `--git` mode, with the
  parsing logic extracted into `_parse_git_mode_args` (also reduced `main()`'s
  complexipy score from 35 to 34 in the process).
- Ran the generated diff through `pdflatex`/`bibtex`; found and fixed a real bug:
  `diff_cells_inline` used a brace-unaware tokenizer, producing unbalanced braces
  (fatal pdflatex error) when a table-header word was replaced by a LaTeX command.
  Fixed by reusing the existing brace-aware `_latex_tokenize`.
- Added 5 new tests (`TestBug7CellInlineBraceAwareTokenizer`, `TestOldMainFlag` ×2,
  `TestIntegrationRl2oceanOldMainRename`) — 80 passed, 1 skipped, 0 failed.
- Verified the full v0.2→v1.0 diff now compiles cleanly to a PDF end-to-end.
- Updated `DOCUMENTATION.md`, `README.md`, created `INVESTIGATION.md`.
**Outcome:** `latexdiff_better.py` is now confirmed to work correctly, end-to-end, on
the real esa-rl2ocean-production-model v0.2→v1.0 diff. No further code changes planned
for this investigation.

## 2026-09-30 — spamr v0.1/v1.0 investigation (AGENTS.md follow-up goal)
**Prompt:** User said "See AGENTS.md" to continue with its stated goal: check whether
`latexdiff_better.py` can diff the `v0.1`/`v1.0` tags of the sibling
`esa-rl2ocean-spamr` repository.
**Actions:**
- Confirmed baseline: mamba env present, 80 passed/1 skipped before any changes.
- Ran `latexdiff_better.py --git` with the existing `--old-main` flag (main file
  renamed `rl2ocean_spamr.tex` → `main.tex` between tags, same pattern as the earlier
  production-model investigation) — no code changes needed.
- Compiled the resulting diff with `pdflatex`/`bibtex`; found the system TeX Live was
  also missing `soul.sty` (a dependency of the source document's own preamble, not of
  this tool). Fixed the same way as the earlier `ulem.sty` gap: extracted from CTAN's
  `macros/generic/soul` `.dtx`/`.ins` source into `~/texmf`.
- Full diff now compiles cleanly to a 26-page PDF (`pdflatex` ×3) with zero errors.
- Found and documented (but did NOT fix) a new, real observation: whole sections that
  the diff engine treats as delete-old+add-new (rather than word-level diff) while
  keeping the same `\label{...}` in both versions produce "Label multiply defined"
  LaTeX warnings, since `\sout{}`/`\textcolor{}` don't suppress `\label`'s side effect.
  Harmless in this document; flagged in `AI_REASONING.md`/`DOCUMENTATION.md` for
  discussion before any fix is attempted.
- Updated `DOCUMENTATION.md`, `AI_REASONING.md`, `INVESTIGATION.md`.
**Outcome:** `latexdiff_better.py` confirmed to work end-to-end on the real
esa-rl2ocean-spamr v0.1→v1.0 diff, no code changes required. One new (non-blocking)
limitation identified and left open for user discussion.

## 2026-09-30 — Fixing the duplicate-`\label` warning (user follow-up)
**Prompt:** User asked: "could the label of the deleted section be changed, e.g.,
adding `_old`?" — proposing a fix direction for the multiply-defined-label finding
above. Then chose the "unique_old" option (append `_old`, `_old2`, ... if the same
name is deleted more than once) when asked to confirm via `ask_user`.
**Actions:**
- Added `_suffix_deleted_labels()` + a small per-run registry
  (`reset_deleted_label_registry()`, module-level `_deleted_label_counts`), called
  from `del_markup()` so every deletion-rendering path (line-level, word-level, table
  cells) is covered by one change.
- Wired `reset_deleted_label_registry()` into `main()`'s shared pipeline and into the
  test suite's `run_diff()` helper (plus an explicit `setup_method` for unit tests
  calling `del_markup()` directly) for per-run/per-test isolation.
- Added `TestBug8DeletedLabelRenamed` (3 tests): unit-level rename check, uniqueness
  bump (`_old` → `_old2`), and a test exercising the actual `diff_text_block(old, '')`
  / `diff_text_block('', new)` code path that produced the real-world bug.
- Ran full suite (83 passed, 1 skipped, up from 80/1), `mypy` (fixed one new
  missing-annotation error), `ruff`/`pylint`/`codespell`/`complexipy` (confirmed all
  remaining findings are pre-existing and unrelated, verified via `git stash`
  A/B comparison).
- Regenerated the real esa-rl2ocean-spamr v0.1→v1.0 diff and recompiled
  (`pdflatex` ×3 + `bibtex`): the three previously-warned labels now render as
  `\label{sec:..._old}` (deleted) / `\label{sec:...}` (added); compile now succeeds
  with zero warnings and zero errors (previously: zero errors, three warnings). Same
  26-page, byte-identical PDF.
- Updated `DOCUMENTATION.md`, `AI_REASONING.md`, `INVESTIGATION.md`.
**Outcome:** Duplicate-label finding fixed and verified end-to-end on the real
document; no known open issues remain from either investigation.

## 2026-09-30 — esa-rl2ocean-srs investigation (v0.2 → v1.0), Bugs 9 & 10
**Prompt:** "See AGENTS.md" — continuing the documented goal of testing
`latexdiff_better.py` against the `esa-rl2ocean-srs` sibling repo (AGENTS.md said
"v0.1"/"v1.0"; the repo only has "v0.2"/"v1.0", and had untracked files from a
concurrent process). Asked the user via `ask_user`; user said use `v0.2`/`v1.0` and
ignore the concurrent files.
**Actions:**
- Ran `latexdiff_better.py --git` on esa-rl2ocean-srs v0.2→v1.0 (main file renamed
  `rl2ocean_srs.tex`→`main.tex`, same as prior investigations; output written only to
  `/tmp`, never into the sibling repo).
- Found and fixed Bug 9: `diff_preamble_tables()` paired preamble tables purely by
  position; an inserted macro in v1.0 shifted the pairing, corrupting a
  `\csvlongtable` macro body (fatal "Runaway argument" pdflatex error). Asked the user
  (via `ask_user`) whether to fix with name-based pairing, a structural-compatibility
  safety check, or both — user said "both". Implemented both.
- Found and fixed Bug 10: deleted `\appendix` (entire appendix section removed in
  v1.0) still executed via `{\color{BUR}\appendix}`, and this document's
  `\usepackage{appendix}`+`fncychap` on `article` class fails outright
  (`No counter 'chapter' defined`) whenever `\appendix` executes. Verified with a
  minimal standalone reproduction. Fixed by adding `\appendix` to `_COMMENT_DEL_RE`
  (same pattern as `\section`/`\chapter`/`\begin`/`\end`).
- Regenerated the real diff and compiled (`pdflatex` ×3 + `bibtex`): 67-page PDF, zero
  fatal errors; remaining warnings are expected/cosmetic (dangling refs into the
  deleted appendix, unrelated PDF/font noise).
- Added 4 new regression tests (2 unit for Bug 9, 1 unit for Bug 10, 1 real-repo
  integration test) — full suite now 87 passed, 1 skipped (was 83/1). Ran
  codespell/ruff/mypy/complexipy/pylint, diffed vs. pre-change baseline — no new
  issues; `diff_preamble_tables` complexity rose 10→19, still under the 20 threshold.
- Updated `DOCUMENTATION.md`, `AI_REASONING.md`, `INVESTIGATION.md`.
**Outcome:** Tool confirmed usable end-to-end on this third real document; two more
real bugs found and fixed with regression coverage; no known open issues remain.

## 2026-10-02 — Fourth sibling-repo investigation: esa-rl2ocean-CVA-TN (no main rename)
**Prompt:** Continue AGENTS.md's stated goal: test `latexdiff_better.py --git` against
the `v0.2`→`v1.0` tags of `esa-rl2ocean-CVA-TN`, the fourth sibling repo investigated.
**Actions:**
- Ran the tool against the real repo (scratch copy in `/tmp/cva-tn-compile`); no
  main-file rename this time (`main.tex` at both tags). Most table-heavy document so
  far (48 body tables); first to exercise `\hhline`, `\cline`, legacy `$$...$$`,
  `\begin{equation}`, and URL `#` fragments heavily.
- Found and fixed Bug 11: `\textcolor{ao}{\url{...#...}}` breaks hyperref's
  `\textcolor` patch (raw `#`). Fixed via `add_markup()` falling back to
  `{\color{ao}...}` when text contains a raw `#`.
- Found and fixed Bug 12: content lines inside a wholly-deleted math environment
  (`\begin{equation}`, `\[...\]`, `$$...$$`) were `\sout{}`-wrapped as plain text,
  breaking compilation. Extended sensitive-environment depth tracking to cover math
  environments/delimiters, including a dedicated *old-document* depth tracker for
  purely-deleted blocks (no paired new line exists to drive the normal tracker) —
  this second tracker was added after initial testing showed the first attempt
  (output-depth tracker only) still failed for pure-delete opcodes with
  balanced-brace math content.
- Found and fixed Bug 13: `\hhline{}`/`\cline{}` not recognised as trailing row-end
  markers (only `\hline` was), corrupting the next row's first cell (~474 pdflatex
  errors). Fixed via a shared `_ROW_END_PATTERN` used by all 4 row-parsing call sites.
- Iteratively regenerated the diff and recompiled after each fix: 476 → 2 (after Bug
  13) → 0 fatal errors (after the final old-document depth-tracker fix for Bug 12).
  Full end-to-end compile (`pdflatex` ×3 + `bibtex`) now produces a clean 117-page PDF;
  remaining warnings (2 bibtex missing-citation, acronym hyperrefs,
  `\texttwosuperior`) confirmed pre-existing in the source document itself.
- Added regression tests: `TestBug11RawHashInTextcolor` (4), 
  `TestBug12DeletedMathEnvironmentContent` (4), `TestBug13HhlineClineRowSplitting` (6),
  `TestIntegrationCvaTn` (1 real-repo integration test). Also fixed a latent
  `UnicodeDecodeError` in the shared test `_run()` helper (strict UTF-8 decode failed
  on this document's pdflatex log) — needed for the new integration test to pass.
  Full suite: 102 passed, 1 skipped (up from 87/1). No regressions.
- Ran codespell/ruff/pylint/flake8/mypy/complexipy; no new issues introduced by this
  session's changes (all flagged pre-existing findings fall outside the modified line
  ranges, confirmed via `git diff --stat`/hunk inspection). Noted (not fixed):
  `diff_text_block`'s complexipy score was already far above the 20-point threshold
  before this session (153) and rose to 164 — a pre-existing, previously
  undocumented violation; flagged in `INVESTIGATION.md` as an open question for the
  user rather than silently refactored.
- Updated `DOCUMENTATION.md`, `AI_REASONING.md`, `INVESTIGATION.md`.
**Outcome:** Tool confirmed usable end-to-end on this fourth real document (and the
first with heavy table-rule and math-environment usage); three more real bugs found
and fixed with regression coverage. One pre-existing complexity concern
(`diff_text_block`, score 164) flagged for the user to decide on a future refactor.
