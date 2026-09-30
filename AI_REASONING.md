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
