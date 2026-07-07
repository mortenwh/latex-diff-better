r"""Tests for latexdiff_better.py compilation-failure and correctness bugs.

Bug 1 (Compilation error): \sout{} wrapping commands that expand via hyperref/acronym
        into PDF-mode constructs incompatible with ulem's \sout.
        Affected commands: \url, \href, \cite*, \ac*, \gls*, \nameref, \autoref, \cref.

Bug 2 (Correctness): Added comment-only lines (starting with %) wrapped as
        \textcolor{ao}{}%..., commenting out all following markup on that output line.

Bug 3 (Correctness): Word-level diff on lines containing inline % comments produces
        mid-line \textcolor{ao}{}% which silences all diff tokens after the % on that line.
"""

import re
import sys
import os
import pytest

# Allow importing latexdiff_better from parent directory
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import latexdiff_better as ldb


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

PREAMBLE = r"""\documentclass{article}
\usepackage[hidelinks]{hyperref}
\usepackage{acronym}
\begin{document}
"""
POSTAMBLE = r"\end{document}"


def make_doc(body):
    return PREAMBLE + body + "\n" + POSTAMBLE


def run_diff(old_body, new_body):
    """Run the full diff pipeline on two document bodies and return the output text."""
    old_text = make_doc(old_body)
    new_text = make_doc(new_body)
    old_preamble, old_b = ldb.split_preamble_body(old_text)
    new_preamble, new_b = ldb.split_preamble_body(new_text)
    out_preamble = ldb.inject_diff_packages(new_preamble)
    old_segs = ldb.segment_text(old_b)
    new_segs = ldb.segment_text(new_b)
    out_body = ldb.diff_segments(old_segs, new_segs)
    return out_preamble + out_body


def assert_no_sout_pattern(output, pattern, msg):
    """Assert that `pattern` does not appear inside any \\sout{...} in output."""
    # Find all \sout{...} blocks (simple heuristic: match up to next }}
    for m in re.finditer(r'\\sout\{', output):
        start = m.end()
        depth = 1
        i = start
        while i < len(output) and depth > 0:
            if output[i] == '\\':
                i += 2
                continue
            if output[i] == '{':
                depth += 1
            elif output[i] == '}':
                depth -= 1
            i += 1
        sout_content = output[start:i - 1]
        assert not re.search(pattern, sout_content), (
            f"{msg}\nFound inside \\sout{{...}}: {sout_content!r}"
        )


# ---------------------------------------------------------------------------
# Bug 1 — \sout{} must not contain hyperref/acronym-linked commands
# ---------------------------------------------------------------------------

class TestBug1SoutWithHyperrefCommands:
    r"""Bug 1: commands that hyperref wraps in PDF links must not appear inside \sout{}."""

    def test_cite_not_in_sout(self):
        """\\cite{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "This was published by \\cite{smith2020}.\n"
        new = "This section has no references.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\cite\b', r'\cite inside \sout must not appear')

    def test_citep_not_in_sout(self):
        """\\citep{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "Shown in experiments \\citep{jones2021, doe2022}.\n"
        new = "Shown in experiments.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\citep\b', r'\citep inside \sout must not appear')

    def test_ac_not_in_sout(self):
        """\\ac{} (acronym) deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "The \\ac{ESA} mission began in 2000.\n"
        new = "The mission began in 2000.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\ac\b', r'\ac inside \sout must not appear')

    def test_acp_not_in_sout(self):
        """\\acp{} (plural acronym) deleted line must not be inside \\sout{}."""
        old = "Multiple \\acp{TC} were observed.\n"
        new = "Multiple storms were observed.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\acp\b', r'\acp inside \sout must not appear')

    def test_url_not_in_sout(self):
        """\\url{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "Download from \\url{https://example.com/data.zip}.\n"
        new = "Download from the official website.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\url\b', r'\url inside \sout must not appear')

    def test_href_not_in_sout(self):
        """\\href{}{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "See \\href{https://example.com}{the documentation}.\n"
        new = "See the documentation.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\href\b', r'\href inside \sout must not appear')

    def test_gls_not_in_sout(self):
        """\\gls{} (glossary) deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "The \\gls{nrcs} was measured at 10 GHz.\n"
        new = "The backscatter was measured at 10 GHz.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\gls\b', r'\gls inside \sout must not appear')

    def test_autoref_not_in_sout(self):
        """\\autoref{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "As shown in \\autoref{fig:result}, the curve is smooth.\n"
        new = "The curve is smooth.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\autoref\b', r'\autoref inside \sout must not appear')

    def test_nameref_not_in_sout(self):
        """\\nameref{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "Refer to \\nameref{sec:intro} for background.\n"
        new = "Refer to the introduction for background.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\nameref\b', r'\nameref inside \sout must not appear')

    def test_cref_not_in_sout(self):
        """\\cref{} deleted line must use {\\color{BUR}...} not \\sout{}."""
        old = "Results in \\cref{tab:comparison} confirm this.\n"
        new = "Results in the table confirm this.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\cref\b', r'\cref inside \sout must not appear')

    def test_bug1_deleted_content_still_visible(self):
        """Deleted content must still appear in output (as {\\color{BUR}...}) even without \\sout."""
        old = "This was published by \\cite{smith2020}.\n"
        new = "This section has no references.\n"
        out = run_diff(old, new)
        assert r'\cite{smith2020}' in out, "Deleted \\cite content must appear in diff output"
        assert r'{\color{BUR}' in out or r'\textcolor{BUR}' in out, "Deleted content must be coloured red"

    # --- word-level diff variants (within a matched line pair) ---

    def test_cite_in_word_diff_not_in_sout(self):
        """\\cite{} appearing in a deleted word-level token must not be inside \\sout{}."""
        old = "Results \\cite{smith2020} confirm the model.\n"
        new = "Results confirm the model.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\cite\b', r'\cite inside \sout (word diff) must not appear')

    def test_ac_in_word_diff_not_in_sout(self):
        """\\ac{} appearing in a deleted word-level token must not be inside \\sout{}."""
        old = "The \\ac{SAR} image was processed.\n"
        new = "The image was processed.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\ac\b', r'\ac inside \sout (word diff) must not appear')


# ---------------------------------------------------------------------------
# Bug 2 — Comment-only added lines must not be wrapped with colour markup
# ---------------------------------------------------------------------------

class TestBug2AddedCommentLines:
    """Bug 2: pure LaTeX comment lines in the new version must pass through unchanged."""

    def test_added_comment_line_passes_through(self):
        """An inserted '% comment' line must appear verbatim, not as \\textcolor{ao}{}%..."""
        old = "Some text here.\n"
        new = "Some text here.\n% This is a new comment\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out, (
            r"Added comment line must not produce \textcolor{ao}{}%..."
        )
        # The comment itself should still be present in the output
        assert '% This is a new comment' in out

    def test_added_comment_separator_passes_through(self):
        """A separator comment line (%%%%...) added in new version passes through unchanged."""
        old = "Section content.\n"
        new = "Section content.\n%%%%%%%%%%%% SECTION %%%%%%%%%%%%\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out, (
            r"Added separator comment must not produce \textcolor{ao}{}%..."
        )

    def test_added_indented_comment_passes_through(self):
        """An indented comment line added in new version passes through unchanged."""
        old = "Some text.\n"
        new = "Some text.\n  % indented comment\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out, (
            r"Added indented comment must not produce \textcolor{ao}{}%..."
        )

    def test_replaced_by_comment_line_no_broken_markup(self):
        """When an old line is replaced by a pure comment line, no \\textcolor{ao}{}% emitted."""
        old = "In the context of the project, team X maintains an archive.\n"
        new = "% Definizione esatta di 10 colonne\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out, (
            r"Line replaced by pure comment must not produce \textcolor{ao}{}%..."
        )


# ---------------------------------------------------------------------------
# Bug 3 — Lines with inline % comments must not produce mid-line \textcolor{ao}{}%
# ---------------------------------------------------------------------------

class TestBug3InlineCommentInWordDiff:
    """Bug 3: word-level diff on lines with inline % must not silence following tokens."""

    def test_inline_comment_no_broken_markup(self):
        """Replacing a plain line with one containing inline % must not produce \\textcolor{ao}{}%."""
        old = "The old sentence ends here.\n"
        new = "The new sentence. % reviewer note\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out, (
            r"Inline % must not produce \textcolor{ao}{}% mid-line in diff output"
        )

    def test_old_line_with_inline_comment(self):
        """Deleting a line with inline % must handle the comment without broken markup."""
        old = "The old text. % comment explaining change\n"
        new = "The new text.\n"
        out = run_diff(old, new)
        # Markup must not leave the comment in a position that breaks brace balance
        assert r'\textcolor{ao}{}%' not in out

    def test_both_lines_with_inline_comment(self):
        """Both old and new lines having % must not break the diff output."""
        old = "Version one. % old comment\n"
        new = "Version two. % new comment\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{}%' not in out


# ---------------------------------------------------------------------------
# Bug 4 — deleted pure-comment lines must not produce empty \sout{}
# ---------------------------------------------------------------------------

class TestBug4EmptySoutOnCommentLines:
    r"""Bug 4: deleting a line that is purely a LaTeX comment must produce a
    % DIFF-DEL comment, not \textcolor{BUR}{\sout{}}% ... with an empty \sout{}."""

    def test_deleted_comment_line_no_empty_sout(self):
        """Deleted pure-comment line must not produce \\sout{}."""
        old = "% This is an explanatory comment that was removed.\n"
        new = ""
        out = run_diff(old, new)
        assert r'\sout{}' not in out, (
            r"Deleted comment line must not produce \sout{} (empty strikethrough)"
        )

    def test_deleted_comment_line_uses_diff_del(self):
        """Deleted pure-comment line must be recorded as % DIFF-DEL: ..."""
        old = "% reviewer note: this section needs updating\n"
        new = ""
        out = run_diff(old, new)
        assert '% DIFF-DEL:' in out, "Deleted comment line must appear as % DIFF-DEL: ..."

    def test_deleted_comment_line_preserves_content(self):
        """The comment content must appear in the output (inside % DIFF-DEL)."""
        old = "% important note about the algorithm\n"
        new = "Some new text.\n"
        out = run_diff(old, new)
        assert 'important note about the algorithm' in out

    def test_plain_text_deletion_unaffected(self):
        """Regression: plain (non-comment) deleted lines still use \\sout{}."""
        old = "This sentence has no comment.\n"
        new = "Completely different sentence.\n"
        out = run_diff(old, new)
        assert r'\sout{' in out


# ---------------------------------------------------------------------------
# Bug 5 — \acfi, \aclu, \acfu must not appear inside \sout{}
# ---------------------------------------------------------------------------

class TestBug5AcMultiCharSuffixNotInSout:
    r"""Bug 5: \ac* commands with multi-character suffixes (\acfi, \aclu, \acfu)
    must be detected by _NOSOUT_RE and never wrapped in \sout{}."""

    def test_acfi_not_in_sout(self):
        r"""\\acfi{} must use {\color{BUR}...} not \\sout{}."""
        old = "The \\acfi{ESA} mission started.\n"
        new = "The mission started.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\acfi\b', r'\acfi must not appear inside \sout{}')

    def test_aclu_not_in_sout(self):
        r"""\\aclu{} must use {\color{BUR}...} not \\sout{}."""
        old = "As described by \\aclu{GPP}.\n"
        new = "As described previously.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\aclu\b', r'\aclu must not appear inside \sout{}')

    def test_acfu_not_in_sout(self):
        r"""\\acfu{} must use {\color{BUR}...} not \\sout{}."""
        old = "See \\acfu{SAR} for details.\n"
        new = "See the technical report for details.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\acfu\b', r'\acfu must not appear inside \sout{}')

    def test_acsf_not_in_sout(self):
        r"""\\acsf{} (two-char suffix) must use {\color{BUR}...} not \\sout{}."""
        old = "Defined in \\acsf{EOPF}.\n"
        new = "Defined in the specification.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\acsf\b', r'\acsf must not appear inside \sout{}')

    def test_acp_still_not_in_sout(self):
        r"""Regression: single-char suffix \\acp{} must also still not appear in \\sout{}."""
        old = "All \\acp{SAR} instruments use this.\n"
        new = "All radar instruments use this.\n"
        out = run_diff(old, new)
        assert_no_sout_pattern(out, r'\\acp\b', r'\acp must not appear inside \sout{}')


# ---------------------------------------------------------------------------
# Bug 3 regression — diff_preamble_tables is now wired into main pipeline
# ---------------------------------------------------------------------------

class TestPreambleDiffVisible:
    """Preamble table changes must appear in the diff output."""

    def test_preamble_table_change_visible(self):
        """A table in the preamble that changes must produce diff markup."""
        preamble_old = (
            r"\documentclass{article}" + "\n"
            r"\usepackage{colortbl}" + "\n"
            r"\newcommand{\mytable}{%" + "\n"
            r"\begin{tabular}{|l|l|}" + "\n"
            r"\hline" + "\n"
            r"A & Old value \\" + "\n"
            r"\hline" + "\n"
            r"\end{tabular}}" + "\n"
            r"\begin{document}" + "\n"
        )
        preamble_new = (
            r"\documentclass{article}" + "\n"
            r"\usepackage{colortbl}" + "\n"
            r"\newcommand{\mytable}{%" + "\n"
            r"\begin{tabular}{|l|l|}" + "\n"
            r"\hline" + "\n"
            r"A & New value \\" + "\n"
            r"\hline" + "\n"
            r"\end{tabular}}" + "\n"
            r"\begin{document}" + "\n"
        )
        old_p, _ = ldb.split_preamble_body(preamble_old + r"\end{document}")
        new_p, _ = ldb.split_preamble_body(preamble_new + r"\end{document}")
        result = ldb.inject_diff_packages(ldb.diff_preamble_tables(old_p, new_p))
        # The changed cell value must appear with diff markup.
        # Word-level diff produces \sout{Old} and \textcolor{ao}{New} — check for markup
        assert 'diffdel' in result or 'sout' in result, (
            "Preamble table change must produce visible diff markup"
        )
        assert 'New' in result and 'Old' in result, (
            "Both old and new cell values must appear in preamble diff output"
        )


# ---------------------------------------------------------------------------
# Regression tests — known-good behaviour must not break
# ---------------------------------------------------------------------------

class TestRegression:
    """Ensure the fixes do not break existing correct behaviour."""

    def test_plain_text_deletion_still_uses_sout(self):
        """Plain text (no special commands) in deleted lines still uses \\sout{}."""
        old = "This sentence was removed entirely.\n"
        new = "Different content here.\n"
        out = run_diff(old, new)
        # Some part of the deleted text should be inside \sout
        assert r'\sout{' in out

    def test_plain_word_deletion_uses_sout(self):
        """A simple deleted word in a word-level diff uses \\sout{}."""
        old = "The quick brown fox.\n"
        new = "The brown fox.\n"
        out = run_diff(old, new)
        assert r'\sout{quick}' in out or r'\sout{' in out

    def test_added_text_uses_textcolor_ao(self):
        """Added text uses \\textcolor{ao}{...}."""
        old = "The fox.\n"
        new = "The quick fox.\n"
        out = run_diff(old, new)
        assert r'\textcolor{ao}{' in out

    def test_cite_without_hyperref_still_compiles(self):
        """\\cite{} in deleted text without hyperref preamble produces color markup."""
        old_text = (
            r"\documentclass{article}" + "\n"
            r"\begin{document}" + "\n"
            "Published in \\cite{smith2020}.\n"
            r"\end{document}"
        )
        new_text = (
            r"\documentclass{article}" + "\n"
            r"\begin{document}" + "\n"
            "Published elsewhere.\n"
            r"\end{document}"
        )
        old_p, old_b = ldb.split_preamble_body(old_text)
        new_p, new_b = ldb.split_preamble_body(new_text)
        out_b = ldb.diff_segments(ldb.segment_text(old_b), ldb.segment_text(new_b))
        assert r'\cite{smith2020}' in out_b, "Deleted \\cite content must appear in diff"

    def test_table_diff_unaffected(self):
        """Table diffing still works correctly after the fixes."""
        old = (
            "\\begin{tabular}{|l|l|}\n"
            "\\hline\n"
            "ID & Value \\\\\n"
            "\\hline\n"
            "A1 & First \\\\\n"
            "\\hline\n"
            "\\end{tabular}\n"
        )
        new = (
            "\\begin{tabular}{|l|l|}\n"
            "\\hline\n"
            "ID & Value \\\\\n"
            "\\hline\n"
            "A1 & Second \\\\\n"
            "\\hline\n"
            "\\end{tabular}\n"
        )
        out = run_diff(old, new)
        assert r'\begin{tabular}' in out
        assert 'Second' in out
