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

- None currently blocking. The tool is confirmed usable, end-to-end, for this
  document pair.
- Possible future improvement (not yet requested): the diffed output currently
  loses the "old main file was `production_model.tex`" information in the legend
  page (it just shows the old commit hash). Low priority — cosmetic only.

## Concrete next steps

- No further code changes planned for this investigation; it is considered resolved.
- If similar brace-unbalancing bugs are found on other real documents in the future,
  check whether they stem from the same class of issue (a naive/non-brace-aware
  tokenizer somewhere) before writing a one-off fix.
