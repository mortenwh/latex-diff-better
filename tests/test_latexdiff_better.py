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


# ---------------------------------------------------------------------------
# Bug 6 — parse_table_rows / split_cells must not split inside brace groups
# ---------------------------------------------------------------------------

class TestBug6BraceAwareSplitting:
    r"""Bug 6: \\ inside \makecell{...\\ ...} (or any braced argument) must
    not be treated as a table row terminator.  Likewise, & inside a brace
    group must not be treated as a cell separator.

    Root cause: parse_table_rows() used a plain regex to split on all \\
    tokens, and split_cells() used re.split(r'(?<!\\)&', body).  Neither
    respected brace depth, so \makecell{A \\ B} got split into two fragments
    with unbalanced braces, producing LaTeX compilation errors.
    """

    # -----------------------------------------------------------------------
    # Shared fixtures
    # -----------------------------------------------------------------------

    SIMPLE_TABLE = (
        r"\begin{tabular}{ll}" + "\n"
        r"\makecell{A \\ B} & Col2 \\" + "\n"
        r"Row2 & Data \\" + "\n"
        r"\end{tabular}"
    )

    REAL_TABLE = (
        r"\begin{tabular}{lll}" + "\n"
        r"\toprule" + "\n"
        r"\textbf{Active Sensor} & "
        r"\multicolumn{2}{r}{\makecell[l]{\textbf{Wind} \\ \textbf{Source}}} \\" + "\n"
        r"\midrule" + "\n"
        r"ALOS & ASCAT & Ref \\" + "\n"
        r"\bottomrule" + "\n"
        r"\end{tabular}"
    )

    # -----------------------------------------------------------------------
    # parse_table_rows unit tests
    # -----------------------------------------------------------------------

    def test_makecell_not_split_row_count(self):
        r"""\\ inside \makecell{} must not create extra rows."""
        _, rows, _, _ = ldb.parse_table_rows(self.SIMPLE_TABLE)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 rows, got {len(data_rows)}: {data_rows!r}"
        )

    def test_makecell_rows_brace_balanced(self):
        r"""Every row from parse_table_rows must have balanced braces."""
        _, rows, _, _ = ldb.parse_table_rows(self.SIMPLE_TABLE)
        for r in rows:
            assert ldb._brace_balanced(r), (
                f"Row has unbalanced braces: {r!r}"
            )

    def test_makecell_no_row_starts_with_closing_brace(self):
        r"""No row should start with 'B}' — a sign that \\ inside \makecell was a split point."""
        _, rows, _, _ = ldb.parse_table_rows(self.SIMPLE_TABLE)
        for r in rows:
            assert not r.strip().startswith('B}'), (
                f"Row starts with 'B}}' indicating \\\\ inside \\makecell was used "
                f"as row separator: {r!r}"
            )

    def test_multicolumn_makecell_not_split(self):
        r"""\\ inside \multicolumn arg with \makecell must not split the row."""
        table = (
            r"\begin{tabular}{lll}" + "\n"
            r"\multicolumn{2}{r}{\makecell[l]{Wind \\ Source}} & Extra \\" + "\n"
            r"Row2 & Data & More \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 rows, got {len(data_rows)}: {data_rows!r}"
        )
        assert r'\makecell[l]{Wind \\ Source}' in data_rows[0], (
            f"\\makecell content split across rows. First row: {data_rows[0]!r}"
        )

    def test_parbox_line_break_not_split(self):
        r"""\\ inside \parbox must not split the row."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"\parbox{3cm}{Line1 \\ Line2} & B \\" + "\n"
            r"C & D \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 data rows, got {len(data_rows)}: {data_rows!r}"
        )
        for r in data_rows:
            assert ldb._brace_balanced(r), f"Unbalanced braces in row: {r!r}"

    def test_shortstack_line_break_not_split(self):
        r"""\\ inside \shortstack must not split the row."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"\shortstack{A \\ B} & Col2 \\" + "\n"
            r"Row2 & Data \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 data rows, got {len(data_rows)}: {data_rows!r}"
        )

    def test_nested_braces_not_split(self):
        r"""\\ inside nested braces \textbf{\makecell{A \\ B}} must not split the row."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"\textbf{\makecell{A \\ B}} & Col2 \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 1, (
            f"Expected 1 data row, got {len(data_rows)}: {data_rows!r}"
        )
        assert ldb._brace_balanced(data_rows[0]), (
            f"Row must have balanced braces: {data_rows[0]!r}"
        )

    def test_row_sep_at_depth0_is_split(self):
        r"""\\ at brace depth 0 IS a row separator (normal case preserved)."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"A & B \\" + "\n"
            r"C & D \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 data rows, got {len(data_rows)}: {data_rows!r}"
        )

    def test_row_sep_with_height_preserved(self):
        r"""\\[5pt] at brace depth 0 is a row separator with height (preserved)."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"A & B \\[5pt]" + "\n"
            r"C & D \\" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if r.strip()]
        assert len(data_rows) == 2, (
            f"Expected 2 data rows, got {len(data_rows)}: {data_rows!r}"
        )
        assert r'\\[5pt]' in data_rows[0], (
            f"Row height adjustment \\\\[5pt] must be preserved: {data_rows[0]!r}"
        )

    def test_mixed_table_correct_row_count(self):
        r"""Table with \makecell rows and plain rows has correct row count."""
        table = (
            r"\begin{tabular}{ll}" + "\n"
            r"\toprule" + "\n"
            r"\makecell{H1 \\ Sub1} & \makecell{H2 \\ Sub2} \\" + "\n"
            r"\midrule" + "\n"
            r"Plain A & Plain B \\" + "\n"
            r"\makecell{Multi \\ Line} & Value \\" + "\n"
            r"\bottomrule" + "\n"
            r"\end{tabular}"
        )
        _, rows, _, _ = ldb.parse_table_rows(table)
        data_rows = [r for r in rows if '&' in r]
        assert len(data_rows) == 3, (
            f"Expected 3 data rows, got {len(data_rows)}: {data_rows!r}"
        )
        for r in rows:
            assert ldb._brace_balanced(r), f"Row has unbalanced braces: {r!r}"

    # -----------------------------------------------------------------------
    # split_cells unit tests
    # -----------------------------------------------------------------------

    def test_split_cells_normal(self):
        """Normal & at depth 0 splits cells correctly."""
        row = r"A & B & C \\"
        cells = ldb.split_cells(row)
        assert len(cells) == 3, f"Expected 3 cells, got {cells!r}"
        assert cells[0].strip() == 'A'
        assert cells[1].strip() == 'B'
        assert cells[2].strip() == 'C'

    def test_split_cells_escaped_amp_regression(self):
        r"""Escaped \& must not be treated as a cell separator."""
        row = r"Price: 10\,\$ \& 20\,\$ & Value \\"
        cells = ldb.split_cells(row)
        assert len(cells) == 2, (
            f"Expected 2 cells (\\& is not a separator), got {cells!r}"
        )

    def test_split_cells_amp_inside_braces(self):
        r"""& inside a brace group must not split cells."""
        row = r"\multicolumn{2}{r}{\mbox{A & B}} & Last \\"
        cells = ldb.split_cells(row)
        assert len(cells) == 2, (
            f"Expected 2 cells (& inside braces is not a separator), got {len(cells)}: {cells!r}"
        )

    # -----------------------------------------------------------------------
    # render_added_row / render_deleted_row unit tests
    # -----------------------------------------------------------------------

    def test_render_added_row_makecell_balanced(self):
        r"""render_added_row must produce balanced braces on a row with \makecell."""
        row = r"\makecell{Wind \\ Source} & Value \\"
        result = ldb.render_added_row(row)
        assert ldb._brace_balanced(result), (
            f"render_added_row output has unbalanced braces: {result!r}"
        )

    def test_render_added_row_multicolumn_makecell_balanced(self):
        r"""render_added_row on \multicolumn+\makecell must produce balanced braces."""
        row = (
            r"\multicolumn{2}{r}{\makecell[l]{\textbf{Wind} \\ \textbf{Source}}}"
            r" & Extra \\"
        )
        result = ldb.render_added_row(row)
        assert ldb._brace_balanced(result), (
            f"Output has unbalanced braces: {result!r}"
        )
        assert r'\makecell[l]{' in result, (
            f"\\makecell was removed or corrupted: {result!r}"
        )

    def test_render_deleted_row_makecell_balanced(self):
        r"""render_deleted_row must produce balanced braces on a row with \makecell."""
        row = r"\makecell{A \\ B} & Value \\"
        cells = ldb.split_cells(row)
        n_cols = 2
        trailing = r"\\"
        result = ldb.render_deleted_row(cells, n_cols, trailing)
        assert ldb._brace_balanced(result), (
            f"render_deleted_row output has unbalanced braces: {result!r}"
        )

    # -----------------------------------------------------------------------
    # wrap_table_added / wrap_table_deleted integration tests
    # -----------------------------------------------------------------------

    def test_wrap_table_added_balanced_braces(self):
        r"""wrap_table_added on a table with \makecell multi-line header → balanced braces."""
        result = ldb.wrap_table_added(self.REAL_TABLE)
        assert ldb._brace_balanced(result), (
            f"wrap_table_added output has unbalanced braces: {result!r}"
        )

    def test_wrap_table_added_cellcolor_not_inside_makecell(self):
        r"""wrap_table_added must not inject \cellcolor inside \makecell content."""
        result = ldb.wrap_table_added(self.REAL_TABLE)
        # If \cellcolor appears between \makecell{ and the matching }, that is a bug.
        # Simple regression check: the broken pattern from the bug report must not appear.
        assert r'\cellcolor{diffadd}\textbf{Source}' not in result, (
            r"\cellcolor was incorrectly injected as a continuation of \makecell content"
        )

    def test_wrap_table_deleted_balanced_braces(self):
        r"""wrap_table_deleted on a table with \makecell multi-line header → balanced braces."""
        result = ldb.wrap_table_deleted(self.REAL_TABLE)
        assert ldb._brace_balanced(result), (
            f"wrap_table_deleted output has unbalanced braces: {result!r}"
        )

    # -----------------------------------------------------------------------
    # Full diff pipeline integration tests
    # -----------------------------------------------------------------------

    def _make_table_doc(self, table_body):
        preamble = (
            r"\documentclass{article}" + "\n"
            r"\usepackage{tabularx}" + "\n"
            r"\usepackage{booktabs}" + "\n"
            r"\usepackage{makecell}" + "\n"
            r"\begin{document}" + "\n"
        )
        return preamble + table_body + "\n" + r"\end{document}"

    def test_diff_pipeline_added_table_with_makecell(self):
        r"""Full diff: added table with \makecell{...\\ ...} → balanced braces in output."""
        old_text = self._make_table_doc("")
        new_text = self._make_table_doc(self.REAL_TABLE)
        old_p, old_b = ldb.split_preamble_body(old_text)
        new_p, new_b = ldb.split_preamble_body(new_text)
        out_p = ldb.inject_diff_packages(new_p)
        out_body = ldb.diff_segments(ldb.segment_text(old_b), ldb.segment_text(new_b))
        output = out_p + out_body
        assert ldb._brace_balanced(output), (
            "Full diff output has unbalanced braces for added table with \\makecell"
        )

    def test_diff_pipeline_deleted_table_with_makecell(self):
        r"""Full diff: deleted table with \makecell{...\\ ...} → balanced braces in output."""
        old_text = self._make_table_doc(self.REAL_TABLE)
        new_text = self._make_table_doc("")
        old_p, old_b = ldb.split_preamble_body(old_text)
        new_p, new_b = ldb.split_preamble_body(new_text)
        out_p = ldb.inject_diff_packages(new_p)
        out_body = ldb.diff_segments(ldb.segment_text(old_b), ldb.segment_text(new_b))
        output = out_p + out_body
        assert ldb._brace_balanced(output), (
            "Full diff output has unbalanced braces for deleted table with \\makecell"
        )
