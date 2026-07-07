#!/usr/bin/env python3
"""Better LaTeX diff with proper table, structure, and cell handling.

The standard latexdiff Perl script fails with table environments because
DIFadd/DIFdel commands cannot span across & cell separators or row endings.
This script handles tables with cell-level coloring via colortbl and avoids
putting sout around structural LaTeX commands.

Usage (two files):
    python3 latexdiff_better.py old.tex new.tex output.tex

Usage (git mode — multi-file document, run from within the repo):
    python3 latexdiff_better.py --git <old_commit> <main.tex> output.tex

Usage (git mode — multi-file document, explicit repo dir):
    python3 latexdiff_better.py --git <repo_dir> <old_commit> <main.tex> output.tex

    In git mode the script checks out <main.tex> (and all its \\include'd
    sub-files) at <old_commit>, flattens both old and new versions into a
    single in-memory string, then runs the normal diff pipeline.

Architecture overview
---------------------
1. Flattening (git mode only)
   \\include / \\input directives are recursively expanded into a single
   in-memory string for each version, reading files either from disk (new)
   or from a git commit (old).

2. CSV expansion (git mode only)
   \\csvlongtable, \\csvlongtbd and \\csvlongtrace commands are replaced by
   inline xltabular environments so the diff pipeline can compare individual
   rows and cells rather than seeing the whole table as a single blob.

3. Segmentation
   The document body (after \\begin{document}) is split into alternating
   ('text', ...) and ('table', ...) segments.  Table environments detected:
   tabular, tabularx, tabular*, xltabular, longtable, array.

4. Segment-level diff (diff_segments)
   difflib.SequenceMatcher is run on whitespace-normalised segment keys.
   Matched table pairs → diff_tables; matched text pairs → diff_text_block;
   unmatched tables → wrap_table_added / wrap_table_deleted.

5. Table diff (diff_tables)
   SequenceMatcher on row keys (whitespace-normalised).
   Equal rows pass through unchanged.
   Inserted rows get \\rowcolor{diffadd}.
   Deleted rows get \\rowcolor{diffdel} + per-cell \\sout{} / \\color{BUR}.
   Changed rows with equal column count get per-cell inline word diff.

6. Cell diff (diff_cells_inline)
   SequenceMatcher on whitespace-separated tokens.
   Inserted tokens → \\textcolor{ao}{...}
   Deleted tokens  → \\textcolor{BUR}{\\sout{...}} or {\\color{BUR}...}

7. Text diff (diff_text_block / diff_words_in_line)
   Line-level SequenceMatcher; word-level diff within matched line pairs.
   Structural commands (\\begin, \\end, \\item, …) and lines with unbalanced
   braces fall back to safe markup (comments for deletions, plain text for
   additions) so the output is always compilable.

8. Preamble handling
   The new preamble is used as-is with two injections: ulem+colortbl packages
   and colour definitions (diffadd, diffdel, ao, BUR).

Colour coding in the output PDF
--------------------------------
  Green background  (\\rowcolor{diffadd})         – row added
  Pink  background  (\\rowcolor{diffdel})         – row deleted
  Neutral background (diffdel!50!diffadd!50)      – row changed (cell-level diff)
  Green text  \\textcolor{ao}{...}                – text added
  Red+sout    \\textcolor{BUR}{\\sout{...}}        – text deleted (simple)
  Red (no sout)  {\\color{BUR}...}               – text deleted (complex LaTeX content)
  % DIFF-DEL: ...                                 – deleted line that cannot be safely
                                                    coloured (structural or unbalanced)

Limitations
-----------
- Tables that moved between sections may show as separate all-red + all-green
  rather than a unified row diff.
- The preamble is taken from the new version; preamble changes are not shown.
- \\sout{} cannot contain \\begin/\\end, optional args [..], \\newline, \\par,
  or & (in table context) — these fall back to {\\color{BUR}...}.
"""

import re
import sys
import difflib
import os
import subprocess


# ---------------------------------------------------------------------------
# Markup helpers
# ---------------------------------------------------------------------------

DIFF_PACKAGE_LINES = r"""\usepackage{ulem}
\normalem
\usepackage{colortbl}
"""

DIFF_COLORS = r"""% --- diff colour definitions ---
\definecolor{diffadd}{RGB}{198,239,206}
\definecolor{diffdel}{RGB}{255,199,206}
% Provide ao (green) and BUR (red) in case the source document does not define them.
\makeatletter
\@ifundefined{color@ao}{\definecolor{ao}{rgb}{0.0,0.5,0.0}}{}
\@ifundefined{color@BUR}{\definecolor{BUR}{rgb}{0.8,0.0,0.0}}{}
\makeatother
"""

# Structural LaTeX commands that must NOT be wrapped in \sout{}
_STRUCTURAL_RE = re.compile(
    r'\\(section\*?|subsection\*?|subsubsection\*?|paragraph\*?|chapter\*?'
    r'|begin|end|newpage|clearpage|appendix'
    r'|newcommand|renewcommand|providecommand'
    r'|setcounter|addtocounter|def)\b'
)

# Matches a section-type command with its title argument, e.g. \subsection{4.7 ROSS}
_SECTION_HEADING_RE = re.compile(
    r'\\(chapter|section|subsection|subsubsection|paragraph)\*?\{(.+)\}',
    re.DOTALL,
)

# Commands that ulem's \sout cannot handle safely:
#   - Commands with optional [...] args (\cmd[...]) — ulem misparses [ as its own optional arg
#   - Verbatim-style commands (different lexical mode)
#   - Explicit line/paragraph breaks (interrupt \sout's horizontal-mode scan)
#   - Commands that expand into PDF hyperlinks when hyperref is loaded — \cite*, \ac*,
#     \gls*, \href, \url, \autoref, \nameref, \cref — because the hyperlink wrappers
#     (\hyper@natlinkstart / \hyper@natlinkend) change PDF mode, which is incompatible
#     with ulem's horizontal-mode box scanning. \url also changes catcodes (verbatim
#     mode). All of these cause "Extra }, or forgotten \endgroup" / "Missing } inserted"
#     errors when wrapped inside \sout{}.
#     The \ac*/\Ac*/\AC* family uses [a-zA-Z]* to catch all multi-char suffixes
#     (\acfi, \aclu, \acfu, \acsf, …).
# Note: plain \textbf{}, \ref{}, \label{} etc. work fine inside \sout.
_NOSOUT_RE = re.compile(
    r'\\[a-zA-Z]+\['            # \cmd[...] — optional arg confuses ulem
    r'|\\includegraphics\b'     # always has optional args in practice
    r'|\\verb\b|\\lstinline\b'  # verbatim
    r'|\\newline\b|\\par\b'     # line/paragraph breaks inside \sout cause errors
    r'|\\\\'                    # explicit \\ line break
    # Hyperref-linked / catcode-changing commands — incompatible with \sout when
    # hyperref is loaded (all four esa-* repos and most modern LaTeX docs use hyperref):
    r'|\\url\b'                 # verbatim URL — catcode changes break ulem scanning
    r'|\\href\b'                # hyperref link — PDF-mode wrapper
    r'|\\cite[a-z]*\b'          # \cite, \citep, \citet, \citealp, etc.
    r'|\\[aA][cC][a-zA-Z]*\b'  # \ac, \acp, \acl, \acf, \acfi, \aclu, \acfu, \Ac, \AC, etc.
    r'|\\[gG][lL][sS][a-zA-Z]*\b'  # \gls, \Gls, \GLS, \glspl, \glstext, etc.
    r'|\\(?:name|auto|c)ref\b'  # \nameref, \autoref, \cref — hyperref cross-references
)

# Lines that must ALWAYS be output as ``% DIFF-DEL: ...`` comments rather than
# wrapped in {\color{}} or \sout{}.  Executing these outside their required
# parent environment causes fatal LaTeX errors:
#   - \begin / \end — would open/close real environments in the wrong place
#   - \item — needs its enclosing list environment
#   - section commands — would add numbered headings / shift numbering
#   - TikZ picture commands — require an active tikzpicture environment
#   - algorithmic / algorithm2e commands — require an active algorithmic env
#   - acronym / glossaries list-entry commands — must be inside their env
_COMMENT_DEL_RE = re.compile(
    r'\\begin\{|\\end\{|\\item\b'
    r'|\\chapter\*?\{|\\section\*?\{|\\subsection\*?\{'
    r'|\\subsubsection\*?\{|\\paragraph\*?\{'
    # TikZ picture commands (must be inside tikzpicture)
    r'|\\node\b|\\coordinate\b|\\path\b|\\draw\b|\\fill\b|\\filldraw\b'
    r'|\\clip\b|\\shade\b|\\tikzset\b|\\tikzstyle\b'
    # algorithmic / algorithm2e commands (must be inside algorithmic env)
    r'|\\STATE\b|\\IF\b|\\ELSE\b|\\ELSIF\b|\\ENDIF\b'
    r'|\\FOR\b|\\FORALL\b|\\WHILE\b|\\REPEAT\b|\\UNTIL\b'
    r'|\\LOOP\b|\\RETURN\b|\\REQUIRE\b|\\ENSURE\b'
    r'|\\PROCEDURE\b|\\FUNCTION\b|\\ENDPROCEDURE\b|\\ENDFUNCTION\b'
    # float-specific commands (must be inside a figure/table float)
    r'|\\caption\b|\\subcaption\b|\\captionof\b'
    # acronym / glossaries list-entry commands (must be inside their environment)
    r'|\\acro\b|\\acrodef\b|\\newacronym\b|\\newglossaryentry\b'
    # bibliography commands — write \bibstyle/\bibdata to .aux; executing both
    # old and new versions causes duplicate entries that make bibtex abort with
    # "Illegal, another \bibstyle command".  Deleted versions must be comments;
    # added/unchanged versions must pass through as-is (no colour wrapping).
    r'|\\bibliographystyle\b|\\bibliography\b|\\addbibresource\b',
)


def is_structural(text):
    """Return True if text contains a structural LaTeX command (\\begin, \\end, \\section…)."""
    return bool(_STRUCTURAL_RE.search(text))


def _section_rename_note(old_line):
    """Return a small LaTeX annotation showing the old section title, or '' if not applicable.

    Used to make section renames and removals visible in the diff PDF.  The
    annotation is rendered as a small red italic note after the new heading so
    the reader can see what the previous title was.
    """
    m = _SECTION_HEADING_RE.search(old_line.strip())
    if not m or not m.group(2).strip():
        return ''
    old_title = m.group(2).strip()
    return r'{\color{BUR}\footnotesize\textit{[was: ' + old_title + r']}}\par' + '\n'


def add_markup(text):
    """Wrap text in green colour markup for additions (\\textcolor{ao}{}).

    Handles trailing LaTeX % comments correctly: the closing brace is placed
    before the % so it is not swallowed into the comment.

    When the entire text is a LaTeX comment (e.g. "% note"), the text is
    returned as-is: a comment added in the new version has no visible content
    to colour and wrapping it would produce \\textcolor{ao}{}%..., which
    comments out any markup following it on the same output line.
    """
    m = re.search(r'(?<!\\)%', text)
    if m:
        before = text[:m.start()]
        if not before.strip():
            # Entire content is a comment — pass through without colour markup
            return text
        return r'\textcolor{ao}{' + before + '}' + text[m.start():]
    return r'\textcolor{ao}{' + text + '}'


def del_markup(text):
    """Wrap text in red delete markup.

    Uses \\textcolor{BUR}{\\sout{}} for plain text so the deletion is shown
    with red colour AND strikethrough.  Falls back to {\\color{BUR}...} (red
    colour only, no strikethrough) when the text contains structural commands
    or macros with arguments that ulem's \\sout cannot handle safely.

    Trailing LaTeX % comments are moved outside the closing brace so they are
    not accidentally swallowed into the comment.
    """
    m = re.search(r'(?<!\\)%', text)
    comment_suffix = ''
    if m:
        comment_suffix = text[m.start():]
        text = text[:m.start()]
    if is_structural(text) or _NOSOUT_RE.search(text):
        return r'{\color{BUR}' + text + '}' + comment_suffix
    return r'\textcolor{BUR}{\sout{' + text.rstrip() + '}}' + comment_suffix


# ---------------------------------------------------------------------------
# Table begin-tag parsing (handles nested braces in column specs)
# ---------------------------------------------------------------------------

def match_brace_group(text, pos):
    """Return (start, end+1) of a balanced {…} group starting at pos, or None."""
    if pos >= len(text) or text[pos] != '{':
        return None
    depth = 0
    i = pos
    while i < len(text):
        c = text[i]
        if c == '\\':
            i += 2  # skip escaped character
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth == 0:
                return (pos, i + 1)
        i += 1
    return None


def parse_begin_tag(text):
    """
    Parse the \\begin{env}{opt1}[opt2]{opt3} header at the start of text.
    Returns (begin_tag_str, body_str).
    """
    m = re.match(r'\\begin\{([^}]+)\}', text)
    if not m:
        return '', text

    pos = m.end()
    begin_tag = m.group(0)

    # Consume all optional and required arguments (alternating {} and [])
    for _ in range(6):  # at most 6 extra argument groups
        while pos < len(text) and text[pos] in ' \t\n':
            pos += 1
        if pos >= len(text):
            break
        if text[pos] == '{':
            grp = match_brace_group(text, pos)
            if grp:
                begin_tag += text[grp[0]:grp[1]]
                pos = grp[1]
            else:
                break
        elif text[pos] == '[':
            end = text.find(']', pos)
            if end >= 0:
                begin_tag += text[pos:end + 1]
                pos = end + 1
            else:
                break
        else:
            break

    return begin_tag, text[pos:]


def parse_end_tag(text, env_name):
    """Find the LAST \\end{env_name} in text and split around it.

    Returns (body, end_tag) where body is everything before the last \\end
    and end_tag is the \\end{...} string itself.  Using the LAST occurrence
    correctly handles the case where the environment body contains nested
    instances of the same environment name.
    """
    pattern = re.compile(r'\\end\{' + re.escape(env_name) + r'\}')
    matches = list(pattern.finditer(text))
    if not matches:
        return text, ''
    last = matches[-1]
    return text[:last.start()], last.group(0)


# ---------------------------------------------------------------------------
# File segmentation: table environments vs plain text
# ---------------------------------------------------------------------------

TABLE_ENV_NAMES = ('tabular', 'tabularx', 'tabular*', 'xltabular', 'longtable', 'array')
TABLE_BEGIN_RE = re.compile(
    r'\\begin\{(tabular[x*]?|xltabular|longtable|array)\}',
    re.IGNORECASE,
)


def _pos_in_comment(text, pos):
    """Return True if pos falls inside a LaTeX line comment (unescaped % earlier on same line)."""
    line_start = text.rfind('\n', 0, pos) + 1
    i = line_start
    while i < pos:
        c = text[i]
        if c == '\\':
            i += 2  # skip the escaped character (e.g. \%)
            continue
        if c == '%':
            return True
        i += 1
    return False


def find_table_spans(text):
    """Return sorted, non-overlapping (start, end) character spans of table environments.

    Tracks nesting depth so that a tabular inside a tabular is not reported as
    a separate span — only the outermost environment boundary is returned.
    Environments detected: tabular, tabularx, tabular*, xltabular, longtable, array.

    LaTeX line comments (% …) are skipped so that commented-out \\begin/\\end
    commands are not counted as real environment delimiters.
    """
    spans = []
    for m in TABLE_BEGIN_RE.finditer(text):
        env_name = m.group(1)
        # Skip \begin{...} that is itself inside a comment
        if _pos_in_comment(text, m.start()):
            continue
        # Find matching \end{env_name} with proper depth tracking
        depth = 0
        i = m.start()
        while i < len(text):
            c = text[i]
            # Skip rest of line when an unescaped % is encountered
            if c == '%' and (i == 0 or text[i - 1] != '\\'):
                nl = text.find('\n', i)
                i = nl + 1 if nl >= 0 else len(text)
                continue
            sm = re.match(r'\\begin\{' + re.escape(env_name) + r'\}', text[i:])
            em = re.match(r'\\end\{' + re.escape(env_name) + r'\}', text[i:])
            if sm:
                depth += 1
                i += sm.end()
            elif em:
                depth -= 1
                if depth == 0:
                    end = i + em.end()
                    spans.append((m.start(), end))
                    break
                i += em.end()
            else:
                i += 1
    # Remove nested spans (keep outermost)
    merged = []
    for s, e in sorted(spans):
        if merged and s < merged[-1][1]:
            continue  # skip — already inside a larger span
        merged.append((s, e))
    return merged


def segment_text(text):
    """Split text into alternating ('text', str) and ('table', str) segments.

    Every character of text appears in exactly one segment.  Table segments
    contain the full \\begin{...}...\\end{...} environment string; text segments
    contain everything in between.
    """
    spans = find_table_spans(text)
    segments = []
    pos = 0
    for s, e in spans:
        if pos < s:
            segments.append(('text', text[pos:s]))
        segments.append(('table', text[s:e]))
        pos = e
    if pos < len(text):
        segments.append(('text', text[pos:]))
    return segments


# ---------------------------------------------------------------------------
# Row and cell parsing
# ---------------------------------------------------------------------------

def _split_brace_aware(text, sep_char):
    r"""Split *text* at *sep_char* characters that are at brace depth 0.

    Escaped characters (preceded by \) and any character inside a brace
    group {…} are never treated as separators.  This prevents & and \\
    tokens inside \makecell{}, \parbox{}, \multicolumn args, etc. from
    being mistaken for cell or row separators.
    """
    parts = []
    current = []
    depth = 0
    i = 0
    n = len(text)
    while i < n:
        c = text[i]
        if c == '\\':
            # Skip the next character unconditionally (escape sequence).
            current.append(c)
            if i + 1 < n:
                current.append(text[i + 1])
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        elif c == sep_char and depth == 0:
            parts.append(''.join(current))
            current = []
            i += 1
            continue
        current.append(c)
        i += 1
    parts.append(''.join(current))
    return parts


def split_cells(row_text):
    """Split a table row into individual cell strings.

    Splits on unescaped & only (not \\&), and never splits inside brace
    groups (e.g. inside \\makecell{} or \\multicolumn arguments).  Leading
    structural commands (\\hline, \\endhead, …) are stripped first via
    row_leading() so they do not end up in the first cell.  The trailing
    \\\\ row-end marker and any following \\hline are also removed before
    splitting.
    """
    body = row_text[len(row_leading(row_text)):]
    # Remove trailing \\ (row end marker) and \hline
    body = re.sub(r'(\\\\(?:\[.*?\])?(?:\s*\\hline)*)$', '', body)
    return [c.strip() for c in _split_brace_aware(body, '&')]


def count_cells(row_text):
    """Return the number of cells in a row (= number of unescaped & separators + 1).

    Leading structural commands and the trailing \\\\ marker are stripped before
    counting so they don't contribute spurious & characters.
    """
    body = row_text[len(row_leading(row_text)):]
    body = re.sub(r'(\\\\(?:\[.*?\])?(?:\s*\\hline)*)$', '', body)
    return len(_split_brace_aware(body, '&')) - 1


def row_trailing(row_text):
    r"""Extract the trailing \\ and optional \hline suffix from a row string.

    Returns the matched suffix (e.g. r'\\\\hline') or the default r'\\\hline'
    if no trailing row-end marker is found.  Used to preserve the original
    row terminator when reconstructing modified rows.
    """
    m = re.search(r'(\\\\(?:\[.*?\])?(?:\s*\\hline)*)$', row_text)
    return m.group(1) if m else r'\\\hline'


def is_structural_row(row_text):
    """Return True if the row contains only LaTeX structural commands (no data cells).

    Rows consisting solely of \\hline, booktabs rules (\\toprule, \\midrule,
    \\bottomrule, \\cmidrule, \\specialrule, \\addlinespace), arydshln rules
    (\\Xhline, \\Xcline, \\hdashline, \\cdashline), longtable markers
    (\\endhead, \\endfoot, \\endfirsthead, \\endlastfoot) or whitespace are
    treated as structural — they are passed through unchanged during diffs
    rather than being marked as added/deleted.
    """
    stripped = row_text.strip()
    return bool(re.fullmatch(
        r'(?:'
        r'\\hline'
        r'|\\toprule(?:\[[^\]]*\])?'
        r'|\\midrule(?:\[[^\]]*\])?'
        r'|\\bottomrule(?:\[[^\]]*\])?'
        r'|\\cmidrule(?:\[[^\]]*\])?(?:\([lr]+\))?\{[^}]*\}'
        r'|\\specialrule\{[^}]*\}\{[^}]*\}\{[^}]*\}'
        r'|\\addlinespace(?:\[[^\]]*\])?'
        r'|\\Xhline\{[^}]*\}'
        r'|\\Xcline\{[^}]*\}\{[^}]*\}'
        r'|\\hdashline(?:\[[^\]]*\])?'
        r'|\\cdashline\{[^}]*\}(?:\[[^\]]*\])?'
        r'|\\endhead'
        r'|\\endfoot'
        r'|\\endfirsthead'
        r'|\\endlastfoot'
        r'|\s'
        r')*',
        stripped
    ))


_STRUCT_PREFIX_RE = re.compile(
    r'^(?:\s*(?:'
    r'\\hline'
    r'|\\toprule(?:\[[^\]]*\])?'
    r'|\\midrule(?:\[[^\]]*\])?'
    r'|\\bottomrule(?:\[[^\]]*\])?'
    r'|\\cmidrule(?:\[[^\]]*\])?(?:\([lr]+\))?\{[^}]*\}'
    r'|\\specialrule\{[^}]*\}\{[^}]*\}\{[^}]*\}'
    r'|\\addlinespace(?:\[[^\]]*\])?'
    r'|\\Xhline\{[^}]*\}'
    r'|\\Xcline\{[^}]*\}\{[^}]*\}'
    r'|\\hdashline(?:\[[^\]]*\])?'
    r'|\\cdashline\{[^}]*\}(?:\[[^\]]*\])?'
    r'|\\endhead'
    r'|\\endfoot'
    r'|\\endfirsthead'
    r'|\\endlastfoot'
    r')\s*)*'
)


def row_leading(row_text):
    """Extract the leading structural prefix (\\hline, \\endhead, …) from a row.

    Returns the matched prefix string (may be empty).  This prefix must be
    emitted BEFORE any delete/add markup for the row data because \\hline uses
    \\noalign internally and cannot appear inside \\sout{} or any brace group.
    """
    m = _STRUCT_PREFIX_RE.match(row_text)
    return m.group() if m else ''


def _split_rows_brace_aware(body):
    r"""Split a table body string into rows on \\ tokens at brace depth 0.

    A \\ token that appears inside a brace group — e.g. inside
    \makecell{Wind \\ Speed}, \parbox{2cm}{A \\ B}, or any other braced
    argument — is NOT treated as a row terminator.  Only \\ at depth 0
    (outside all brace groups) terminates a row.

    The separator (including optional \\[dim] height and any trailing
    \hline commands) is attached to the *preceding* row, matching the
    contract of the original regex-based split.
    """
    # Regex for the full row-end token: \\ with optional [dim] and \hline(s)
    row_end_re = re.compile(r'\\\\(?:\[.*?\])?(?:\s*\\hline)*')

    rows = []
    current = []
    depth = 0
    i = 0
    n = len(body)

    while i < n:
        c = body[i]
        if c == '\\':
            if depth == 0 and i + 1 < n and body[i + 1] == '\\':
                # Candidate row terminator — match full token (\\[dim]\hline*)
                m = row_end_re.match(body, i)
                if m:
                    current.append(m.group())
                    rows.append(''.join(current))
                    current = []
                    i = m.end()
                    continue
            # Regular escape sequence: consume two characters unchanged.
            current.append(c)
            if i + 1 < n:
                current.append(body[i + 1])
            i += 2
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
        current.append(c)
        i += 1

    if current:
        rows.append(''.join(current))
    return rows


def parse_table_rows(table_content):
    """
    Parse a table environment into (begin_tag, rows, end_tag, env_name).
    Each row is the raw text including its trailing \\\\.

    Row splitting is brace-depth-aware: \\\\ tokens inside brace groups
    (e.g. inside \\makecell{A \\\\ B} or \\parbox arguments) are NOT
    treated as row terminators.
    """
    m_env = re.match(r'\\begin\{([^}]+)\}', table_content)
    if not m_env:
        return '', [table_content], '', ''
    env_name = m_env.group(1)

    begin_tag, body_and_end = parse_begin_tag(table_content)
    body, end_tag = parse_end_tag(body_and_end, env_name)

    rows = _split_rows_brace_aware(body)

    # Move longtable/xltabular header rows (up to and including \endhead or
    # \endfirsthead) into begin_tag.  This prevents the \endhead marker from
    # appearing as a structural prefix on the first data row, which would cause
    # a duplicate \endhead in the diff output whenever the first data row
    # changes (one from the deleted old row's row_leading, one from the
    # inserted new row).
    endhead_re = re.compile(r'\\endhead|\\endfirsthead')
    header_parts = []
    body_rows = []
    found_endhead = False
    for row in rows:
        if found_endhead:
            body_rows.append(row)
        else:
            prefix = row_leading(row)
            if endhead_re.search(prefix):
                header_parts.append(prefix)
                rest = row[len(prefix):]
                if rest.strip():
                    body_rows.append(rest)
                found_endhead = True
            else:
                header_parts.append(row)
    if found_endhead:
        begin_tag += ''.join(header_parts)
        rows = body_rows

    return begin_tag, rows, end_tag, env_name


# ---------------------------------------------------------------------------
# Table diff
# ---------------------------------------------------------------------------

def _ensure_rowcolor_terminated(rows):
    r"""Ensure every row with \rowcolor ends with \\.

    colortbl's \rowcolor peeks ahead for a \\ row terminator.  The last row
    of a LaTeX table legitimately omits \\, but that causes colortbl to see
    \end{...} instead and raise 'Missing number, treated as zero'.
    """
    out = []
    for r in rows:
        if r'\rowcolor' in r and not re.search(r'\\\\', r):
            r = r + r'\\'
        out.append(r)
    return out


def _del_cell(c):
    """Render a single deleted cell safely."""
    if not c.strip():
        return r'\cellcolor{diffdel}'
    if _NOSOUT_RE.search(c) or not _brace_balanced(c):
        return r'\cellcolor{diffdel}{\color{BUR}' + c + '}'
    return r'\cellcolor{diffdel}\sout{' + c + '}'


def render_deleted_row(old_cells, n_new_cols, trailing):
    """Render an old (deleted) row as pink with per-cell strikethrough.

    If the old row has the same column count as the new table (n_new_cols),
    each cell gets \\cellcolor{diffdel} plus \\sout{} or {\\color{BUR}...}.

    If the column counts differ (table structure changed), all old cells are
    collapsed into a single \\multicolumn spanning n_new_cols columns.  Cells
    are joined with ' \\& ' (LaTeX escaped ampersand = literal & in text mode)
    so the & characters are not interpreted as column separators.
    """
    if len(old_cells) == n_new_cols:
        del_cells = [_del_cell(c) for c in old_cells]
        return ' & '.join(del_cells) + trailing
    # Column count mismatch: collapse old cells using \& (literal & in text)
    combined = r' \& '.join(old_cells)
    inner = (r'\cellcolor{diffdel}\sout{' + combined + r'}'
             if not _NOSOUT_RE.search(combined) and _brace_balanced(combined)
             else r'\cellcolor{diffdel}{\color{BUR}' + combined + r'}')
    mcol = r'\multicolumn{' + str(max(n_new_cols, 1)) + r'}{|l|}{' + inner + '}'
    return mcol + trailing


def render_added_row(row):
    """Render an added row with green per-cell background.

    Uses \\cellcolor{diffadd} on each cell rather than \\rowcolor{diffadd} to
    avoid the colortbl + tabularx incompatibility: \\rowcolor uses \\noalign /
    \\aftergroup which fires during tabularx's column-width measurement passes
    and causes 'Missing number, treated as zero' at \\end{tabularx}.

    Handles rows that contain full-line comments followed by structural
    commands (e.g. ``% comment\\n\\hline\\nmulticolumn{...}``): the comment
    lines are stripped so that \\cellcolor is not placed before a ``%`` that
    would comment out the trailing ``\\\\``, and any embedded \\hline commands
    are emitted as structural markup before the cell content.
    """
    prefix = row_leading(row)
    rest = row[len(prefix):]
    trailing = row_trailing(rest) or r'\\'
    content = rest[:-len(trailing)] if trailing else rest

    # Strip full-line comments (lines that are entirely a LaTeX comment).
    # This prevents \cellcolor being placed before a "% ..." that would
    # comment out the rest of the line, including the trailing \\.
    content_stripped = re.sub(r'(?m)^[ \t]*%[^\n]*\n?', '', content)

    # After stripping comments, structural commands (e.g. \hline) that were
    # buried after the comment line may now be at the front.
    inner_m = _STRUCT_PREFIX_RE.match(content_stripped)
    inner_prefix = inner_m.group() if inner_m else ''
    cell_content = content_stripped[len(inner_prefix):].strip()

    if not cell_content:
        # Only comments and structural commands — pass through unchanged.
        return row

    cells = split_cells(cell_content)
    # \cellcolor must NOT precede \multicolumn: in colortbl, \cellcolor is placed
    # inside the cell template, but \multicolumn replaces the template via \omit,
    # causing "Misplaced \omit" errors in tabularx/xltabular.  For cells that
    # start with \multicolumn, apply \textcolor to the content inside instead.
    def _color_cell(c):
        stripped = c.strip()
        if re.match(r'\\multicolumn\b', stripped):
            # Inject \textcolor{ao} around the content argument of \multicolumn
            mc_m = re.match(
                r'(\\multicolumn\s*\{[^}]*\}\s*\{[^}]*\}\s*)\{(.*)\}(.*)$',
                stripped, re.DOTALL
            )
            if mc_m:
                return mc_m.group(1) + r'{\textcolor{ao}{' + mc_m.group(2) + '}}' + mc_m.group(3)
            return c  # fallback: pass through unchanged
        return r'\cellcolor{diffadd}' + c
    add_cells = [_color_cell(c) for c in cells]
    return prefix + inner_prefix + ' & '.join(add_cells) + trailing


def diff_cells_inline(old_c, new_c):
    """Word-level diff between two cell strings, safe for LaTeX.

    If both cells are wrapped in a single {…} group (common in CSV data),
    we strip the outer braces before diffing and re-add them at the end.
    This prevents unbalanced tokens like '{SW' or 'solutions.}' from being
    passed individually to del_markup / add_markup.
    """
    def _strip_outer_braces(s):
        """Return (inner, True) if s is exactly {inner}, else (s, False)."""
        s = s.strip()
        if s.startswith('{') and s.endswith('}') and _brace_balanced(s[1:-1]):
            return s[1:-1], True
        return s, False

    old_inner, old_had = _strip_outer_braces(old_c)
    new_inner, new_had = _strip_outer_braces(new_c)
    # Only use stripped form if BOTH had outer braces (same structure)
    if old_had and new_had:
        result = diff_cells_inline(old_inner, new_inner)
        return '{' + result + '}'

    old_toks = re.findall(r'\S+|\s+', old_c)
    new_toks = re.findall(r'\S+|\s+', new_c)
    out = []
    sm = difflib.SequenceMatcher(None, old_toks, new_toks, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            out.append(''.join(old_toks[i1:i2]))
        elif tag == 'replace':
            old_chunk = ''.join(old_toks[i1:i2]).strip()
            new_chunk = ''.join(new_toks[j1:j2]).strip()
            if old_chunk:
                out.append(del_markup(old_chunk) if _brace_balanced(old_chunk)
                           else r'{\color{BUR}' + old_chunk + '}')
            if new_chunk:
                out.append(' ' + (add_markup(new_chunk) if _brace_balanced(new_chunk)
                                  else r'{\color{ao}' + new_chunk + '}'))
        elif tag == 'delete':
            chunk = ''.join(old_toks[i1:i2]).strip()
            if chunk:
                out.append(del_markup(chunk) if _brace_balanced(chunk)
                           else r'{\color{BUR}' + chunk + '}')
        elif tag == 'insert':
            chunk = ''.join(new_toks[j1:j2]).strip()
            if chunk:
                out.append(' ' + (add_markup(chunk) if _brace_balanced(chunk)
                                  else r'{\color{ao}' + chunk + '}'))
    return ''.join(out)



# ---------------------------------------------------------------------------
# Table diff helpers
# ---------------------------------------------------------------------------

def _row_match_key(row_text):
    """Return a stable matching key for a table row.

    For structural rows (\\hline, \\endhead, ...) the full normalised text is
    used so they align positionally.

    For data rows the *first cell* is used as the key.  This lets
    SequenceMatcher pair rows by their identifier (e.g. requirement ID) rather
    than by textual similarity of the whole row.  When a requirement description
    changes substantially the full-row key would differ and cause SequenceMatcher
    to misalign adjacent rows.  The first-cell key avoids that by anchoring
    matches on the stable identifier column.
    """
    if is_structural_row(row_text):
        return re.sub(r'\s+', ' ', row_text).strip()
    cells = split_cells(row_text)
    if cells:
        return re.sub(r'\s+', ' ', cells[0]).strip()
    return re.sub(r'\s+', ' ', row_text).strip()


def _diff_row_pair(or_, nr, n_new_cols):
    """Produce diff output for a matched (same first-cell key) old/new row pair.

    Returns a list of row strings to add to result_rows.
    If content is unchanged the new row is returned as-is.
    If content changed and columns match, a cell-level diff is returned.
    If column counts do not match, a delete+insert pair is returned.
    """
    if is_structural_row(or_) and is_structural_row(nr):
        return [nr]
    if or_.strip() == nr.strip():
        return [nr]
    oc = split_cells(or_)
    nc = split_cells(nr)
    tr = row_trailing(nr) or row_trailing(or_) or r'\\\hline'
    if is_structural_row(or_):
        return [nr]
    if len(oc) == len(nc) == n_new_cols:
        diffed = []
        for c1, c2 in zip(oc, nc):
            if c1.strip() == c2.strip():
                diffed.append(c2)
            else:
                diffed.append(
                    r'\cellcolor{diffdel!50!diffadd!50}'
                    + diff_cells_inline(c1, c2)
                )
        return [' & '.join(diffed) + tr]
    # Column count mismatch within a matched pair: delete old, add new
    prefix = row_leading(or_)
    return [
        prefix + render_deleted_row(oc, n_new_cols, row_trailing(or_)),
        render_added_row(nr),
    ]


def diff_tables(old_table, new_table):
    """Generate a merged table showing row-level and cell-level diffs.

    Algorithm:
      1. Parse both tables into (begin_tag, rows, end_tag) via parse_table_rows.
      2. Guard: if old and new tables have incompatible column counts (differ by
         more than 1) they are almost certainly from different contexts (e.g. a
         5-column requirements table matched against a 3-column traceability
         table at the segment level).  Return entirely-deleted + entirely-added
         instead of producing garbled diffs.
      3. Determine n_new_cols from the new table's data rows.
      4. Run SequenceMatcher on *first-cell* keys so rows are matched by their
         identifier (requirement ID, parent ID, ...) rather than by the
         similarity of their full text.  This prevents a row whose description
         changed substantially from being paired with a completely different row
         that happens to occupy the same position.
      5. For each opcode:
           equal   -> same ID: if content unchanged, pass through; if changed,
                      do cell-level diff via diff_cells_inline.
           insert  -> emit new rows with \\rowcolor{diffadd}.
           delete  -> emit old rows via render_deleted_row (pink + strikethrough).
           replace -> structural rows pass through (new version); data rows are
                      shown as delete+insert to avoid misleading cell-level diffs
                      between rows with different identifiers.
      6. Reassemble with the new begin/end tags.

    The new table's \\begin tag (including column spec) is always used for the
    output so the resulting table has the new structure.
    """
    old_begin, old_rows, old_end, _ = parse_table_rows(old_table)
    new_begin, new_rows, new_end, _ = parse_table_rows(new_table)

    old_data = [r for r in old_rows if not is_structural_row(r) and '&' in r]
    new_data = [r for r in new_rows if not is_structural_row(r) and '&' in r]
    old_n_cols = max((count_cells(r) + 1 for r in old_data), default=1) if old_data else 1
    n_new_cols = max((count_cells(r) + 1 for r in new_data), default=1) if new_data else 1

    # Guard: tables with very different column counts are almost certainly
    # unrelated (e.g. a requirements table matched against a traceability table
    # by the segment-level SequenceMatcher).
    if old_data and new_data and abs(old_n_cols - n_new_cols) > 1:
        return wrap_table_deleted(old_table) + '\n' + wrap_table_added(new_table)

    old_keys = [_row_match_key(r) for r in old_rows]
    new_keys = [_row_match_key(r) for r in new_rows]

    result_rows = []
    sm = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            # Keys (first cells) match; content may still differ.
            for or_, nr in zip(old_rows[i1:i2], new_rows[j1:j2]):
                result_rows.extend(_diff_row_pair(or_, nr, n_new_cols))

        elif tag == 'insert':
            for row in new_rows[j1:j2]:
                if is_structural_row(row):
                    result_rows.append(row)
                else:
                    result_rows.append(render_added_row(row))

        elif tag == 'delete':
            for row in old_rows[i1:i2]:
                if is_structural_row(row):
                    result_rows.append(row)
                else:
                    prefix = row_leading(row)
                    result_rows.append(
                        prefix + render_deleted_row(split_cells(row), n_new_cols, row_trailing(row))
                    )

        elif tag == 'replace':
            # With first-cell matching, replace occurs when structural or header
            # rows do not align cleanly.  Use delete+insert to avoid misleading
            # cell-level diffs between rows with different identifiers.
            for row in old_rows[i1:i2]:
                if is_structural_row(row):
                    result_rows.append(row)
                else:
                    prefix = row_leading(row)
                    result_rows.append(
                        prefix + render_deleted_row(split_cells(row), n_new_cols, row_trailing(row))
                    )
            for row in new_rows[j1:j2]:
                if is_structural_row(row):
                    result_rows.append(row)
                else:
                    result_rows.append(render_added_row(row))

    body = re.sub(r'\n{2,}', '\n', '\n'.join(r.lstrip('\n') for r in result_rows)).rstrip()
    return new_begin + body + '\n' + new_end

def wrap_table_added(table_content):
    """Colour all data rows green to indicate the entire table is new."""
    begin_tag, rows, end_tag, _ = parse_table_rows(table_content)
    new_rows = []
    for r in rows:
        if is_structural_row(r):
            new_rows.append(r)
        else:
            new_rows.append(render_added_row(r))
    body = re.sub(r'\n{2,}', '\n', '\n'.join(r.lstrip('\n') for r in new_rows)).rstrip()
    return begin_tag + body + '\n' + end_tag

def wrap_table_deleted(table_content):
    """Colour all data rows pink with strikethrough to indicate the entire table was deleted."""
    begin_tag, rows, end_tag, _ = parse_table_rows(table_content)
    data_rows = [r for r in rows if not is_structural_row(r) and '&' in r]
    n_cols = max((count_cells(r) + 1 for r in data_rows), default=1) if data_rows else 1
    new_rows = []
    for r in rows:
        if not is_structural_row(r):
            prefix = row_leading(r)
            new_rows.append(
                prefix + render_deleted_row(split_cells(r), n_cols, row_trailing(r))
            )
        else:
            new_rows.append(r)
    body = re.sub(r'\n{2,}', '\n', '\n'.join(r.lstrip('\n') for r in new_rows)).rstrip()
    return begin_tag + body + '\n' + end_tag


# ---------------------------------------------------------------------------
# Line-level text diff (safe for structural commands)
# ---------------------------------------------------------------------------

def _brace_balanced(text):
    """Return True if text has balanced, non-negative brace depth throughout.

    An unbalanced string (e.g. a lone } or a { with no matching }) cannot be
    safely wrapped in \\textcolor{}{} or \\sout{} — doing so would produce
    invalid LaTeX.  Used as a safety gate before applying markup.
    """
    depth = 0
    i = 0
    while i < len(text):
        c = text[i]
        if c == '\\':
            i += 2  # skip the escaped character
            continue
        if c == '{':
            depth += 1
        elif c == '}':
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return depth == 0


def _line_is_safe_for_color(line):
    """
    True if we can safely wrap this line in \\textcolor{}{} or {\\color{}}.
    Unsafe when the line has unbalanced braces (e.g. closes a group opened on
    a previous line).
    """
    return _brace_balanced(line)


# Lines containing optional LaTeX args like \cmd[...]{...} split badly on
# whitespace — fall back to whole-line markup for these.
_COMPLEX_LINE_RE = re.compile(r'\\[a-zA-Z]+\[')


def _latex_tokenize(line):
    """Brace-aware tokenizer for a single LaTeX line.

    Splits the line into whitespace and non-whitespace tokens, but keeps
    ``\\cmd{...}`` groups as a single token (including spaces inside the
    braces).  This prevents the diff from inserting colour commands inside
    ``\\ref{}``, ``\\cite{}``, ``\\label{}`` and similar arguments where
    LaTeX would reject colour markup.
    """
    tokens = []
    i = 0
    n = len(line)
    while i < n:
        if line[i].isspace():
            j = i
            while j < n and line[j].isspace():
                j += 1
            tokens.append(line[i:j])
            i = j
        elif line[i] == '\\':
            # Collect command name
            j = i + 1
            while j < n and line[j].isalpha():
                j += 1
            if j > i + 1:
                # Named command: greedily consume any immediately following
                # brace groups {…} (no space allowed between command and brace).
                k = j
                while k < n and line[k] == '{':
                    depth = 0
                    m = k
                    while m < n:
                        if line[m] == '{':
                            depth += 1
                        elif line[m] == '}':
                            depth -= 1
                            if depth == 0:
                                m += 1
                                break
                        m += 1
                    else:
                        # unmatched brace — stop collecting brace groups
                        break
                    k = m
                tokens.append(line[i:k])
                i = k
            else:
                # Single-char or symbol command (\\, \%, …)
                tokens.append(line[i:j + 1] if j < n else line[i:j])
                i = max(j + 1, i + 2)
        else:
            j = i
            while j < n and not line[j].isspace() and line[j] != '\\':
                j += 1
            tokens.append(line[i:j])
            i = j
    return tokens


def diff_words_in_line(old_line, new_line):
    """
    Word-level diff between two single lines of plain text.
    Falls back to whole-line markup if the line is too complex for safe
    token-level splitting (e.g. contains optional command arguments or
    inline LaTeX comments).

    Lines containing an unescaped % always fall back to whole-line mode:
    if a % token appeared in either half of the word diff, add_markup would
    emit \\textcolor{ao}{}%..., starting a line comment that silences all
    subsequent diff tokens on the same output line.  del_markup handles %
    correctly at the full-line level by splitting off the comment suffix.
    """
    _has_comment = re.compile(r'(?<!\\)%')
    if (_COMPLEX_LINE_RE.search(old_line) or _COMPLEX_LINE_RE.search(new_line)
            or _has_comment.search(old_line) or _has_comment.search(new_line)):
        # Whole-line fallback: show delete then add
        result = []
        if old_line.strip():
            result.append(del_markup(old_line))
        if new_line.strip():
            result.append('\n' + add_markup(new_line))
        return ''.join(result)

    old_toks = _latex_tokenize(old_line)
    new_toks = _latex_tokenize(new_line)
    out = []
    sm = difflib.SequenceMatcher(None, old_toks, new_toks, autojunk=False)
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            out.append(''.join(old_toks[i1:i2]))
        elif tag == 'replace':
            old_c = ''.join(old_toks[i1:i2]).strip()
            new_c = ''.join(new_toks[j1:j2]).strip()
            # Only wrap if the chunk has balanced braces (avoids LaTeX errors)
            if old_c:
                out.append(del_markup(old_c) if _brace_balanced(old_c)
                           else r'{\color{BUR}' + old_c + '}')
            if new_c:
                out.append(' ' + (add_markup(new_c) if _brace_balanced(new_c)
                                  else r'{\color{ao}' + new_c + '}'))
        elif tag == 'delete':
            c = ''.join(old_toks[i1:i2]).strip()
            if c:
                out.append(del_markup(c) if _brace_balanced(c)
                           else r'{\color{BUR}' + c + '}')
        elif tag == 'insert':
            c = ''.join(new_toks[j1:j2]).strip()
            if c:
                out.append(' ' + (add_markup(c) if _brace_balanced(c)
                                  else r'{\color{ao}' + c + '}'))
    return ''.join(out)


def _safe_del_line(stripped, eol, show_section_note=True, force_comment=False):
    """
    Mark a deleted line safely.
    Lines containing \\begin{} or \\end{} must become comments — wrapping them
    in {\\color{}} would still *execute* the environment command, opening or
    closing real environments alongside the new content and breaking structure.
    Lines with unbalanced braces also fall back to comments.

    When show_section_note is True (default), a small visible colored annotation
    is added for deleted section headings so the reader can see which section was
    removed.  Pass show_section_note=False in replace blocks that will add their
    own [was: ...] annotation via _section_rename_note.

    When force_comment is True, always emit a ``% DIFF-DEL:`` comment regardless
    of the line content.  Used when the caller knows the line is inside a
    sensitive environment (tikzpicture, algorithmic, …) where even ordinary
    content cannot be safely wrapped in colour commands.
    """
    if not stripped.strip():
        return ''
    # Pure LaTeX comment lines (% ...) must not be wrapped in del_markup() —
    # del_markup() splits at % and returns \textcolor{BUR}{\sout{}}% ... with an
    # empty strikethrough box.  Comment them out as DIFF-DEL instead.
    if re.match(r'[ \t]*%', stripped):
        return '% DIFF-DEL: ' + stripped + eol
    # Never execute deleted \begin / \end — they would open real environments.
    # Never execute deleted \item — it requires its parent list environment,
    # which is itself commented out.
    # Never execute deleted section commands — they would add numbered sections
    # and shift the document's section numbering.
    # Never wrap TikZ-specific commands (e.g. \node, \coordinate, \draw,
    # \path) or algorithmic commands (\STATE, \IF, etc.) in \sout{} or
    # {\color{}} — they require their parent environment (tikzpicture /
    # algorithmic) to be active, and executing them in document context causes
    # "Undefined control sequence" or silent corruption.
    if force_comment or _COMMENT_DEL_RE.search(stripped):
        comment = '% DIFF-DEL: ' + stripped + eol
        # For section headings, also emit a small visible colored annotation so
        # the reader knows which section was removed (the % comment is invisible).
        if show_section_note:
            sec_m = _SECTION_HEADING_RE.search(stripped)
            if sec_m and sec_m.group(2).strip():
                visible = (r'{\color{BUR}\footnotesize\textit{[Removed: '
                           + sec_m.group(2).strip() + r']}}\par' + '\n')
                return comment + visible
        return comment
    if _line_is_safe_for_color(stripped):
        return del_markup(stripped) + eol
    # Unbalanced braces — use a comment to record the deletion safely
    return '% DIFF-DEL: ' + stripped + eol


def _safe_add_line(stripped, eol, line_orig):
    """Mark an inserted line with green colour if safe; otherwise emit it unchanged.

    Lines are left unmarked when:
      - They are empty or consist solely of structural LaTeX commands — these
        are needed for document structure and must not be coloured.
      - They are pure LaTeX comments (start with %) — wrapping them in
        \\textcolor{ao}{} produces \\textcolor{ao}{}%..., which makes the `%`
        start a line comment that hides all subsequent diff markup on the same
        output line.
      - They contain optional argument syntax \\cmd[...] — wrapping such lines
        would break the command parsing (e.g. \\includepdf[...], \\csvlongtable).
      - They have unbalanced braces (part of a multi-line group).

    \\item is handled specially: the \\item token must remain BEFORE the colour
    group because LaTeX requires \\item to appear directly in a list environment,
    not inside \\textcolor{}{}.
    """
    if not stripped.strip() or is_structural(stripped):
        return line_orig
    # Pure LaTeX comment lines (% ...) must pass through unchanged.
    # Wrapping in \textcolor{ao}{} would produce \textcolor{ao}{}%..., causing
    # the % to comment out all following markup on that physical output line.
    if re.match(r'[ \t]*%', stripped):
        return line_orig
    # Document-level or complex commands with optional args ([...]) must not be
    # wrapped in \textcolor{} — it would break commands like \includepdf, \csvlongtable
    if _COMPLEX_LINE_RE.search(stripped):
        return line_orig
    # TikZ / algorithmic / float-specific commands must not be wrapped in
    # \textcolor{} — color group boundaries break multi-line TikZ statements
    # (the continuation after "at" on the next line falls outside the color
    # group) and environment-specific commands need their parent env active.
    if _COMMENT_DEL_RE.search(stripped):
        return line_orig
    # \item must come BEFORE the color group — \textcolor{\item...} causes errors
    # because LaTeX sees content before the first \item in a list.
    item_m = re.match(r'^(\s*\\item\b[*]?\s*)', stripped)
    if item_m:
        rest = stripped[item_m.end():]
        if rest.strip():
            return item_m.group(1) + add_markup(rest) + eol
        return line_orig  # bare \item with no content
    if _line_is_safe_for_color(stripped):
        return add_markup(stripped) + eol
    return line_orig  # can't safely color; just show new value


def diff_text_block(old, new):
    """
    Line-level diff between two text blocks.
    Uses word-level diff within matched line pairs; marks structural lines
    with color only (no sout) so they remain compilable.  Lines with
    unbalanced braces (part of multi-line groups) fall back to LaTeX comments
    for deletions so the output still compiles.
    """
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)

    result = []
    sm = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)

    # Track depth inside environments where LaTeX colour markup is unsafe:
    # tikzpicture (TikZ commands + multi-line options), algorithmic variants
    # (environment-specific commands), verbatim-like environments.
    # Depth is maintained across opcodes based on what appears in the OUTPUT
    # (i.e. equal/insert/replace-new lines).  Lines that appear only in the
    # old text (delete opcode) do not change the output-document depth.
    _SENSITIVE_ENV_NAMES = (
        'tikzpicture', 'algorithmic', 'algorithm2e',
        'lstlisting', 'verbatim', 'Verbatim',
    )
    _sens_begin = re.compile(
        r'\\begin\{(' + '|'.join(_SENSITIVE_ENV_NAMES) + r')\}'
    )
    _sens_end = re.compile(
        r'\\end\{(' + '|'.join(_SENSITIVE_ENV_NAMES) + r')\}'
    )
    sensitive_depth = 0

    def _track_depth(line):
        nonlocal sensitive_depth
        sensitive_depth += len(_sens_begin.findall(line))
        sensitive_depth -= len(_sens_end.findall(line))
        sensitive_depth = max(0, sensitive_depth)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for line in new_lines[j1:j2]:
                _track_depth(line)
            result.extend(new_lines[j1:j2])

        elif tag == 'insert':
            for line in new_lines[j1:j2]:
                _track_depth(line)
                if sensitive_depth > 0:
                    result.append(line)  # inside sensitive env — pass through
                    continue
                stripped = line.rstrip('\n')
                eol = '\n' if line.endswith('\n') else ''
                result.append(_safe_add_line(stripped, eol, line))

        elif tag == 'delete':
            for line in old_lines[i1:i2]:
                # Deleted lines don't appear in the output, so don't update
                # sensitive_depth here — depth is output-document depth.
                stripped = line.rstrip('\n')
                eol = '\n' if line.endswith('\n') else ''
                result.append(_safe_del_line(stripped, eol,
                                             force_comment=sensitive_depth > 0))

        elif tag == 'replace':
            ob = old_lines[i1:i2]
            nb = new_lines[j1:j2]

            # Detect section renames: when the first pair of lines are both
            # section-type commands but with different content.  In that case,
            # break positional pairing after the heading and emit remaining old
            # lines as pure deletes and remaining new lines as pure inserts.
            # This prevents deleted section content from bleeding into the new
            # section body (which confuses readers who see unrelated red text
            # below a new section headline).
            section_rename = False
            if ob and nb:
                ol0 = ob[0].rstrip('\n')
                nl0 = nb[0].rstrip('\n')
                if (is_structural(ol0) and is_structural(nl0) and ol0 != nl0
                        and _SECTION_HEADING_RE.search(ol0)
                        and _SECTION_HEADING_RE.search(nl0)):
                    section_rename = True

            if section_rename:
                old_eol = '\n' if ob[0].endswith('\n') else ''
                # show_section_note=False: suppress [Removed: ...] since we add [was: ...] below
                result.append(_safe_del_line(ob[0].rstrip('\n'), old_eol, show_section_note=False))
                _track_depth(nb[0])
                result.append(nb[0])
                note = _section_rename_note(ob[0].rstrip('\n'))
                if note:
                    result.append(note)
                # Remaining old lines: pure deletes (don't pair with new content)
                for line in ob[1:]:
                    stripped = line.rstrip('\n')
                    eol = '\n' if line.endswith('\n') else ''
                    result.append(_safe_del_line(stripped, eol))
                # Remaining new lines: pure inserts
                for line in nb[1:]:
                    _track_depth(line)
                    result.append(_safe_add_line(
                        line.rstrip('\n'),
                        '\n' if line.endswith('\n') else '',
                        line,
                    ))
            else:
                for k in range(max(len(ob), len(nb))):
                    if k < len(ob) and k < len(nb):
                        ol = ob[k].rstrip('\n')
                        nl = nb[k].rstrip('\n')
                        eol = '\n' if nb[k].endswith('\n') else ''
                        _track_depth(nb[k])
                        if sensitive_depth > 0 or _sens_begin.search(nb[k]) or _sens_end.search(nb[k]):
                            # Inside (or entering/leaving) a sensitive env:
                            # comment old, keep new as-is
                            old_eol = '\n' if ob[k].endswith('\n') else ''
                            result.append(_safe_del_line(ol, old_eol,
                                                         force_comment=sensitive_depth > 0))
                            result.append(nb[k])
                        elif is_structural(ol) or is_structural(nl):
                            old_eol = '\n' if ob[k].endswith('\n') else ''
                            note = _section_rename_note(ol)
                            # Suppress [Removed: ...] if we'll add [was: ...] note
                            result.append(_safe_del_line(ol, old_eol,
                                                         show_section_note=not bool(note)))
                            result.append(nb[k])
                            if note:
                                result.append(note)
                        elif (not _line_is_safe_for_color(ol)
                              or not _line_is_safe_for_color(nl)):
                            # Multi-line brace group: comment old, keep new
                            old_eol = '\n' if ob[k].endswith('\n') else ''
                            result.append(_safe_del_line(ol, old_eol))
                            result.append(nb[k])
                        elif _COMMENT_DEL_RE.search(ol) or _COMMENT_DEL_RE.search(nl):
                            # TikZ / algorithmic / environment-specific commands
                            # cannot run outside their parent environment.  Treat
                            # old line as a safe comment-delete and new line as-is.
                            old_eol = '\n' if ob[k].endswith('\n') else ''
                            result.append(_safe_del_line(ol, old_eol))
                            result.append(_safe_add_line(nl, eol, nb[k]))
                        else:
                            result.append(diff_words_in_line(ol, nl) + eol)
                    elif k < len(ob):
                        line = ob[k]
                        stripped = line.rstrip('\n')
                        eol = '\n' if line.endswith('\n') else ''
                        result.append(_safe_del_line(stripped, eol))
                    else:
                        _track_depth(nb[k])
                        if sensitive_depth > 0:
                            result.append(nb[k])
                        else:
                            result.append(_safe_add_line(
                                nb[k].rstrip('\n'),
                                '\n' if nb[k].endswith('\n') else '',
                                nb[k]
                            ))

    return ''.join(result)


# ---------------------------------------------------------------------------
# Segment-level diff
# ---------------------------------------------------------------------------

def diff_segments(old_segs, new_segs):
    """Diff two lists of (type, content) segments and return the merged result string.

    Segments are compared by whitespace-normalised content keys so that
    formatting-only differences don't prevent matching.  For each SequenceMatcher
    opcode the appropriate handler is called:
      equal   → new content as-is
      insert  → wrap_table_added / diff_text_block('', new)
      delete  → wrap_table_deleted / diff_text_block(old, '')
      replace → diff_tables (table↔table), diff_text_block (text↔text),
                or mixed delete+add when types differ.

    Note: text segment inserts/deletes use diff_text_block rather than
    del_markup/add_markup to process them line-by-line.  This is critical
    because text segments often begin with a lone '}' that closes the brace
    group opened in the preceding xltabular wrapper — wrapping the whole
    segment in {\\color{BUR}...} would immediately close that colour group,
    producing catastrophically unbalanced braces.
    """
    old_keys = [re.sub(r'\s+', ' ', c).strip() for _, c in old_segs]
    new_keys = [re.sub(r'\s+', ' ', c).strip() for _, c in new_segs]

    result = []
    sm = difflib.SequenceMatcher(None, old_keys, new_keys, autojunk=False)

    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag == 'equal':
            for _, c in new_segs[j1:j2]:
                result.append(c)

        elif tag == 'insert':
            for st, c in new_segs[j1:j2]:
                result.append(wrap_table_added(c) if st == 'table' else
                               diff_text_block('', c) if c.strip() else c)

        elif tag == 'delete':
            for st, c in old_segs[i1:i2]:
                result.append(wrap_table_deleted(c) if st == 'table' else
                               diff_text_block(c, '') if c.strip() else c)

        elif tag == 'replace':
            ob = old_segs[i1:i2]
            nb = new_segs[j1:j2]
            for k in range(max(len(ob), len(nb))):
                if k < len(ob) and k < len(nb):
                    ot, oc = ob[k]
                    nt, nc = nb[k]
                    if ot == 'table' and nt == 'table':
                        result.append(diff_tables(oc, nc))
                    elif ot == 'text' and nt == 'text':
                        # If the new segment opens a float environment (table/figure),
                        # place deleted content *before* the float rather than
                        # interleaving it inside.  Interleaving puts deleted paragraphs
                        # inside \begin{table}...\end{table}, making the float too
                        # large for the page.
                        if _FLOAT_ENV_OPEN_RE.search(nc):
                            result.append(diff_text_block(oc, '') if oc.strip() else oc)
                            result.append(diff_text_block('', nc) if nc.strip() else nc)
                        else:
                            result.append(diff_text_block(oc, nc))
                    else:
                        result.append(wrap_table_deleted(oc) if ot == 'table'
                                      else diff_text_block(oc, '') if oc.strip() else oc)
                        result.append(wrap_table_added(nc) if nt == 'table'
                                      else diff_text_block('', nc) if nc.strip() else nc)
                elif k < len(ob):
                    ot, oc = ob[k]
                    result.append(wrap_table_deleted(oc) if ot == 'table'
                                  else diff_text_block(oc, '') if oc.strip() else oc)
                else:
                    nt, nc = nb[k]
                    result.append(wrap_table_added(nc) if nt == 'table'
                                  else diff_text_block('', nc) if nc.strip() else nc)

    return ''.join(result)


# ---------------------------------------------------------------------------
# CSV table expansion
# ---------------------------------------------------------------------------

# Specification for each CSV-backed table command:
#   key_col  : 0-based column used as row identity for diffing (None = whole row)
#   col_idx  : 0-based column indices to emit (in order)
#   headers  : LaTeX header cell text for each column
#   colspec  : xltabular column spec
CSV_COMMANDS = {
    'csvlongtable': {
        'key_col': 2,          # Requirement ID
        'col_idx': [2, 3, 4, 5, 6],
        'headers': ['ID', 'Description', 'VM', 'Parent', 'Notes'],
        'colspec': r'|S|L|c|S|L|',
    },
    'csvlongtbd': {
        'key_col': 0,          # TBD/TBC ID
        'col_idx': [0, 1, 2],
        'headers': ['TBC/TBD ID', 'Requirement ID', 'Comment (due)'],
        'colspec': r'|l|M|N|',
    },
    'csvlongtrace': {
        'key_col': None,       # composite key: whole row
        'col_idx': [0, 1, 2],
        'headers': ['Parent', 'Requirement ID', 'Original requirement description'],
        'colspec': r'|l|M|N|',
    },
}


def _split_csv_line(line, sep=';'):
    """Split a semicolon-separated CSV line while respecting LaTeX {}-group nesting.

    A semicolon inside a {}-group (e.g. inside a \\url{} or \\texttt{}) is NOT
    treated as a field separator.  This prevents splitting URLs or other braced
    content that happens to contain semicolons.
    """
    fields, current, depth = [], [], 0
    for ch in line:
        if ch == '{':
            depth += 1
            current.append(ch)
        elif ch == '}':
            depth -= 1
            current.append(ch)
        elif ch == sep and depth == 0:
            fields.append(''.join(current).strip())
            current = []
        else:
            current.append(ch)
    fields.append(''.join(current).strip())
    return fields


def _read_csv(text, sep=';'):
    """Parse CSV text into a list of field-lists, skipping the header row and blank/comment lines."""
    lines = [l for l in text.splitlines() if l.strip() and not l.startswith('%')]
    if not lines:
        return []
    rows = []
    for line in lines[1:]:   # skip header
        fields = _split_csv_line(line, sep)
        if any(f.strip() for f in fields):
            rows.append(fields)
    return rows


def _row_to_latex(fields, col_idx):
    """Render selected columns of a CSV row as a LaTeX table row ending with \\\\ \\hline.

    col_idx is a list of 0-based column indices to include (in order).
    Trailing \\newline or \\\\ sequences are stripped from cell values to avoid
    accidentally ending the row inside a cell.
    """
    cells = []
    for i in col_idx:
        val = fields[i] if i < len(fields) else ''
        # Strip trailing \newline / \\ which would end the row inside a cell
        val = re.sub(r'(\\newline|\\\\)\s*$', '', val.strip())
        cells.append(val)
    return ' & '.join(cells) + r' \\ \hline'


def _xltabular_header(spec):
    """Build the opening lines of an inline xltabular, matching the \\csvlongtable style.

    The \\renewcommand{\\arraystretch} and font settings are applied in a brace
    group that wraps the entire environment (closed by _xltabular_footer).
    spec is a CSV_COMMANDS entry dict with keys 'colspec' and 'headers'.
    """
    colspec = spec['colspec']
    headers = ' & '.join(spec['headers']) + r' \\ \hline\hline'
    return (
        r'{\renewcommand{\arraystretch}{1.4}\tiny\fontfamily{phv}\selectfont'
        + '\n'
        + r'\begin{xltabular}{\textwidth}{' + colspec + '}\n'
        + r'\hline' + '\n'
        + headers + '\n'
        + r'\endhead' + '\n'
    )


def _xltabular_footer():
    """Return the closing line of an inline xltabular (\\end{xltabular} + closing brace group)."""
    return r'\end{xltabular}}' + '\n'


def csv_to_xltabular(rows, cmd_name):
    """Render a list of parsed CSV rows as a plain (no-diff) inline xltabular.

    Used when a CSV file exists in only one version (old or new), so there is
    nothing to diff — the table is shown as entirely added or deleted by the
    surrounding wrap_table_added / wrap_table_deleted logic.
    """
    spec = CSV_COMMANDS[cmd_name]
    lines = [_xltabular_header(spec)]
    for row in rows:
        lines.append(_row_to_latex(row, spec['col_idx']))
    lines.append(_xltabular_footer())
    return '\n'.join(lines)


def expand_csv_commands(text, cmd_name, old_loader, new_loader):
    """
    Replace every \\cmd_name{file} call in text with an inline xltabular.
    old_loader(path) and new_loader(path) return the CSV file content as a
    string (or None if the file does not exist at that version).
    The result is TWO strings: old_expanded and new_expanded — the same
    text but with \\cmd_name{...} replaced by their inline table equivalents,
    using old_loader for one and new_loader for the other.
    """
    pattern = re.compile(r'\\' + re.escape(cmd_name) + r'\{([^}]+)\}')
    spec = CSV_COMMANDS[cmd_name]

    def replace(m, loader):
        csv_path = m.group(1)
        content = loader(csv_path)
        if content is None:
            return m.group(0)   # leave unchanged if file not available
        rows = _read_csv(content)
        if not rows:
            return r'{\small No requirements / entries.}' + '\n'
        return csv_to_xltabular(rows, cmd_name)

    old_out = pattern.sub(lambda m: replace(m, old_loader), text)
    new_out = pattern.sub(lambda m: replace(m, new_loader), text)
    return old_out, new_out


def expand_all_csv_commands(old_text, new_text, old_loader, new_loader):
    """Expand all known CSV table commands in both old and new document texts.

    Processes \\csvlongtable, \\csvlongtbd and \\csvlongtrace in one pass each.
    After expansion the diff pipeline sees ordinary inline xltabular environments
    and can apply row/cell-level diffs to them.

    old_loader(path) / new_loader(path) are callables that return the CSV file
    content as a string, or None if the file does not exist at that version
    (in which case the \\cmd{file} token is left unchanged).

    Returns (old_expanded, new_expanded, any_expanded) where any_expanded is True
    only if at least one CSV file was actually loaded and replaced.
    """
    def make_replacer(cmd_name, loader):
        def replacer(m):
            csv_path = m.group(1)
            content = loader(csv_path)
            if content is None:
                return m.group(0)
            rows = _read_csv(content)
            if not rows:
                return r'{\small No requirements / entries.}' + '\n'
            return csv_to_xltabular(rows, cmd_name)
        return replacer

    old_original, new_original = old_text, new_text
    for cmd in CSV_COMMANDS:
        pat = re.compile(r'\\' + re.escape(cmd) + r'\{([^}]+)\}')
        old_text = pat.sub(make_replacer(cmd, old_loader), old_text)
        new_text = pat.sub(make_replacer(cmd, new_loader), new_text)
    any_expanded = (old_text != old_original or new_text != new_original)
    return old_text, new_text, any_expanded

def git_show(repo, commit, path):
    """Return the text content of <path> at <commit> in git repo <repo>, or None if absent."""
    try:
        result = subprocess.run(
            ['git', 'show', f'{commit}:{path}'],
            cwd=repo, capture_output=True, check=True
        )
        return result.stdout.decode('utf-8', errors='replace')
    except subprocess.CalledProcessError:
        return None


def flatten(text, base_dir, loader):
    r"""
    Recursively expand \include{file} and \input{file} directives.
    loader(rel_path) → str|None  fetches the content of a sub-file.
    \include adds a \clearpage before/after (matching LaTeX semantics);
    \input is a raw splice.
    """
    def replacer(m):
        cmd = m.group(1)        # 'include' or 'input'
        arg = m.group(2).strip()
        if not arg.endswith('.tex'):
            arg += '.tex'
        sub = loader(arg)
        if sub is None:
            return m.group(0)   # leave as-is if file not found
        sub = flatten(sub, base_dir, loader)
        if cmd == 'include':
            return '\n\\clearpage\n' + sub + '\n\\clearpage\n'
        return sub

    return re.sub(r'\\(include|input)\{([^}]+)\}', replacer, text)


def flatten_from_disk(text, base_dir):
    """Flatten a document by reading \\include/\\input sub-files from the local filesystem."""
    def loader(rel):
        full = os.path.join(base_dir, rel)
        if os.path.exists(full):
            return open(full, encoding='utf-8').read()
        return None
    return flatten(text, base_dir, loader)


def flatten_from_git(text, repo, commit):
    """Flatten a document by reading \\include/\\input sub-files from a git commit."""
    def loader(rel):
        return git_show(repo, commit, rel)
    return flatten(text, repo, loader)


# ---------------------------------------------------------------------------
# Preamble handling
# ---------------------------------------------------------------------------

def split_preamble_body(text):
    """Split a LaTeX document into (preamble_up_to_and_including_begin_document, body).

    If \\begin{document} is not found, returns (text, '').
    """
    m = re.search(r'\\begin\{document\}', text)
    if not m:
        return text, ''
    return text[:m.end()], text[m.end():]


def diff_preamble_tables(old_preamble, new_preamble):
    """
    Diff only the TABLE segments inside the preamble (i.e. xltabular/tabular
    environments embedded in \\newcommand definitions).  All non-table text is
    taken from the new preamble unchanged — diffing arbitrary preamble code
    (\\documentclass, \\usepackage, \\ifthenelse …) would produce invalid LaTeX.
    Tables are paired positionally (1st old table ↔ 1st new table, etc.).
    """
    old_segs = segment_text(old_preamble)
    new_segs = segment_text(new_preamble)

    old_tables = [c for t, c in old_segs if t == 'table']
    result = []
    table_idx = 0
    for seg_type, content in new_segs:
        if seg_type == 'table':
            if table_idx < len(old_tables):
                result.append(diff_tables(old_tables[table_idx], content))
            else:
                result.append(content)  # new table with no old counterpart
            table_idx += 1
        else:
            result.append(content)
    return ''.join(result)


# Matches the opening tag of a LaTeX float environment at the start of a text segment.
# Used in diff_segments to detect new text segments that open a float, so that deleted
# content from the old segment is placed before the float rather than inside it.
_FLOAT_ENV_OPEN_RE = re.compile(r'\\begin\{(table|figure)\*?\}')


def make_diff_legend_page(old_label: str, new_label: str) -> str:
    """Return LaTeX source for a standalone legend page to prepend to the diff body.

    The page lists the two compared versions and provides a visual key for all
    diff markup styles used in the document.
    """
    return (
        r'\clearpage' '\n'
        r'\thispagestyle{empty}' '\n'
        r'\begin{center}' '\n'
        r'{\LARGE\bfseries Document Diff}\\[0.8em]' '\n'
        r'{\large Comparison between two versions}\\[1.5em]' '\n'
        r'\begin{tabular}{ll}' '\n'
        r'  \textbf{Old version:} & \texttt{' + _tex_escape_label(old_label) + r'} \\' '\n'
        r'  \textbf{New version:} & \texttt{' + _tex_escape_label(new_label) + r'} \\' '\n'
        r'  \textbf{Generated:}   & \today \\' '\n'
        r'\end{tabular}' '\n'
        r'\end{center}' '\n'
        r'\vspace{2em}' '\n'
        r'{\large\bfseries Legend}\\[0.5em]' '\n'
        r'\begin{tabular}{lp{0.75\textwidth}}' '\n'
        r'  \colorbox{diffadd}{\phantom{XX}} & Added table row (green background) \\[0.4em]' '\n'
        r'  \colorbox{diffdel}{\phantom{XX}} & Deleted table row (pink/red background) \\[0.4em]' '\n'
        r'  \textcolor{ao}{Green text} & Text added in the new version \\[0.4em]' '\n'
        r'  \textcolor{BUR}{\sout{Red strikethrough}} & Text deleted from the old version (inline content) \\[0.4em]' '\n'
        r'  {\color{BUR}Red (no strikethrough)} & Text deleted from the old version (complex/structural content) \\[0.4em]' '\n'
        r'  \texttt{\% DIFF-DEL: \ldots} & Structurally deleted \LaTeX{} commands (commented out) \\' '\n'
        r'\end{tabular}' '\n'
        r'\clearpage' '\n'
    )


def _tex_escape_label(s: str) -> str:
    """Escape characters that are special in LaTeX so version labels render safely."""
    replacements = [
        ('\\', r'\textbackslash{}'),
        ('_', r'\_'),
        ('^', r'\^{}'),
        ('%', r'\%'),
        ('$', r'\$'),
        ('#', r'\#'),
        ('&', r'\&'),
        ('{', r'\{'),
        ('}', r'\}'),
        ('~', r'\textasciitilde{}'),
    ]
    for old, new in replacements:
        s = s.replace(old, new)
    return s


def inject_diff_packages(preamble):
    """Insert ulem, colortbl and colour definitions after the last \\usepackage line.

    Packages that embed external metadata or have run-time dependencies not
    relevant to a diff PDF are stripped from the preamble to avoid unnecessary
    compilation failures.

    If no \\usepackage is found the additions are appended at the end of the
    preamble string.
    """
    # Packages that are irrelevant (or harmful) in a diff document
    _STRIP_PACKAGES = (
        'hyperxmp',    # requires ccicons at \begin{document}; XMP metadata not needed
        'doclicense',  # requires ccicons for CC licence icons; not needed in diff
    )
    for pkg in _STRIP_PACKAGES:
        # Match \usepackage[opt]{pkg} where [opt] may span multiple lines
        preamble = re.sub(
            r'[ \t]*\\usepackage(?:\[[^\]]*\])?\{' + re.escape(pkg) + r'\}[^\n]*\n?',
            '',
            preamble,
        )
        # Also handle multi-line optional args: \usepackage[\n  ...\n]{pkg}
        preamble = re.sub(
            r'[ \t]*\\usepackage\s*\[[^\]]*\]\s*\{' + re.escape(pkg) + r'\}[^\n]*\n?',
            '',
            preamble,
            flags=re.DOTALL,
        )

    # Strip fancyhead/fancyfoot lines that reference \doclicenseImage, since
    # doclicense is not loaded in the diff document.
    preamble = re.sub(
        r'[ \t]*\\fancy(?:head|foot)\s*\[[^\]]*\]\s*\{[^}]*\\doclicense[^}]*\}[^\n]*\n?',
        '',
        preamble,
    )

    # Define doclicense commands as no-ops in case any slipped through into
    # the document body (e.g. \doclicenseThis, \doclicenseIcon).
    noop_defs = (
        r'\providecommand{\doclicenseThis}{}'
        '\n'
        r'\providecommand{\doclicenseImage}[1][]{}'
        '\n'
        r'\providecommand{\doclicenseIcon}[1][]{}'
        '\n'
        r'\providecommand{\doclicenseLongName}{}'
        '\n'
    )
    last = list(re.finditer(r'\\usepackage.*', preamble))
    additions = '\n' + noop_defs + DIFF_PACKAGE_LINES + DIFF_COLORS
    if last:
        pos = last[-1].end()
        return preamble[:pos] + additions + preamble[pos:]
    return preamble + additions


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    """Entry point: parse arguments and run the diff pipeline.

    Two modes:
      Standard:  old.tex new.tex output.tex
        Reads two standalone .tex files, flattens \\include/\\input sub-files,
        expands CSV table commands, and diffs them directly.

      Git mode:  --git [<repo_dir>] <old_commit> [<new_commit>] <main.tex> output.tex
        If <repo_dir> is omitted the current working directory is used as the repo.
        If <new_commit> is omitted the working tree is used as the new version.
        1. Reads main.tex and all its \\include'd sub-files at old_commit from git.
        2. Reads the new version either from the working tree (default) or from
           <new_commit> in git (two-commit mode).
        3. Expands \\csvlongtable / \\csvlongtbd / \\csvlongtrace in both versions.
        4. Runs the shared diff pipeline on the flattened+expanded texts.

    Shared diff pipeline:
      1. Split both texts at \\begin{document} (preamble + body).
      2. Inject diff packages into the new preamble.
      3. Segment the body into text and table blocks.
      4. Diff the segments; write preamble + diffed body to output.
    """
    if len(sys.argv) == 4 and sys.argv[1] != '--git':
        # Standard two-file mode
        old_path, new_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
        old_label = old_path
        new_label = new_path
        with open(old_path, encoding='utf-8') as f:
            old_text = f.read()
        with open(new_path, encoding='utf-8') as f:
            new_text = f.read()
        # Flatten \include / \input sub-files (same as git mode does)
        old_dir = os.path.dirname(os.path.abspath(old_path))
        new_dir = os.path.dirname(os.path.abspath(new_path))
        old_text = flatten_from_disk(old_text, old_dir)
        new_text = flatten_from_disk(new_text, new_dir)
        # Expand CSV-backed table commands using disk loaders for both versions
        def _old_csv_loader(path):
            full = os.path.join(old_dir, path)
            return open(full, encoding='utf-8').read() if os.path.exists(full) else None
        def _new_csv_loader(path):
            full = os.path.join(new_dir, path)
            return open(full, encoding='utf-8').read() if os.path.exists(full) else None
        old_text, new_text, csv_expanded = expand_all_csv_commands(
            old_text, new_text, _old_csv_loader, _new_csv_loader
        )
        if csv_expanded:
            print('CSV tables expanded for diffing')

    elif sys.argv[1] == '--git' and len(sys.argv) in (5, 6, 7):
        # Git mode argument parsing.  The optional <repo_dir> is distinguished from
        # a commit hash by checking whether the first positional argument is a directory.
        #
        # Supported forms:
        #   --git <old_commit> <main.tex> <output.tex>              (repo = cwd)
        #   --git <repo_dir> <old_commit> <main.tex> <output.tex>
        #   --git <old_commit> <new_commit> <main.tex> <output.tex> (repo = cwd)
        #   --git <repo_dir> <old_commit> <new_commit> <main.tex> <output.tex>
        args = sys.argv[2:]  # everything after --git
        if os.path.isdir(args[0]):
            repo_dir = os.path.abspath(args[0])
            args = args[1:]
        else:
            repo_dir = os.path.abspath(os.getcwd())

        # args is now: <old_commit> [<new_commit>] <main.tex> <output.tex>
        if len(args) == 3:
            old_commit, main_tex, out_path = args
            new_commit = None   # compare against working tree
        elif len(args) == 4:
            old_commit, new_commit, main_tex, out_path = args
        else:
            print('Usage:', file=sys.stderr)
            print('  latexdiff_better.py --git <old_commit> <main.tex> output.tex', file=sys.stderr)
            print('  latexdiff_better.py --git <repo_dir> <old_commit> <main.tex> output.tex', file=sys.stderr)
            print('  latexdiff_better.py --git <old_commit> <new_commit> <main.tex> output.tex', file=sys.stderr)
            print('  latexdiff_better.py --git <repo_dir> <old_commit> <new_commit> <main.tex> output.tex', file=sys.stderr)
            sys.exit(1)

        main_rel = os.path.relpath(main_tex, repo_dir) if os.path.isabs(main_tex) else main_tex
        old_label = old_commit

        old_main = git_show(repo_dir, old_commit, main_rel)
        if old_main is None:
            print(f'Error: {main_rel} not found at commit {old_commit}', file=sys.stderr)
            sys.exit(1)
        old_text = flatten_from_git(old_main, repo_dir, old_commit)

        if new_commit is None:
            # Compare against working tree
            new_label = f'{main_rel} (working tree)'
            new_main_path = os.path.join(repo_dir, main_rel)
            with open(new_main_path, encoding='utf-8') as f:
                new_text = flatten_from_disk(f.read(), repo_dir)
            def new_csv_loader(path):
                full = os.path.join(repo_dir, path)
                return open(full, encoding='utf-8').read() if os.path.exists(full) else None
        else:
            # Two-commit mode: read new version from git as well
            new_label = new_commit
            new_main = git_show(repo_dir, new_commit, main_rel)
            if new_main is None:
                print(f'Error: {main_rel} not found at commit {new_commit}', file=sys.stderr)
                sys.exit(1)
            new_text = flatten_from_git(new_main, repo_dir, new_commit)
            def new_csv_loader(path):
                return git_show(repo_dir, new_commit, path)

        def old_csv_loader(path):
            return git_show(repo_dir, old_commit, path)

        old_text, new_text, csv_expanded = expand_all_csv_commands(
            old_text, new_text, old_csv_loader, new_csv_loader
        )
        if csv_expanded:
            print('CSV tables expanded for diffing')

    else:
        print('Usage:', file=sys.stderr)
        print('  latexdiff_better.py old.tex new.tex output.tex', file=sys.stderr)
        print('  latexdiff_better.py --git <old_commit> <main.tex> output.tex', file=sys.stderr)
        print('  latexdiff_better.py --git <repo_dir> <old_commit> <main.tex> output.tex', file=sys.stderr)
        print('  latexdiff_better.py --git <old_commit> <new_commit> <main.tex> output.tex', file=sys.stderr)
        print('  latexdiff_better.py --git <repo_dir> <old_commit> <new_commit> <main.tex> output.tex', file=sys.stderr)
        sys.exit(1)

    # ------------------------------------------------------------------
    # Diff pipeline (shared by both modes)
    # ------------------------------------------------------------------
    old_preamble, old_body = split_preamble_body(old_text)
    new_preamble, new_body = split_preamble_body(new_text)

    out_preamble = inject_diff_packages(diff_preamble_tables(old_preamble, new_preamble))

    old_segs = segment_text(old_body)
    new_segs = segment_text(new_body)
    out_body = diff_segments(old_segs, new_segs)

    legend_page = make_diff_legend_page(old_label, new_label)

    with open(out_path, 'w', encoding='utf-8') as f:
        f.write(out_preamble)
        f.write('\n' + legend_page)
        f.write(out_body)

    n_body = sum(1 for t, _ in new_segs if t == 'table')
    print(f'Written: {out_path}  ({n_body} body table environments processed)')


if __name__ == '__main__':
    main()
