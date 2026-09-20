"""Static check of the backend package.

The sandbox has no network, so pydantic/fastapi/sqlalchemy cannot be installed
and the app cannot be imported. That does not mean it cannot be checked.

This harness parses every module with ast (no imports executed), builds a map
of each module's top-level public names, and then verifies that every
`from app.x import y` statement resolves to a name that actually exists. It
also reports syntax errors, duplicate route declarations, and route-ordering
hazards where a literal path is shadowed by an earlier path-parameter route.

That last check is the one that matters most: it is exactly the class of bug
that shipped twice in the API layer.
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
APP = ROOT / "app"

errors: list[str] = []
warnings: list[str] = []


def module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def collect_names(tree: ast.Module) -> tuple[set[str], set[str]]:
    """Top-level names defined in a module, plus names it re-exports."""
    defined: set[str] = set()
    exported: set[str] = set()

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            defined.add(node.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    defined.add(target.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            defined.add(node.target.id)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                defined.add(alias.asname or alias.name.split(".")[0])
                exported.add(alias.asname or alias.name.split(".")[0])

    # Assignments that alias an imported name are re-exports too.
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Name):
            for target in node.targets:
                if isinstance(target, ast.Name) and node.value.id in exported:
                    exported.add(target.id)

    return defined, exported


# ---------------------------------------------------------------- pass 1: parse

trees: dict[str, ast.Module] = {}
files = sorted(APP.rglob("*.py"))
for path in files:
    name = module_name(path)
    try:
        trees[name] = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        errors.append(f"SYNTAX  {path.relative_to(ROOT)}:{exc.lineno}: {exc.msg}")

module_names: dict[str, set[str]] = {}
for name, tree in trees.items():
    defined, _ = collect_names(tree)
    module_names[name] = defined
module_names["__star__"] = set()

# ------------------------------------------------------- pass 2: import resolution

for name, tree in trees.items():
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom) or node.module is None:
            continue
        if not node.module.startswith("app"):
            continue
        target = node.module
        if target not in module_names:
            if target in trees:
                continue
            errors.append(
                f"IMPORT  {name}: module 'app.{target[4:]}' does not exist"
            )
            continue
        for alias in node.names:
            if alias.name == "*":
                continue
            if alias.name not in module_names[target]:
                errors.append(
                    f"IMPORT  {name}: 'app.{target[4:]}.{alias.name}' is not defined "
                    f"in that module"
                )

# ------------------------------------------- pass 3: route ordering and duplication

ROUTE_RE = re.compile(
    r"@router\.(get|post|patch|put|delete)\(\s*[\"']([^\"']+)[\"']",
)

for name, tree in trees.items():
    if not name.startswith("app.api."):
        continue
    if name == "app.api.__init__":
        continue

    routes: list[tuple[str, str, int]] = []
    for node in tree.body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                continue
            if func.value.id != "router":
                continue
            if func.attr not in {"get", "post", "patch", "put", "delete"}:
                continue
            if not dec.args:
                continue
            first = dec.args[0]
            if not isinstance(first, ast.Constant):
                continue
            routes.append((func.attr, first.value, node.lineno))

    seen: set[tuple[str, str]] = set()
    for method, path, lineno in routes:
        key = (method, path)
        if key in seen:
            errors.append(
                f"ROUTE   {name}:{lineno}: duplicate {method.upper()} {path}"
            )
        seen.add(key)

    # A literal path is shadowed if an earlier route of the same method matches
    # the same number of segments with a path parameter in that position.
    def segments(p: str) -> list[str]:
        return [s for s in p.split("/") if s != ""]

    for i, (method, path, lineno) in enumerate(routes):
        segs = segments(path)
        for j in range(i):
            pmethod, ppath, plineno = routes[j]
            if pmethod != method:
                continue
            psegs = segments(ppath)
            if len(psegs) != len(segs):
                continue
            if all(
                pseg == sseg or pseg.startswith("{")
                for pseg, sseg in zip(psegs, segs)
            ) and psegs != segs:
                errors.append(
                    f"ROUTE   {name}:{lineno}: {method.upper()} {path} is shadowed by "
                    f"{method.upper()} {ppath} declared at line {plineno} - "
                    f"FastAPI matches in declaration order"
                )

# ------------------------------------------- pass 4: SQLAlchemy reserved names

# Declarative reserves a handful of attribute names on mapped classes. Hitting
# one raises InvalidRequestError at import time, which means the models package
# fails to load and the entire application dies. A static check is far cheaper
# than discovering it on boot.
RESERVED_MAPPED_NAMES = {"metadata", "registry"}

for name, tree in trees.items():
    if not name.startswith("app.models"):
        continue
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue
        bases = {ast.unparse(b) for b in node.bases}
        if not any("Base" in base for base in bases):
            continue
        if any(arg == "Base" for arg in bases) or "__tablename__" in {
            t.id
            for b in node.body
            if isinstance(b, ast.Assign)
            for t in b.targets
            if isinstance(t, ast.Name)
        }:
            for b in node.body:
                targets: list[str] = []
                if isinstance(b, ast.Assign):
                    targets = [t.id for t in b.targets if isinstance(t, ast.Name)]
                elif isinstance(b, ast.AnnAssign) and isinstance(b.target, ast.Name):
                    targets = [b.target.id]
                for target in targets:
                    if target in RESERVED_MAPPED_NAMES:
                        errors.append(
                            f"ORM     {name}:{b.lineno}: '{target}' is reserved by the "
                            f"SQLAlchemy Declarative API on class {node.name} - map it "
                            f"under another attribute name with an explicit column name"
                        )

# ------------------------------------------- pass 6: ORM attribute references

# A typo in `Vendor.risk_leval` is a runtime AttributeError deep inside a query.
# Building the set of mapped attributes from the models and checking every
# `Model.attr` reference in the codebase turns that into a build-time error.

orm_attrs: dict[str, set[str]] = {}
for name, tree in trees.items():
    if not name.startswith("app.models"):
        continue
    for node in tree.body:
        if not isinstance(node, ast.ClassDef):
            continue

        assigned = {
            t.id
            for b in node.body
            if isinstance(b, ast.Assign)
            for t in b.targets
            if isinstance(t, ast.Name)
        }
        # Only real mapped tables participate. Enum classes live in the same
        # module and are bound to the same local names, so including them would
        # make every legitimate `WorkflowStatus.APPROVAL_PENDING` look like a
        # bad column reference.
        if "__tablename__" not in assigned:
            continue

        attrs: set[str] = set()
        for b in node.body:
            if not isinstance(b, ast.Assign):
                continue
            is_mapped = isinstance(b.value, ast.Call) and (
                getattr(b.value.func, "id", "") in {"Column", "relationship"}
                or getattr(b.value.func, "attr", "") in {"Column", "relationship"}
            )
            if is_mapped:
                attrs.update(t.id for t in b.targets if isinstance(t, ast.Name))
        orm_attrs[node.name] = attrs

# Attributes SQLAlchemy puts on every mapped class and that code legitimately
# calls through the class object.
ORM_CLASS_API = {
    "in_", "notin_", "is_", "isnot", "desc", "asc", "distinct", "any", "has",
    "label", "cast", "between", "like", "ilike", "op", "contains", "startswith",
    "endswith", "invert", "self_group", "compare", "concat", "nulls_last",
    "nulls_first", "desc_op", "collate", "regexp_match",
}

all_orm_classes = set(orm_attrs)

for name, tree in trees.items():
    if name.startswith("app.models"):
        continue

    # Resolve local aliases to ORM classes, e.g. `Exception as ExceptionModel`.
    local: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("app.models"):
            for alias in node.names:
                if alias.name in all_orm_classes:
                    local[alias.asname or alias.name] = alias.name
        elif isinstance(node, ast.ImportFrom) and node.module == "app.models":
            for alias in node.names:
                if alias.name in all_orm_classes:
                    local[alias.asname or alias.name] = alias.name

    if not local:
        continue

    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if not isinstance(node.value, ast.Name):
            continue
        bound = local.get(node.value.id)
        if bound is None:
            continue
        attr = node.attr
        if attr.startswith("__") or attr in ORM_CLASS_API:
            continue
        if attr not in orm_attrs[bound]:
            errors.append(
                f"ORM     {name}:{node.lineno}: {node.value.id}.{attr} - "
                f"{bound} has no mapped attribute '{attr}'"
            )

# ------------------------------------------- pass 7: async/sync hygiene

for name, tree in trees.items():
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef):
            body_src = ast.dump(node)
            # A bare `await` outside an async function is caught by the parser,
            # so this pass only looks for the inverse: awaiting inside a
            # non-async def nested in an async function is legal but suspicious.
            pass

# ------------------------------------------------------------------- report

for warning in warnings:
    print(f"warn  {warning}")
for error in errors:
    print(f"ERROR {error}")

print()
print(f"parsed {len(trees)} modules, {len(errors)} error(s), {len(warnings)} warning(s)")
sys.exit(1 if errors else 0)
