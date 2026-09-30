# DOCUMENTATION

Technical documentation for `latexdiff-better`. For a quick user-facing summary see
`README.md`.

## Purpose

`latexdiff_better.py` produces a highlighted diff (`gitdiff.tex`-style output) between
two versions of a LaTeX document, with special handling for tables — including tables
generated from CSV files via `\csvlongtable` / `\csvlongtbd` / `\csvlongtrace` commands,
which the standard `latexdiff` perl script cannot diff correctly.

## Environment setup

The project uses a dedicated mamba environment, `latexdiff-better`, defined in
`environment.yml` (conda-forge channel only, all versions pinned).

Create it with:

```bash
mamba env create -f environment.yml
mamba activate latexdiff-better
```

Dependencies:
- `python=3.11.16` — runtime
- `pytest=9.1.1` — test runner
- `loguru=0.7.3`, `tqdm=4.70.1` — reserved for future logging/progress needs (not yet
  used by the current script, which relies on `print()`/stdlib only)
- `codespell=2.4.3`, `ruff=0.16.9`, `pylint=4.0.10`, `flake8=7.4.1`, `mypy=2.3.1`,
  `complexipy=8.0.1` — linting, static typing, and complexity checks

### LaTeX toolchain (system, not mamba)

`pdflatex` and `bibtex` are provided by the system TeX Live install
(`texlive-*` apt packages) and are used only by the integration tests
(`tests/test_latexdiff_better.py::TestIntegrationCompile`) to confirm that generated
diff `.tex` files actually compile.

This system's TeX Live install was missing `ulem.sty` (needed because diff output uses
`\sout{}` for struck-through deleted text). Since there is no passwordless `sudo` in
this environment, `ulem.sty` was installed into the user's local TeX tree instead of via
apt:

```bash
curl -sL https://mirrors.ctan.org/macros/latex/contrib/ulem.zip -o /tmp/ulem.zip
unzip -o /tmp/ulem.zip -d /tmp/ulem_pkg
mkdir -p ~/texmf/tex/latex/ulem
cp /tmp/ulem_pkg/ulem/ulem.sty ~/texmf/tex/latex/ulem/
mktexlsr ~/texmf
```

`kpsewhich` picks up `~/texmf` (`TEXMFHOME`) automatically once the file is placed
there and `mktexlsr` has refreshed the filename database. If this repo is set up on a
fresh machine and integration tests fail with `\normalem` / `\sout` undefined-control-
sequence errors, repeat the steps above (or install `texlive-latex-extra` via apt if
`sudo` is available and it happens to include `ulem.sty` on that system).

The same system TeX Live install was also missing `soul.sty` (needed by some source
documents' own preamble, e.g. via the `doclicense` package — unrelated to this tool's
own markup). `soul` is now distributed only as `.dtx`/`.ins` source under
`macros/generic/soul` on CTAN (not a prebuilt `.zip` under `macros/latex/contrib/soul`
as older instructions might suggest), so it must be extracted with `tex`:

```bash
curl -sL https://mirrors.ctan.org/macros/generic/soul.zip -o /tmp/soul.zip
unzip -o /tmp/soul.zip -d /tmp/soul_pkg
cd /tmp/soul_pkg/soul && tex soul.ins   # generates soul.sty, soul-ori.sty, soulutf8.sty
mkdir -p ~/texmf/tex/latex/soul
cp soul.sty soul-ori.sty soulutf8.sty ~/texmf/tex/latex/soul/
mktexlsr ~/texmf
```

## Running tests

```bash
mamba activate latexdiff-better
pytest -q
```

As of the last verified run: 83 passed, 1 skipped (skip reason: an optional dependency
of one test is unavailable — see test file for details), 0 failed.

Tests are marked `integration` (see `pytest.ini`) when they invoke `pdflatex`/`bibtex`
to verify the generated diff actually compiles; these are automatically skipped if
`pdflatex`/`bibtex` are not found on `PATH`.

## Code structure (`latexdiff_better.py`)

Single-file script, organized as a pipeline of pure functions (no classes). Rough
grouping, in file order:

- **Markup helpers**: `add_markup`, `del_markup`, `is_structural` — wrap text in
  add/delete highlighting, detect structural LaTeX commands that must not be
  colored/struck. `del_markup` also renames any `\label{...}` inside deleted text via
  `_suffix_deleted_labels` (registry reset per run by `reset_deleted_label_registry`,
  called from `main()`) to avoid "Label multiply defined" clashes with a surviving
  same-named label.
- **Brace/tag parsing**: `match_brace_group`, `parse_begin_tag`, `parse_end_tag`,
  `_pos_in_comment` — brace-aware and comment-aware parsing primitives used throughout.
- **Table detection & row/cell splitting**: `find_table_spans`, `segment_text`,
  `split_cells`, `count_cells`, `parse_table_rows`, `_split_rows_brace_aware` — locate
  table environments in the body and split them into rows/cells without breaking on
  braces or commented-out `&`/`\\`.
- **Row/table diffing**: `diff_tables`, `_diff_row_pair`, `diff_cells_inline`,
  `render_added_row`, `render_deleted_row`, `wrap_table_added`, `wrap_table_deleted` —
  match old/new rows by key, diff matched rows cell-by-cell, and render whole
  added/deleted tables.
- **Text (non-table) diffing**: `diff_text_block`, `diff_words_in_line`,
  `_safe_del_line`, `_safe_add_line`, `_latex_tokenize` — line/word-level diff for
  prose, with safety checks to avoid producing uncompilable output (unbalanced braces,
  structural commands, etc.).
- **Segment-level orchestration**: `diff_segments` — walks the alternating
  text/table segments of old vs new body and dispatches to the right differ,
  merging adjacent text+table+text replacements where needed.
- **CSV table expansion**: `_read_csv`, `_row_to_latex`, `csv_to_xltabular`,
  `expand_csv_commands`, `expand_all_csv_commands` — turn `\csvlongtable{file.csv}`-
  style commands into literal `xltabular` LaTeX tables so they can be diffed like any
  other table.
- **Multi-file / git input handling**: `git_show`, `flatten`, `flatten_from_disk`,
  `flatten_from_git` — resolve `\include`/`\input` across files, either from disk or
  from a git commit via `git show`.
- **Preamble handling**: `split_preamble_body`, `diff_preamble_tables`,
  `inject_diff_packages` — diff preamble-defined tables, inject the packages
  (`xcolor`, `ulem`, etc.) needed by the diff markup into the new preamble.
- **Legend page**: `make_diff_legend_page`, `_tex_escape_label` — generate the
  human-readable colour-coding legend page prepended to diff output (see README).
- **`main()`**: CLI argument parsing and pipeline orchestration. Two invocation modes:
  - Two-file mode: `latexdiff_better.py old.tex new.tex output.tex`
  - Git mode: `latexdiff_better.py --git [<repo_dir>] <old_commit> [<new_commit>] <main.tex> output.tex [--old-main <path>]`
    (repo defaults to cwd; if `<new_commit>` is omitted, diffs against the working tree;
    `<old_commit>`/`<new_commit>` can be tags, branches, or raw hashes — `git show`
    resolves any of them identically). `--old-main <path>` overrides the path looked
    up at `<old_commit>`, for the case where the main file was renamed between
    versions. Argument parsing for this mode lives in `_parse_git_mode_args`.

## Known limitations

See the "KNOWN LIMITATIONS" section of `README.md` — moved tables between sections can
show as separate delete+add rather than a unified row diff; lines with unbalanced
braces are commented out (`% DIFF-DEL: ...`) rather than shown struck through; preamble
changes in the new document are not diffed/shown.

## Investigation: v0.2 → v1.0 diff of esa-rl2ocean-production-model

Verified (2026-09-30) that `latexdiff_better.py --git` correctly diffs the `v0.2` →
`v1.0` tags of the sibling `esa-rl2ocean-production-model` repository, producing a
`diff.tex` that compiles cleanly through `pdflatex` → `bibtex` → `pdflatex` ×2 to a PDF.

Two findings from this investigation, both now fixed in this repo:

1. **Tags vs. hashes — not actually an issue.** `git show <ref>:<path>` (used by
   `git_show()`) resolves tags, branches, and raw commit hashes identically; there is
   no need to pre-resolve tags to hashes before calling the script. The AGENTS.md
   suspicion that "we can only use hash codes" was investigated and found incorrect.
2. **Renamed main file — a real, now-fixed limitation.** The main file was renamed
   from `production_model.tex` (at `v0.2`) to `main.tex` (at `v1.0`). `--git`'s
   two-commit mode previously assumed the same path in both commits. Fixed by adding
   the `--old-main <path>` flag (see above), which overrides the path used to look up
   the file at `<old_commit>` only.
3. **Bug found and fixed while testing on this real document**: `diff_cells_inline`
   (word-level diff inside table cells) tokenized cell text with a naive `\S+|\s+`
   regex, which splits inside `\cmd{...}` groups (e.g. `\textbf{SLC` and `Spacing}`
   become separate tokens). When a word-level replacement then wrapped only one such
   fragment in `{\color{...}...}`, it produced unbalanced braces and a fatal pdflatex
   "Runaway argument" error. Fixed by switching `diff_cells_inline` to the same
   brace-aware `_latex_tokenize` already used by `diff_words_in_line`. Regression
   tests: `TestBug7CellInlineBraceAwareTokenizer` in
   `tests/test_latexdiff_better.py`.

Example invocation used to reproduce/verify:

```bash
python3 latexdiff_better.py --git /home/mortenwh/esa-rl2ocean-production-model \
    v0.2 v1.0 main.tex --old-main production_model.tex /tmp/diff.tex
```

## Investigation: v0.1 → v1.0 diff of esa-rl2ocean-spamr

Verified (2026-09-30) that `latexdiff_better.py --git` correctly diffs the `v0.1` →
`v1.0` tags of the sibling `esa-rl2ocean-spamr` repository. This document has no CSV
tables (unlike the production-model repo) and no code changes were needed — the
existing `--old-main` flag (added during the production-model investigation) already
covers this repo's main-file rename.

Findings:

1. **Main file renamed here too**: `rl2ocean_spamr.tex` (v0.1) → `main.tex` (v1.0).
   Handled with the existing `--old-main rl2ocean_spamr.tex` flag; no code change
   needed.
2. **Missing `soul.sty` on this machine's TeX Live** (see "Environment setup" above
   for the fix) — unrelated to `latexdiff_better.py` itself; it is a dependency of the
   source document's own preamble (via `doclicense`), not of the diff markup this tool
   generates.
3. **Bug found and fixed while testing**: when a whole section was rewritten heavily
   enough that the diff engine rendered it as a fully deleted old section plus a fully
   added new section (rather than a unified prose diff), and both versions kept the
   same `\label{...}`, both `\label` commands executed — `\sout{}`/`\textcolor{}`
   markup doesn't suppress a wrapped command's side effect — causing a LaTeX "Label
   ... multiply defined" warning and making `\ref` resolution depend on document
   order. Fixed by having `del_markup()` rename any `\label{X}` found in deleted text
   to `\label{X_old}` (or `_old2`, `_old3`, ... if the same name is deleted more than
   once in one run — tracked via a small module-level registry reset once per diff
   run by `reset_deleted_label_registry()`). The surviving (added/unchanged)
   definition keeps its original name, so every `\ref` in the document resolves to it
   unambiguously; the renamed deleted copy becomes an inert, uniquely-named label that
   nothing references. Regression tests: `TestBug8DeletedLabelRenamed` in
   `tests/test_latexdiff_better.py`.

Example invocation used to reproduce/verify:

```bash
python3 latexdiff_better.py --git /home/mortenwh/esa-rl2ocean-spamr \
    v0.1 v1.0 main.tex --old-main rl2ocean_spamr.tex /tmp/spamr_diff.tex
```

Compiled cleanly (`pdflatex` ×3, `bibtex` — no citations in this doc so bibtex found
nothing to do, which is expected) to a 26-page PDF with zero errors and zero warnings
(after the `\label` rename fix above; before it, this document is exactly what
surfaced the three "Label ... multiply defined" warnings).

