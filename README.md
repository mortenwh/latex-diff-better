# Latex-diff-better

The regular latexdiff perl script fails to catch changes in documents using the
csvlongtable package, because it does not easily catch changes in the csv
files.

This tool is meant to more easily create diffs between versions of more
complicated documents.

Created with the help of GitHub Copilot and Claude Sonnet 4.6.


# HOW TO READ THE gitdiff.tex OUTPUT

## COLOUR CODING QUICK REFERENCE

  GREEN background (\rowcolor{diffadd})      : table row was added in the new version
  PINK  background (\rowcolor{diffdel})      : table row was deleted from the old version
  MIXED background (\cellcolor{diffdel!50!diffadd!50}) : individual cell was changed;
                                               old content shown in red/strikethrough,
                                               new content shown in green

  Green text   \textcolor{ao}{...}          : added text (outside tables)
  Red+strikethrough \textcolor{BUR}{\sout{...}} : deleted text (outside tables, simple)
  Red text (no strikethrough) {\color{BUR}...}  : deleted text that contains LaTeX
                                               commands (\url, \newline, \includegraphics,
                                               etc.) — these cannot safely go inside \sout{}

  Commented-out lines  % DIFF-DEL: ...      : deleted lines that contain \begin{}, \end{},
                                               or have unbalanced braces — they are
                                               commented out so the file still compiles


## INSIDE TABLE CELLS

When a cell value changed, the cell gets a neutral (salmon/yellow) background and shows:
  - Old words in red + strikethrough
  - New words in green

Example:  \cellcolor{diffdel!50!diffadd!50}\textcolor{BUR}{\sout{old}} \textcolor{ao}{new}


## ALL-RED TABLES

A table with ALL rows in pink/red background means the entire table was deleted (no
matching new table could be paired with it by the diff algorithm).  There are two reasons
this can happen:

1. The table's section was ENTIRELY REMOVED from the document.
   You will see the section heading itself in red text, e.g.:
       {\color{BUR}\subsubsection{Reliability, availability, maintainability, and safety}}
   This is correct — the section and its requirements no longer exist.

2. The old and new versions of a table could not be automatically paired because the
   document was restructured (tables moved between sections, or the table changed so
   many rows that the diff engine treated them as unrelated).
   In this case the old table appears as all-red and a separate all-green table (the new
   version) appears nearby.

In the current gitdiff.tex there are 15 all-red tables, grouped as follows:

  Deleted sections (correct — whole section removed):
    - {\color{BUR}\subsubsection{RAM}} requirements (L2O-SW context)
    - {\color{BUR}\subsubsection{INT}} requirements
    - {\color{BUR}\subsubsection{QUA}} requirements
    - {\color{BUR}\subsubsection{DES}} requirements
    - {\color{BUR}\subsubsection{FUN}} requirements
    - {\color{BUR}\subsubsection{DES}} requirements (software design appendix)
    - {\color{BUR}\subsubsection{DEL}} delivery requirements
    - {\color{BUR}\subsection{List of requirements to be discussed}} (old TBD list)
    - {\color{BUR}\subsection{Traceability to SoW requirements}} (old trace format)
    - {\color{BUR}\subsection{Traceability to GEN requirements}} (old trace format)

  Surviving sections — old table not paired (a green replacement table is nearby):
    - \subsubsection{RAM} in L2O-IPF section
    - \subsubsection{QUA} in L2O-IPF section
    - \subsubsection{INT} in L2O-IPF section
    - \subsubsection{DES} in L2O-IPF section
    - Small table in "Details on preliminary software design"

The large all-red trace tables at the end of the document (Traceability to SoW/GEN) are
the old format (5-column requirement table) being replaced by the new format (3-column
trace table).  The corresponding new all-green tables follow immediately in the document.


## ALL-GREEN TABLES

Similarly, an all-green table (all rows with green background) means the entire table is
new — it either:
  - belongs to a newly added section, or
  - is the replacement for a nearby all-red table (new format / new content)


## MIXED TABLES (partially red, partially green)

These are tables that exist in both versions and were diffed at row level.  You will see:
  - Green rows  : new requirements added
  - Pink rows   : requirements removed
  - Neutral rows: requirements that changed (cell-level diff inside the row)
  - White rows  : unchanged requirements


## TABLE STRUCTURE CHANGES

When the old table had a different number of columns than the new table (e.g. old had 5
columns, new has 3), deleted rows from the old table are collapsed into a single
\multicolumn cell.  The old column values are joined with " & " (shown as literal
ampersands) and wrapped in strikethrough or red text.


## KNOWN LIMITATIONS

- Tables that moved to a different section may show as separate all-red (deleted) +
  all-green (added) rather than a unified row diff.
- Text lines with unbalanced braces (part of multi-line LaTeX groups) are commented out
  as "% DIFF-DEL:" rather than shown in red.  This is a safety measure to keep the diff
  file compilable.
- The script uses the new document's preamble unchanged, so any preamble changes are NOT
  shown in the diff.


## SCRIPT INVOCATION

Two-file mode (simple):
    python3 latexdiff_better.py old.tex new.tex output.tex

Git mode (multi-file document with CSV tables):
    python3 latexdiff_better.py --git <old_commit> <main.tex> output.tex
