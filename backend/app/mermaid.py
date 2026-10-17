"""A structural check on generated Mermaid source.

The DESIGN stage constrains the model to a schema, but a schema can only say
"this field is a string" — it cannot say "this string parses as Mermaid". A
diagram that fails to parse is invisible until it reaches the dashboard or a
README, by which point the run is finished and the demo is live.

So the source is checked here and the stage re-prompts once on failure. The
check is deliberately structural rather than a real parser: a Mermaid parser
means Node and a subprocess, and the failures that actually happen are a small,
well-known set.

The one that dominates is unquoted punctuation in a node label. ``A[Log in
(SSO)]`` is a parse error; ``A["Log in (SSO)"]`` is fine. The model is told to
quote every label, and :func:`check` enforces it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

#: Every diagram header Mermaid recognises that this project might produce.
KNOWN_HEADERS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "erDiagram",
    "stateDiagram-v2",
    "stateDiagram",
    "journey",
    "gantt",
    "C4Context",
    "C4Container",
    "C4Component",
)

#: Lines that may legally precede the diagram header.
_PREAMBLE = re.compile(r"^\s*(%%.*|---|title:.*|config:.*|\s*)$")

#: A node label: an opening bracket, a non-greedy label, the first closer. Kept
#: non-greedy on purpose — for ``A[Log in (SSO)]`` it captures ``Log in (SSO``,
#: which is exactly the unbalanced content that has to be reported.
_LABEL = re.compile(r"([\[\({]{1,2})([^\n]*?)([\]\)}]{1,2})")

#: Characters that genuinely break an unquoted label. Colons and commas are
#: deliberately absent: Mermaid tolerates them, and flagging them would cost a
#: re-prompt for a diagram that would have rendered.
_NEEDS_QUOTING = re.compile(r"""[(){}\[\]<>#;"']""")

#: Entity-relationship cardinality, e.g. ``||--o{`` in ``CUSTOMER ||--o{ ORDER``.
#: These braces and pipes are operators, not brackets, so they are removed
#: before the balance check rather than counted by it.
_ER_CARDINALITY = re.compile(r"[|}o]{1,2}(?:--|\.\.)[|{o]{1,2}")


@dataclass
class MermaidProblem:
    line: int
    message: str

    def __str__(self) -> str:
        return f"line {self.line}: {self.message}"


def strip_fences(source: str) -> str:
    """Remove markdown code fences the model sometimes wraps around the source."""
    text = source.strip()
    if not text.startswith("```"):
        return text
    lines = text.splitlines()
    lines = lines[1:]
    while lines and lines[-1].strip().startswith("```"):
        lines.pop()
    return "\n".join(lines).strip()


def header_of(source: str) -> str | None:
    """The diagram type this source declares, or None if it declares none."""
    for line in strip_fences(source).splitlines():
        if _PREAMBLE.match(line):
            continue
        stripped = line.strip()
        for header in KNOWN_HEADERS:
            if stripped == header or stripped.startswith(header + " "):
                return header
        return None
    return None


def check(source: str, *, expected_headers: tuple[str, ...] = ()) -> list[MermaidProblem]:
    """Structural problems in ``source``. An empty list means it looks parseable."""
    text = strip_fences(source)
    if not text:
        return [MermaidProblem(1, "the diagram is empty")]

    problems: list[MermaidProblem] = []

    header = header_of(text)
    if header is None:
        first = next((ln.strip() for ln in text.splitlines() if ln.strip()), "")
        problems.append(
            MermaidProblem(
                1,
                f"does not start with a Mermaid diagram type (found {first[:40]!r}); "
                f"expected one of {', '.join(expected_headers or KNOWN_HEADERS)}",
            )
        )
    elif expected_headers and header not in expected_headers:
        problems.append(
            MermaidProblem(
                1, f"is a {header} diagram but should be one of {', '.join(expected_headers)}"
            )
        )

    problems.extend(_label_problems(text))
    problems.extend(_balance_problems(text))
    return problems


def _label_problems(text: str) -> list[MermaidProblem]:
    """Node labels whose content needs quoting but is not quoted."""
    problems: list[MermaidProblem] = []
    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("%%"):
            continue
        line = _ER_CARDINALITY.sub(" ", line)
        for _, label, _ in _LABEL.findall(line):
            content = label.strip()
            if not content or content.startswith('"') or content.startswith("'"):
                continue
            if _NEEDS_QUOTING.search(content):
                problems.append(
                    MermaidProblem(
                        number,
                        f"node label {content[:40]!r} contains punctuation and must be "
                        'quoted, as in A["like this"]',
                    )
                )
    return problems


def _balance_problems(text: str) -> list[MermaidProblem]:
    """Brackets left open outside of quoted strings."""
    pairs = {")": "(", "]": "[", "}": "{"}
    stack: list[tuple[str, int]] = []
    in_quote: str | None = None

    for number, line in enumerate(text.splitlines(), start=1):
        if line.strip().startswith("%%"):
            continue
        line = _ER_CARDINALITY.sub(" ", line)
        for char in line:
            if in_quote:
                if char == in_quote:
                    in_quote = None
                continue
            if char in "\"'":
                in_quote = char
            elif char in "([{":
                stack.append((char, number))
            elif char in ")]}" and stack and stack[-1][0] == pairs[char]:
                stack.pop()
            elif char in ")]}":
                return [MermaidProblem(number, f"unmatched closing {char!r}")]
        in_quote = None  # quotes do not span lines in Mermaid

    if stack:
        char, number = stack[-1]
        return [MermaidProblem(number, f"unclosed {char!r}")]
    return []


def describe(problems: list[MermaidProblem]) -> str:
    return "; ".join(str(problem) for problem in problems)
