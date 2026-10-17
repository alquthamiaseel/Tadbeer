"""The generated low-fidelity prototype: a file map, not a repository.

The prototype is a **static site** — plain HTML with Tailwind from a CDN — and
that is a deliberate choice over generating a Next.js application.

Vercel serves static files with no build step. A generated Next.js app has to
install dependencies and compile on Vercel's builders, which introduces a class
of failure (a wrong dependency version, a config the model invented) that
surfaces as a red build minutes into a demo and cannot be fixed from Slack. The
plan named that as a risk; removing the build removes the risk entirely rather
than mitigating it.

Nothing about a *low-fidelity* prototype needs a framework. What it needs is to
load instantly and show the screens the plan promised.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

#: Extensions a generated prototype may contain. Anything else is either a
#: build artifact it should not have, or something the model has invented.
ALLOWED_EXTENSIONS = frozenset({".html", ".css", ".js", ".json", ".md", ".svg", ".txt"})

#: The entry point Vercel serves at "/". Its absence means a blank deployment.
ENTRY_POINT = "index.html"

#: Generous for hand-written HTML, small enough that a runaway generation is
#: caught before it reaches GitHub.
MAX_TOTAL_BYTES = 2_000_000
MAX_FILES = 20


class PrototypeFile(BaseModel):
    path: str = Field(
        description=(
            "Repository-relative file path such as index.html or styles.css. "
            "No leading slash, no .. segments, no directories above the root."
        )
    )
    contents: str = Field(description="Complete file contents")


class Screen(BaseModel):
    name: str = Field(description="Screen name as a user would describe it")
    path: str = Field(description="The file that renders this screen, e.g. events.html")
    purpose: str = Field(description="One sentence on what the user does on this screen")


class Prototype(BaseModel):
    """A self-contained static prototype of the planned system."""

    app_name: str = Field(description="Product name shown in the prototype")
    tagline: str = Field(description="One line describing the product")
    screens: list[Screen] = Field(
        description="The landing page plus one screen per major feature, three to six in total"
    )
    files: list[PrototypeFile] = Field(
        description=f"Every file in the prototype. Must include {ENTRY_POINT}."
    )
    notes: list[str] = Field(description="What this prototype deliberately fakes or leaves out")

    def file_map(self) -> dict[str, str]:
        return {file.path: file.contents for file in self.files}


def path_problem(path: str) -> str | None:
    """Why ``path`` is not safe to write, or None if it is fine.

    These files are written into a real GitHub repository and served from a real
    domain, so a generated path is untrusted input like any other.
    """
    if not path or path != path.strip():
        return "is empty or padded with whitespace"
    if path.startswith("/") or path.startswith("~"):
        return "must be relative to the repository root"
    if "\\" in path:
        return "must use forward slashes"
    parts = path.split("/")
    if any(part in ("", ".", "..") for part in parts):
        return "must not contain empty or relative path segments"
    if len(parts) > 3:
        return "is nested more deeply than a low-fidelity prototype needs"
    suffix = path[path.rfind(".") :] if "." in parts[-1] else ""
    if suffix.lower() not in ALLOWED_EXTENSIONS:
        allowed = ", ".join(sorted(ALLOWED_EXTENSIONS))
        return f"has extension {suffix or '(none)'}, which is not one of {allowed}"
    return None


def problems(prototype: Prototype) -> list[str]:
    """Everything that would make this prototype unsafe or broken to deploy."""
    found: list[str] = []
    paths = [file.path for file in prototype.files]

    if not prototype.files:
        found.append("the prototype contains no files")
    if ENTRY_POINT not in paths:
        found.append(f"there is no {ENTRY_POINT}, so the deployment would serve nothing")
    if len(paths) != len(set(paths)):
        duplicates = sorted({p for p in paths if paths.count(p) > 1})
        found.append(f"duplicate file paths: {', '.join(duplicates)}")
    if len(paths) > MAX_FILES:
        found.append(f"{len(paths)} files exceeds the {MAX_FILES}-file limit")

    for file in prototype.files:
        problem = path_problem(file.path)
        if problem:
            found.append(f"path {file.path!r} {problem}")

    total = sum(len(file.contents.encode()) for file in prototype.files)
    if total > MAX_TOTAL_BYTES:
        found.append(f"total size {total} bytes exceeds {MAX_TOTAL_BYTES}")

    for screen in prototype.screens:
        if screen.path not in paths:
            found.append(
                f"screen {screen.name!r} points at {screen.path!r}, which was not generated"
            )

    return found
