#!/usr/bin/env python3
"""Static consistency checks for the frontend.

Why this exists
---------------
This environment has no npm registry access, so `tsc` and `vite build` cannot
run here. That leaves four bug classes that a type-checker would normally catch
and that are otherwise invisible until runtime:

  1. A relative import that points at a file which does not exist.
  2. A named import that the target module does not export. TypeScript catches
     this; nothing else does. It is the single most likely way a refactor
     silently breaks a page.
  3. A `Link to=` or `navigate()` target with no matching route in App.tsx. The
     user sees a blank page and no error.
  4. A `var(--token)` referencing a custom property that was never defined. The
     page renders with a transparent or black element instead of failing.

The checks are deliberately syntactic and dependency-free. They are not a
substitute for a compiler -- they do not check types -- but each one is written
to fail loudly on a planted defect rather than to pass quietly.

Usage
-----
    python3 check_static.py            # run all checks
    python3 check_static.py --verbose  # list every file inspected
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

SKIP_DIRS = {"node_modules", "dist", ".vite", "build", ".git"}
SOURCE_EXTS = (".ts", ".tsx")
STYLE_EXTS = (".css",)

# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    files_checked: int = 0
    imports_checked: int = 0
    routes_checked: int = 0
    tokens_checked: int = 0

    def error(self, where: str, message: str) -> None:
        self.errors.append(f"{where}: {message}")

    def warn(self, where: str, message: str) -> None:
        self.warnings.append(f"{where}: {message}")


# --------------------------------------------------------------------------
# File discovery
# --------------------------------------------------------------------------


def walk(root: str, exts: tuple[str, ...]) -> list[str]:
    found: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for name in filenames:
            if name.endswith(exts):
                found.append(os.path.join(dirpath, name))
    return sorted(found)


def rel(root: str, path: str) -> str:
    return os.path.relpath(path, root).replace(os.sep, "/")


# --------------------------------------------------------------------------
# Pass 1 + 2: imports
# --------------------------------------------------------------------------

# Matches: import X from './y'   |   import { a, b } from './y'
#          import type { a } from './y'  |  import './y'
IMPORT_RE = re.compile(
    r"""import\s+(?:type\s+)?(?P<clause>[^;'"]*?)\s*from\s*['"](?P<spec>[^'"]+)['"]""",
    re.VERBOSE,
)

# Matches a bare side-effect import: import './styles.css'
BARE_IMPORT_RE = re.compile(r"""^\s*import\s+['"](?P<spec>[^'"]+)['"]""", re.MULTILINE)

# Named-import braces inside an import clause.
NAMED_RE = re.compile(r"\{(?P<body>[^}]*)\}")


def resolve_local(path: str) -> str | None:
    """Resolve a relative import spec to a file on disk, or None."""
    if os.path.isfile(path):
        return path
    for ext in SOURCE_EXTS + STYLE_EXTS + (".json",):
        candidate = path + ext
        if os.path.isfile(candidate):
            return candidate
    for ext in SOURCE_EXTS:
        candidate = os.path.join(path, "index" + ext)
        if os.path.isfile(candidate):
            return candidate
    return None


def exports_of(source: str, path: str) -> set[str]:
    """Collect the names a TypeScript module exports.

    Handles the declaration forms used in this codebase plus barrel re-exports.
    Default exports are recorded under the sentinel ``default``.
    """
    names: set[str] = set()

    declaration = re.compile(
        r"""export\s+(?:declare\s+)?(?:async\s+)?"""
        r"""(?:function|class|const|let|var|interface|type|enum)\s+([A-Za-z_$][\w$]*)"""
    )
    for match in declaration.finditer(source):
        names.add(match.group(1))

    # export { a, b as c }   /   export type { a }   /   export { a } from './x'
    for match in re.finditer(r"""export\s+(?:type\s+)?\{([^}]*)\}""", source):
        for part in match.group(1).split(","):
            part = part.strip()
            if not part:
                continue
            if " as " in part:
                part = part.split(" as ")[-1].strip()
            # `export { default as Foo }` yields Foo
            names.add(part)

    if re.search(r"""export\s+default\b""", source):
        names.add("default")

    return names


def strip_import_clause(clause: str) -> tuple[str | None, list[str]]:
    """Split an import clause into (default name, [named imports])."""
    clause = clause.strip()
    default_name = None
    named: list[str] = []

    named_match = NAMED_RE.search(clause)
    if named_match:
        for part in named_match.group("body").split(","):
            part = part.strip()
            if not part:
                continue
            # `import { type Column }` -- the type modifier is not part of the
            # exported name.
            part = re.sub(r"^type\s+", "", part).strip()
            if " as " in part:
                part = part.split(" as ")[0].strip()
            if part:
                named.append(part)
        clause = clause[: named_match.start()].strip().rstrip(",").strip()

    # Anything left that is not a namespace import is the default name.
    if clause and not clause.startswith("*"):
        default_name = clause.split(",")[0].strip()

    return default_name, named


def check_imports(root: str, files: list[str], report: Report) -> None:
    module_exports: dict[str, set[str]] = {}

    for path in files:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        module_exports[path] = exports_of(source, path)

    for path in files:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        here = rel(root, path)
        directory = os.path.dirname(path)

        specs = [m.group("spec") for m in IMPORT_RE.finditer(source)]
        specs += [
            m.group("spec")
            for m in BARE_IMPORT_RE.finditer(source)
            if relative_module(m.group("spec"))
        ]

        for spec in set(specs):
            if not relative_module(spec):
                continue  # external package (react, lucide-react, ...)
            report.imports_checked += 1

            target = resolve_local(os.path.normpath(os.path.join(directory, spec)))
            if target is None:
                report.error(here, f"import '{spec}' does not resolve to a file")
                continue

            if not target.endswith(SOURCE_EXTS):
                continue  # css/json: nothing to check beyond existence

            available = module_exports.get(target, set())
            if not available:
                report.warn(
                    here, f"import '{spec}' resolves to a module with no exports"
                )
                continue

            for match in IMPORT_RE.finditer(source):
                if match.group("spec") != spec:
                    continue
                default_name, named = strip_import_clause(match.group("clause"))
                line = source[: match.start()].count("\n") + 1

                if default_name and "default" not in available:
                    report.error(
                        f"{here}:{line}",
                        f"default import '{default_name}' from "
                        f"{rel(root, target)}, which has no default export",
                    )
                for name in named:
                    if name not in available:
                        report.error(
                            f"{here}:{line}",
                            f"'{name}' is not exported by {rel(root, target)}",
                        )


def relative_module(spec: str) -> bool:
    return spec.startswith("./") or spec.startswith("../")


# --------------------------------------------------------------------------
# Pass 3: routes vs. navigation targets
# --------------------------------------------------------------------------

ROUTE_RE = re.compile(r"""<Route\s+[^>]*?path=["'](?P<path>[^"']+)["']""", re.DOTALL)
TO_RE = re.compile(r"""\bto=["'](?P<path>/[^"'${}]*)["']""")
TO_TEMPLATE_RE = re.compile(r"""\bto=\{`(?P<path>/[^`]*)`\}""")
NAVIGATE_RE = re.compile(r"""navigate\(\s*[`'"](?P<path>/[^`'"]*)[`'"]""")


def route_matches(route: str, target: str) -> bool:
    """True when `target` could be produced by `route`.

    Route segments beginning with ':' match exactly one target segment, and a
    trailing '*' matches the rest.
    """
    if route.endswith("/*"):
        prefix = route[:-2]
        return target == prefix or target.startswith(prefix + "/")

    route_parts = [p for p in route.split("/") if p]
    target_parts = [p for p in target.split("/") if p]
    if len(route_parts) != len(target_parts):
        return False
    for rp, tp in zip(route_parts, target_parts):
        if rp.startswith(":"):
            continue
        if rp != tp:
            return False
    return True


def check_routes(root: str, files: list[str], report: Report) -> None:
    app = os.path.join(root, "src", "App.tsx")
    if not os.path.isfile(app):
        report.error("src/App.tsx", "route table not found; cannot verify links")
        return

    with open(app, encoding="utf-8") as handle:
        app_source = handle.read()

    routes = sorted({m.group("path") for m in ROUTE_RE.finditer(app_source)})
    if not routes:
        report.error("src/App.tsx", "no <Route path=...> declarations found")
        return

    redirects = {m.group("path") for m in ROUTE_RE.finditer(app_source)}
    del redirects  # redirect targets are covered by the same route set

    for path in files:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        here = rel(root, path)

        candidates: list[tuple[int, str]] = []
        for regex in (TO_RE, TO_TEMPLATE_RE, NAVIGATE_RE):
            for match in regex.finditer(source):
                line = source[: match.start()].count("\n") + 1
                candidates.append((line, match.group("path")))

        for line, target in candidates:
            # A template literal may embed an id: /cases/${row.id}. Replace the
            # interpolations with a placeholder segment before matching.
            normalised = re.sub(r"\$\{[^}]*\}", "ID", target)
            report.routes_checked += 1
            if not any(route_matches(route, normalised) for route in routes):
                report.error(
                    f"{here}:{line}",
                    f"'{target}' matches no route in App.tsx "
                    f"(known: {', '.join(routes)})",
                )


# --------------------------------------------------------------------------
# Pass 4: CSS custom properties
# --------------------------------------------------------------------------

DEFINE_RE = re.compile(r"^\s*(?P<name>--[\w-]+)\s*:", re.MULTILINE)
USE_RE = re.compile(r"var\(\s*(?P<name>--[\w-]+)")


def check_tokens(root: str, files: list[str], report: Report) -> None:
    styles = walk(root, STYLE_EXTS)
    defined: set[str] = set()
    for path in styles:
        with open(path, encoding="utf-8") as handle:
            defined.update(m.group("name") for m in DEFINE_RE.finditer(handle.read()))

    if not defined:
        report.error("src/index.css", "no CSS custom properties are defined")
        return

    for path in styles + files:
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        here = rel(root, path)
        for match in USE_RE.finditer(source):
            name = match.group("name")
            report.tokens_checked += 1
            if name not in defined:
                line = source[: match.start()].count("\n") + 1
                report.error(
                    f"{here}:{line}", f"'{name}' is used but never defined"
                )


# --------------------------------------------------------------------------
# Entry point
# --------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument(
        "--root",
        default=os.path.dirname(os.path.abspath(__file__)),
        help="frontend directory (defaults to the script's own directory)",
    )
    args = parser.parse_args()

    root = os.path.abspath(args.root)
    files = walk(os.path.join(root, "src"), SOURCE_EXTS)
    report = Report(files_checked=len(files))

    if not files:
        print("no TypeScript sources found under src/", file=sys.stderr)
        return 2

    check_imports(root, files, report)
    check_routes(root, files, report)
    check_tokens(root, files, report)

    if args.verbose:
        for path in files:
            print(f"  inspected {rel(root, path)}")

    for warning in report.warnings:
        print(f"WARN  {warning}")
    for error in report.errors:
        print(f"ERROR {error}")

    print(
        f"\nfrontend check: {report.files_checked} module(s), "
        f"{report.imports_checked} import(s), "
        f"{report.routes_checked} navigation target(s), "
        f"{report.tokens_checked} token use(s) -> "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
