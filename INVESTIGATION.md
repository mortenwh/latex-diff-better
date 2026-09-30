# Investigation: latexdiff_better.py vs. esa-rl2ocean-production-model (v0.2 → v1.0)

## Question

Can `latexdiff_better.py` (`--git` mode) correctly diff the `v0.2` and `v1.0` tags of
the sibling repository `/home/mortenwh/esa-rl2ocean-production-model`? AGENTS.md
raised a suspicion that only raw commit hashes (not tags) might work, requiring code
changes to accommodate.

## Method

1. Inspected the sibling repo: confirmed `v0.2` and `v1.0` are real annotated/lightweight
   git tags resolving to commits `309a0b1` and `bef0e7d` respectively.
2. Ran `git show <ref>:<path>` (the mechanism `git_show()` in `latexdiff_better.py`
   uses) with both the tag name and the raw hash — identical behavior in both cases.
3. Ran `latexdiff_better.py --git <repo> v0.2 v1.0 <main.tex> output.tex` and iterated
   on failures.
4. Compiled the resulting `diff.tex` with `pdflatex` → `bibtex` → `pdflatex` ×2 to
   confirm a valid PDF is produced (not just that the script exits 0).

## Conclusions so far

- **Tags work identically to hashes.** `git show` resolves any ref (tag, branch, or
  hash) the same way; there was nothing to "accommodate" for tags specifically. This
  disproves the AGENTS.md suspicion.
- **The real blocker was a file rename**, not tags vs. hashes: the main file was
  renamed `production_model.tex` (v0.2) → `main.tex` (v1.0). Fixed by adding a new
  `--old-main <path>` CLI flag to `--git` mode (see `DOCUMENTATION.md` and `README.md`).
- **A real, independent bug was found and fixed** while testing on this document:
  `diff_cells_inline` used a brace-unaware tokenizer for word-level diffs inside table
  cells, which broke on a header cell containing `\textbf{SLC Pixel Spacing}` →
  `\textbf{\ac{SLC} Pixel Spacing}` (a word replaced by a LaTeX command), producing
  unbalanced braces and a fatal `pdflatex` "Runaway argument" error. Fixed by reusing
  the existing brace-aware `_latex_tokenize` (already used by `diff_words_in_line`).
  See `AI_REASONING.md` for why this fix was chosen over alternatives.
- End-to-end verification: `python3 latexdiff_better.py --git
  /home/mortenwh/esa-rl2ocean-production-model v0.2 v1.0 main.tex --old-main
  production_model.tex output.tex` now produces a `diff.tex` that compiles cleanly to
  a PDF via `pdflatex`/`bibtex` with no fatal errors. Remaining LaTeX warnings
  (`undefined references` for a couple of acronym/section labels) were verified to be
  pre-existing in the source document itself (the corresponding `\label`/acronym
  definitions genuinely do not exist in the source), not something introduced by the
  diff tool.
- Regression tests added: `TestBug7CellInlineBraceAwareTokenizer` (brace-tokenizer
  fix), `TestOldMainFlag` (fast unit-level `--old-main` test, no external repo
  needed), `TestIntegrationRl2oceanOldMainRename` (full real-repo integration test,
  skipped if the sibling repo/`pdflatex`/`bibtex` are not present).

## Key remaining questions

- None currently blocking for the production-model document pair. The tool is
  confirmed usable, end-to-end, for this document pair.
- Possible future improvement (not yet requested): the diffed output currently
  loses the "old main file was `production_model.tex`" information in the legend
  page (it just shows the old commit hash). Low priority — cosmetic only.
- **New, from the follow-up spamr investigation below:** should `latexdiff_better.py`
  suppress/comment out `\label{...}` inside fully deleted (`\sout{}`-wrapped)
  structural blocks when the same label is re-defined in the corresponding added
  block, to avoid "Label multiply defined" LaTeX warnings? Open question for the
  user — see the spamr section below for details; not yet decided or implemented.

## Concrete next steps

- No further code changes planned for the production-model investigation; it is
  considered resolved.
- If similar brace-unbalancing bugs are found on other real documents in the future,
  check whether they stem from the same class of issue (a naive/non-brace-aware
  tokenizer somewhere) before writing a one-off fix.
- Discuss with the user whether the duplicate-`\label` observation (found on
  esa-rl2ocean-spamr, see below) warrants a fix, and if so, what the right behavior
  is when a label is reused across a deleted+added section pair.

---

# Investigation: latexdiff_better.py vs. esa-rl2ocean-spamr (v0.1 → v1.0)

## Question

Following up on the AGENTS.md project goal: can `latexdiff_better.py` (`--git` mode)
correctly diff the `v0.1` and `v1.0` tags of the sibling repository
`/home/mortenwh/esa-rl2ocean-spamr`?

## Method

Same method as the production-model investigation above: inspect the sibling repo's
file structure at both tags, run `latexdiff_better.py --git`, then compile the
resulting diff with `pdflatex`/`bibtex` to confirm a valid PDF is produced.

## Conclusions so far

- **Works out of the box with the existing `--old-main` flag.** The main file was
  renamed `rl2ocean_spamr.tex` (v0.1) → `main.tex` (v1.0) — the same rename pattern
  already handled by the flag added during the production-model investigation. No new
  code changes were needed for this repo.
- **No CSV tables in this document** (unlike production-model), so the CSV-expansion
  code path was not exercised here.
- **Missing `soul.sty` on this machine's TeX Live**, same class of issue as the
  earlier `ulem.sty` gap — a system TeX Live gap, not a bug in this tool. Fixed the
  same way (installed into `~/texmf` via `TEXMFHOME`); see `DOCUMENTATION.md` for the
  exact commands (note: `soul` is now CTAN-hosted at `macros/generic/soul` as
  `.dtx`/`.ins` source, not a prebuilt `.zip` under `macros/latex/contrib/soul`).
- **Fixed (2026-09-30, follow-up):** three sections
  (`sec:testing-validation`, `sec:spr-ncr`, `sec:reference-progress-reports`) were
  rewritten heavily enough that the diff engine renders them as a fully-deleted old
  section plus a fully-added new section (rather than a unified prose diff), and both
  versions keep the same `\label{...}`. Since `\sout{}`/`\textcolor{}` markup does not
  suppress a wrapped command's side effect, both `\label` definitions used to execute,
  producing "Label ... multiply defined" LaTeX warnings. Fixed by having
  `del_markup()` rename any `\label{X}` inside deleted text to `\label{X_old}` (unique
  per name within a run, via a small registry reset by
  `reset_deleted_label_registry()`). Verified: regenerated the real diff — the three
  labels now render as `\label{sec:..._old}` (deleted) / `\label{sec:...}` (added);
  `pdflatex`×3 + `bibtex` now completes with zero warnings and zero errors (previously
  zero errors, three warnings). See `AI_REASONING.md` for the alternatives considered.
- End-to-end verification: `python3 latexdiff_better.py --git
  /home/mortenwh/esa-rl2ocean-spamr v0.1 v1.0 main.tex --old-main
  rl2ocean_spamr.tex output.tex` produces a `diff.tex` that compiles cleanly
  (`pdflatex` ×3) to a 26-page PDF with zero errors and (after the label-rename fix)
  zero warnings, aside from an expected "no `\citation` commands" bibtex message
  since this document has no citations.

## Key remaining questions

- None currently open for the production-model or spamr investigations.

## Concrete next steps

- No further code changes planned for production-model/spamr; both are considered
  resolved. If a future diff on a different document surfaces a *different*
  multiply-defined-label scenario (e.g. a genuinely reused label with a legitimate
  cross-document meaning, not just a rewritten section keeping its anchor), re-check
  whether the current blanket-rename-on-delete approach still gives the desired
  result before assuming it does.

---

# Investigation: latexdiff_better.py vs. esa-rl2ocean-srs (v0.2 → v1.0)

## Question

Following up on AGENTS.md's stated goal: can `latexdiff_better.py` (`--git` mode)
correctly diff the tags of the sibling repository `/home/mortenwh/esa-rl2ocean-srs`?
(AGENTS.md names "v0.1"/"v1.0"; the repo only has `v0.2` and `v1.0` — confirmed with
the user, who chose to proceed with `v0.2`→`v1.0`.)

## Method

Same method as the earlier two investigations: inspect the sibling repo's file
structure at both tags, run `latexdiff_better.py --git` (writing output outside the
sibling repo, to `/tmp`, since another concurrent session appeared to already be
using files inside the sibling repo itself — read via `git show` never requires
writing into the sibling repo), then compile the resulting diff with
`pdflatex`/`bibtex` to confirm a valid PDF is produced. Also independently verified
the `\appendix` finding (below) with a minimal standalone LaTeX snippet, isolated from
the diff pipeline, to distinguish a diff-tool bug from a pre-existing document/package
incompatibility.

## Conclusions so far

- **Main file renamed here too**: `rl2ocean_srs.tex` (v0.2) → `main.tex` (v1.0). Same
  pattern as production-model/spamr; handled by the existing `--old-main` flag, no
  code change needed.
- **This is the most CSV-heavy document tested so far**: 44 body table environments
  expanded from `\csvlongtable`/`\csvlongtbd`/`\csvlongtrace` commands (vs. 0 for
  spamr). This exercised the CSV-expansion and preamble-table-diffing code paths much
  more heavily than either prior investigation, and surfaced two new, previously
  latent bugs — both are now fixed (see `DOCUMENTATION.md` for full detail,
  `AI_REASONING.md` for the alternatives considered):
  - **Bug 9 (fatal compile error)**: `diff_preamble_tables()` paired preamble tables
    (found inside `\newcommand{...}` macro bodies) purely by position. A macro
    inserted before the existing CSV-table macros in v1.0's preamble shifted every
    later pairing, causing structurally unrelated macro templates (different column
    counts) to be diffed cell-by-cell against each other, corrupting the macro
    bodies (unbalanced braces → fatal pdflatex "Runaway argument" error). Fixed with
    name-based pairing (by enclosing `\newcommand{\name}`) plus a structural
    compatibility safety net that skips diffing (passes the new table through
    unchanged) when paired tables have different column counts.
  - **Bug 10 (fatal compile error)**: `\appendix` (a side-effecting, argument-less
    structural command) was missing from `_COMMENT_DEL_RE`, so a deleted `\appendix`
    (the entire appendix section was removed between v0.2 and v1.0) was rendered as
    `{\color{BUR}\appendix}` and still executed. This document's
    `\usepackage{appendix}` + `\usepackage{fncychap}` combination on the `article`
    class fails with `No counter 'chapter' defined` the moment `\appendix` executes
    at all — verified independently with a minimal standalone reproduction, isolating
    that this is triggered by executing `\appendix` itself (not by the `{\color{}}`
    wrapping). Fixed by adding `\appendix` to `_COMMENT_DEL_RE`, matching the existing
    treatment of `\section`/`\chapter`/`\begin`/`\end`.
- End-to-end verification: `python3 latexdiff_better.py --git
  /home/mortenwh/esa-rl2ocean-srs v0.2 v1.0 main.tex --old-main rl2ocean_srs.tex
  output.tex` now produces a `diff.tex` that compiles cleanly (`pdflatex` ×3,
  `bibtex` — no citations, expected) to a 67-page PDF with zero fatal errors.
  Remaining warnings are expected/cosmetic: dangling `\ref{}` calls inside deleted
  prose that referenced labels defined only inside the now-fully-deleted appendix
  section (correctly renamed to `_old` per the Bug 8 fix, so these refs legitimately
  have nothing to resolve to — the same class of limitation already documented for
  restructured/moved content), plus unrelated PDF/font-metadata noise.
- Regression tests added: `TestBug9PreambleTableNamePairing` (2 tests, unit-level on
  `diff_preamble_tables` directly), `TestBug10AppendixCommentedOnDelete` (1 test),
  `TestIntegrationRl2oceanSrsOldMainRename` (1 test, full real-repo integration test,
  skipped if the sibling repo/`pdflatex`/`bibtex` are not present). Full suite: 87
  passed, 1 skipped (up from 83/1).

## Key remaining questions

- None currently open for this investigation — the tool is confirmed usable,
  end-to-end, for this document pair.

## Concrete next steps

- No further code changes planned for the srs investigation; it is considered
  resolved. If a future document surfaces *another* preamble-table-pairing
  mismatch that the name-based + structural-compatibility approach doesn't catch
  (e.g. two same-named macros with genuinely different table content that both
  happen to have the same column count), revisit `diff_preamble_tables()` then.
- If a future document uses another side-effecting, argument-less structural
  command not yet in `_COMMENT_DEL_RE` (Bug 10's class of issue), add it there
  following the same pattern.

