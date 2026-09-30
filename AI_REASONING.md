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
