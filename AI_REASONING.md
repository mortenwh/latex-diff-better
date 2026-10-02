# AI Reasoning Notes

Notes on non-trivial reasoning/decisions, kept so a future session (or a fresh AI
session) does not have to rediscover them from scratch.

## 2026-09-30 — Fixing missing `ulem.sty` without root access

**Problem:** The two `TestIntegrationCompile` tests failed with `\normalem` /
`\sout{}` "Undefined control sequence", because `ulem.sty` was not present anywhere
under `/usr/share/texlive` even though `texlive-latex-extra` was already installed
(that Ubuntu package apparently does not ship `ulem` on this system/version).

**Options considered:**
1. `apt install`/reinstall a texlive package that bundles `ulem.sty` — required
   `sudo`, but no passwordless `sudo` is available in this environment, so this was
   not usable non-interactively.
2. Download `ulem.sty` from CTAN and place it in the user's local TeX tree
   (`TEXMFHOME`, i.e. `~/texmf`) — no root needed, and `kpsewhich`/`mktexlsr` pick up
   `TEXMFHOME` automatically. Chosen approach.
3. Vendor `ulem.sty` inside this repo and reference it via `TEXINPUTS` at test time —
   more invasive (adds a third-party file to this repo, needs test-harness changes)
   for no real benefit over option 2, since option 2 fixes the system for all future
   compiles, not just this repo's tests.

**Decision:** Option 2. `ulem` is a very old, stable, widely-used base LaTeX package
(part of the standard "latex-extra" collections on essentially every TeX
distribution); fetching it from the canonical CTAN mirror and installing it exactly
where a user without root would normally add missing packages (`TEXMFHOME`) is safe,
standard practice, and does not touch this repository's code or tests at all — it
only fixes a pre-existing gap in the local machine's TeX Live installation.

**Caveat:** This fix is local to this machine. If this repo is ever run in CI, in a
fresh container, or on a different developer machine, and `ulem.sty` is again
missing, repeat the same `~/texmf` install steps documented in `DOCUMENTATION.md`
(or use `apt install texlive-latex-extra` / equivalent if root is available and that
package happens to include `ulem` there).

## 2026-09-30 — Fixing "Label multiply defined": rename or reuse the existing label?

**Problem:** Diffing `esa-rl2ocean-spamr` v0.1→v1.0 surfaced three "Label ... multiply
defined" LaTeX warnings: a whole section rewritten heavily enough that the diff engine
renders it as fully-deleted-old + fully-added-new (rather than a unified prose diff)
kept the same `\label{...}` in both versions, and neither `\sout{}` nor `\textcolor{}`
markup suppresses a wrapped command's side effect, so both `\label` definitions
execute.

**Options considered:**
1. Comment out `\label{...}` inside deleted structural blocks entirely (never define
   it). Rejected: if the deleted paragraph itself contains a `\ref{}` to that same
   label (common — see the spamr intro paragraph, which references
   `Section~\ref{sec:testing-validation}` inside its own deleted text), removing the
   label definition entirely leaves that `\ref` with nothing to resolve to at all if
   no other definition of the same name exists elsewhere, producing a fresh
   "undefined reference" warning instead of fixing the problem.
2. Leave the deleted `\label` live but rename it uniquely (user's suggestion:
   append `_old`). Chosen approach. The renamed label is inert (nothing references the
   suffixed name) but still executes harmlessly, and the *original* name is now
   defined exactly once (by whichever copy is NOT inside deleted markup), so every
   `\ref` to that name in the whole document — whether itself inside deleted text,
   added text, or unchanged text — resolves to that one surviving definition
   unambiguously, instead of the previous silently-order-dependent behavior.
3. Track collisions precisely (only rename when the same name is *actually* also
   defined elsewhere) instead of blanket-renaming every deleted `\label`. Rejected as
   unnecessary complexity: renaming *every* deleted `\label` unconditionally is
   strictly safe (a renamed-but-uncolliding label is just a harmless unused unique
   anchor) and needs no cross-referencing between the old and new sides of the diff,
   keeping `del_markup()` a simple, local, stateless-per-call transformation (aside
   from the small counter needed for point 4 below).
4. Uniqueness against *itself*: user asked for the rename to be collision-safe even if
   the exact same label name happens to be deleted more than once within one diff run
   (rare, but possible). Implemented via a small module-level counter dict
   (`_deleted_label_counts`), reset once per run by `reset_deleted_label_registry()`
   (called at the top of `main()`'s shared diff pipeline, and by the test suite's
   `run_diff()` helper / an explicit `setup_method` for unit tests that call
   `del_markup()` directly) — first occurrence gets `_old`, second gets `_old2`, etc.

**Verification:** regenerated the real esa-rl2ocean-spamr v0.1→v1.0 diff after the
fix; the three previously-warned labels now render as `\label{sec:..._old}` (deleted)
and `\label{sec:...}` (added, unchanged name); `pdflatex` ×3 + `bibtex` now completes
with zero warnings and zero errors (previously: zero errors but three "multiply
defined" warnings). Same 26-page, byte-identical PDF output.

## 2026-09-30 — Why extract `_parse_git_mode_args` instead of leaving it inline

**Problem:** Adding the `--old-main` flag to `main()`'s inline git-mode argument
parsing pushed `main()`'s complexipy cognitive-complexity score from 35 (already
above the 20 threshold pre-change) to 46.

**Options considered:**
1. Leave it inline and just document the higher score as "inherent to a multi-mode
   CLI dispatcher." Simple, but makes an already-complex function meaningfully worse
   for no structural reason — the git-arg-parsing sub-problem is fully self-contained
   (pure function of `sys.argv[2:]` → parsed fields) and doesn't need to live inside
   `main()`.
2. Extract argument parsing for `--git` mode into a dedicated `_parse_git_mode_args`
   helper, called from `main()`. Chosen approach.

**Result:** `_parse_git_mode_args` is trivial (complexipy score 9). `main()` dropped
to 34 — *lower* than before this session's changes even started (35), despite `main()`
gaining a new mode of operation. `main()`'s remaining complexity is inherent to
dispatching between two-file mode / git-working-tree mode / git-two-commit mode and
is not something to reduce further without a larger restructuring (out of scope for
this session).

## 2026-09-30 — Duplicate `\label` when a whole section is deleted+added (spamr investigation)

**Problem:** Diffing `esa-rl2ocean-spamr` v0.1→v1.0 produced three "Label ... multiply
defined" LaTeX warnings. Root cause: when the segment-level differ decides a section's
prose changed too much to diff word-by-word and instead renders the old section fully
`\sout{}`-deleted and the new section fully `\textcolor{ao}{}`-added, and both versions
happen to keep the same `\label{...}` (typical when a section's *content* is rewritten
but its *identity/anchor* is not), both `\label` commands execute — because neither
`\sout{}` nor `\textcolor{}` suppresses a command's side effects, they only affect
typesetting. This is analogous to (and already covered conceptually by) the documented
"unpaired tables render as separate all-red+all-green" limitation, just for prose
sections instead of tables.

**Why not fixed immediately:** This did not break compilation (only a LaTeX warning)
and did not affect any cross-reference in this particular document (nothing referenced
those labels from a position where the ambiguity mattered). Following AGENTS.md's
"if in doubt, ask" rule, this was first logged as a finding for discussion rather than
guessed at and silently patched. The user then confirmed the fix direction (rename the
deleted label) in a follow-up turn — see the dedicated reasoning entry above for the
implementation that was agreed on and applied.

## 2026-09-30 — Preamble table pairing: name-based vs. safety-check-only (Bug 9)

**Problem:** Diffing `esa-rl2ocean-srs` v0.2→v1.0 crashed pdflatex with a "Runaway
argument" error inside a `\newcommand{\csvlongtable}...` macro body. Root cause:
`diff_preamble_tables()` paired preamble tables purely by position, and v1.0 inserted
a new, unrelated macro-with-table before the existing CSV-table macros, shifting every
later pairing so structurally unrelated table templates (different column counts,
different `\csvcoli`-style placeholders) got diffed cell-by-cell, corrupting the
macro body.

**Options presented to the user (via `ask_user`):**
1. Name-based pairing only (match by enclosing `\newcommand{\name}`).
2. Safety-check-only (detect structural incompatibility, skip diffing if mismatched,
   keep positional pairing otherwise).
3. Both.

**User chose "both".** Reasoning for why both are complementary rather than
redundant: name-based pairing fixes the *common* case (a macro is genuinely
inserted/removed/reordered — the exact scenario that broke here) by using the most
reliable available signal (the macro's own name) instead of a fragile ordinal
position. But name-based pairing alone cannot help when no macro name can be
determined at all (e.g. a bare `\begin{tabular}...}` sitting directly in the preamble,
not inside any `\newcommand`) — for that residual case, pairing still falls back to
position, which can still occasionally pair two genuinely unrelated tables. The
structural-compatibility safety net (`_tables_structurally_compatible`, comparing
heuristically-detected column counts) is what actually prevents *any* mismatched pair
— named or positional — from being diffed and corrupted; it is the last line of
defense, not merely a redundant second check.

**Why column-count comparison, not exact content/structure comparison:** An exact
"are these really the same table" check would require understanding table semantics
deeply (row/column meaning, not just count) — overkill for a safety net whose only
job is "don't corrupt the output", not "diff correctly in every case". A column-count
mismatch is a cheap, robust signal that two tables are very unlikely to be the same
logical table (in every real case observed so far, genuinely-paired old/new tables of
the same macro have matched column counts; only truly-unrelated tables differ). If
the heuristic ever produces a false negative (skips a pair that could have been safely
diffed), the fallback (pass the new table through unchanged) is always safe — never
worse than the previous unconditional-positional-pairing behavior, only ever more
conservative where it matters.

## 2026-09-30 — Complexity note: `diff_preamble_tables` rose from 10 to 19

Adding name-based pairing (with a dict/list bookkeeping loop) and the structural
safety-net check raised `diff_preamble_tables`'s complexipy cognitive-complexity score
from 10 to 19 — still under the project's 20-point acceptability threshold (AGENTS.md),
though above complexipy's own stricter default flag threshold (which is lower than 20).
Not restructured further: the function's logic (collect named/unnamed old tables into
lookup structures once, then walk new tables pairing/checking/diffing each) is already
about as flat as this three-way fallback logic (name match → positional fallback →
structural-compatibility gate) can reasonably be without splitting into multiple tiny
one-call helper functions that would only obscure the single, easy-to-follow control
flow for a reader. `_preceding_macro_name` and `_table_column_count` /
`_tables_structurally_compatible` were already extracted as separate, individually
low-complexity helpers (scores 5 and 13 respectively) specifically to keep
`diff_preamble_tables` itself as simple as this pairing logic allows.

## 2026-09-30 — `\appendix` fix: comment-out vs. a more targeted "run-once" guard (Bug 10)

**Problem:** A deleted `\appendix` (the whole appendix section was removed between
v0.2 and v1.0) was rendered as `{\color{BUR}\appendix}` and still executed, and this
document's `\usepackage{appendix}` + `\usepackage{fncychap}` + `article`-class
combination fails outright (`No counter 'chapter' defined`) the instant `\appendix`
executes at all — verified independently with a minimal standalone snippet containing
just those three ingredients and a bare `\appendix` (no diff markup at all), confirming
this is not specific to the `{\color{}}` wrapping.

**Options considered:**
1. A narrow, `\appendix`-specific guard (e.g. only comment it out if some heuristic
   detects the class/package combination is "risky"). Rejected: overly specific,
   fragile, and solves nothing for the *next* side-effecting argument-less structural
   command found on some other real document — `\appendix`'s underlying problem
   (executing a layout-changing command for content that, semantically, "doesn't
   exist" in the diffed timeline) is identical in kind to why `\section{...}`/
   `\chapter{...}`/`\begin{...}`/`\end{...}` are already unconditionally commented out
   when deleted.
2. Add `\appendix` to the existing `_COMMENT_DEL_RE` list. Chosen approach — it is the
   direct, minimal application of an already-established, already-tested pattern in
   this codebase (comment out structural side-effecting commands rather than execute
   them for deleted content), requiring only a one-line regex addition and no new
   logic.

**Verification:** confirmed the isolated `\appendix`+`fncychap`+`appendix`-package+
`article`-class combination fails even completely outside this tool's diff pipeline
(bare `\appendix` in a minimal document), establishing that the *underlying*
incompatibility is a pre-existing property of that package combination on this
system's TeX Live — not something introduced by the diff tool. The diff tool's own
bug was solely that it executed a *deleted* `\appendix` at all, which it now no longer
does (matching how it already never executes a deleted `\section`/`\chapter`).


## 2026-10-02 — Deleted-math-environment fix needed a second, old-document depth tracker

**Problem (Bug 12, esa-rl2ocean-CVA-TN investigation):** `diff_text_block()` tracks
"sensitive environment" depth (tikzpicture, algorithmic, and — newly added this
session — math environments/`\[...\]`/`$$...$$`) across the whole function, but the
depth counter is explicitly defined and maintained as *output-document* depth: it is
only advanced by lines that appear in the new/output document (`equal`, `insert`,
and the new side of `replace` pairs). This is correct and necessary for those three
opcodes. But a *pure* `delete` SequenceMatcher opcode (an entire
`\begin{equation}...\end{equation}` block removed outright, with no paired "new"
line at all) never advances this tracker — so interior content lines of such a block
were incorrectly treated as "not sensitive" and `\sout{}`-wrapped as plain text,
which still breaks compilation for math content whose braces happen to be balanced
(e.g. `CDF_{sim}(x)-CDF_{m}(x)` has balanced `{}`, so the pre-existing
unbalanced-brace fallback in `_line_is_safe_for_color()` didn't catch it either).

This was caught only because a *direct* unit test (`diff_text_block()` called with an
old string containing a complete deleted equation block with balanced-brace content)
was written and failed, even though end-to-end compilation of the real CVA-TN
document already showed 0 fatal errors — meaning the real document's specific deleted
equation blocks happened not to hit this exact pure-delete + balanced-braces
combination (its math-block deletions were apparently all `replace`-paired against
new content, or had other unbalanced-brace characteristics that the existing
fallback already caught). This reinforces a general lesson for this codebase:
**real-document regression testing alone is not sufficient to confirm a fix is
general** — a single real document exercises only the specific opcode/content
combinations its particular edits happen to produce, not the full space of
SequenceMatcher opcode types a general-purpose line differ must handle correctly.
Direct unit tests targeting the *mechanism* (not just the symptom observed in one
document) are necessary to close this kind of gap.

**Fix:** added a second, parallel depth tracker (`old_sensitive_depth`,
`old_dollar_display_active`, `_track_depth_old()`, `_in_sensitive_context_old()`)
that is advanced by exactly the lines that exist in the *old* document: `equal`
lines (shared by both documents), `delete` lines, and the old side of every
`replace` pairing/remainder (paired loop and the old-only tail). The `delete` and
old-only-tail branches now force-comment based on `_in_sensitive_context_old()`
(checked *before* advancing the tracker with the current line, then OR'd with
`_touches_sensitive_delim()` for the delimiter-line-itself case — mirroring the
existing new-tracker pattern) instead of the previous (observed to be at least
partially coincidental) output-depth-only check. The paired-replace branch now ORs
together both the new-tracker and old-tracker conditions, since either side being
sensitive should force the old line to be commented rather than word-diffed.

**Deliberately not fixed (documented, deferred):** the `section_rename` branch's
`ob[1:]`/`nb[1:]` remainder loops (for a detected section-heading rename within a
`replace` opcode) still do not consult either sensitive-context tracker at all. This
is a pre-existing gap (predates this session), not something this session's changes
regressed, and was not observed to be hit by any real document tested so far (a
section rename immediately abutting a math/sensitive environment is a fairly unusual
document edit). Left as a known limitation in `INVESTIGATION.md`'s "Key remaining
questions" rather than fixed speculatively, per the project's "simplicity first" /
"don't fix unrelated pre-existing issues" conventions — if a future document
surfaces this combination, the same old-tracker mechanism added here should be
extended to those two loops.

**Complexity note:** `diff_text_block()`'s complexipy cognitive-complexity score was
already 153 (far above the project's 20-point threshold) before this session even
started, and rose to 164 across this session's fixes. This pre-existing violation
does not appear to have been flagged or discussed with the user in any prior
session's documentation. Rather than attempt an unplanned refactor of an
already-very-large, actively-in-use function as a side effect of this bug-fix
session (risking new regressions in a function with no existing test coverage of
every branch combination), this was logged as an open question for the user in
`INVESTIGATION.md`, to be addressed as a dedicated, deliberate future task if the
user agrees it's warranted.
