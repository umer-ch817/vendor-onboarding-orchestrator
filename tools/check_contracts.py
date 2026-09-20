#!/usr/bin/env python3
"""Frontend/backend contract check.

Why this exists
---------------
`frontend/src/types/index.ts` opens with this instruction:

    "Keep these in sync with backend/app/schemas/__init__.py. If the backend
     changes, the frontend types must change."

That is an invariant stated in a comment, which means nothing enforces it. It
is also an invariant TypeScript cannot check, because it describes a runtime
JSON payload rather than a compile-time type. A drift in either direction fails
silently:

  * A field the frontend declares but the backend never sends reads as
    ``undefined``. The page renders an empty cell and no error is raised. This
    is the dangerous direction -- it is exactly the shape of the bug where the
    list response models were assumed to use ``items`` and actually use
    ``cases``.

  * A field the backend sends but the frontend omits is harmless at runtime but
    means the UI cannot use data the API is already paying to serialize.

This script parses both sides statically and compares them.

It is intentionally dependency-free: this environment has no access to the
Python package index, so it cannot import Pydantic to introspect the real
models. It reads the source instead -- which is the same source a reviewer
would read, so a disagreement between this checker and the models is itself a
finding.

Usage
-----
    python3 tools/check_contracts.py
    python3 tools/check_contracts.py --allow-missing   # exit 0 on drift
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field

# ---------------------------------------------------------------------------
# The explicit mapping between a frontend interface and its backend model.
#
# This is written out rather than inferred because the two sides use different
# naming conventions on purpose: the API names the transport shape
# (``VendorResponse``) while the frontend names the domain concept (``Vendor``).
# A convention-based guess would be wrong for every one of these, and a wrong
# guess here would make the whole check meaningless.
# ---------------------------------------------------------------------------

TYPE_MAP: dict[str, str] = {
    "Vendor": "VendorResponse",
    "VendorCreate": "VendorCreate",
    "VendorUpdate": "VendorUpdate",
    "VendorListResponse": "VendorListResponse",
    "OnboardingCase": "OnboardingCaseResponse",
    "OnboardingCaseCreate": "OnboardingCaseCreate",
    "OnboardingCaseUpdate": "OnboardingCaseUpdate",
    "OnboardingCaseListResponse": "OnboardingCaseListResponse",
    "OnboardingCaseDetail": "OnboardingCaseDetail",
    "Document": "DocumentResponse",
    "DocumentWithExtraction": "DocumentWithExtraction",
    "DocumentListResponse": "DocumentListResponse",
    "ExtractedField": "ExtractedFieldResponse",
    "RiskSignal": "RiskSignalResponse",
    "RiskAssessment": "RiskAssessmentResponse",
    "CaseRiskView": "",  # not a Pydantic model: shaped by hand in risk_service
    "Exception": "ExceptionResponse",
    "ExceptionListResponse": "ExceptionListResponse",
    "ExceptionResolve": "ExceptionResolve",
    "Approval": "ApprovalResponse",
    "ApprovalListResponse": "ApprovalListResponse",
    "ApprovalCreate": "ApprovalCreate",
    "ApprovalDecision": "ApprovalDecision",
    "AuditEvent": "AuditEventResponse",
    "AuditEventListResponse": "AuditEventListResponse",
    "DashboardMetrics": "DashboardMetrics",
}

# Fields the frontend declares that legitimately have no backend counterpart.
# Each needs a reason, so the exemption list cannot quietly grow.
ALLOWED_FRONTEND_ONLY: dict[str, dict[str, str]] = {
    "CaseRiskView": {
        "*": "Hand-shaped dict from RiskService, not a Pydantic model.",
    },
    "DashboardMetrics": {
        "by_status": "Added by the plain-dict handler at GET /dashboard/, not the model.",
        "risk_distribution": "Added by the plain-dict handler at GET /dashboard/.",
        "exceptions_by_severity": "Added by the plain-dict handler at GET /dashboard/.",
        "needs_attention": "Added by the plain-dict handler at GET /dashboard/.",
        "definitions": "Added by the plain-dict handler at GET /dashboard/.",
        "dataset_label": "Added by the plain-dict handler at GET /dashboard/.",
    },
}

SKIP_MODEL_NAMES = {"BaseModel", "object"}


@dataclass
class Model:
    name: str
    bases: list[str]
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Interface:
    name: str
    bases: list[str]
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    compared: int = 0

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)


# ---------------------------------------------------------------------------
# Backend: Pydantic models
# ---------------------------------------------------------------------------

CLASS_DECL_RE = re.compile(
    r"^class\s+(?P<name>\w+)\s*(?:\((?P<bases>[^)]*)\))?\s*:", re.MULTILINE
)
# A field is 'name: type' at one indent level deeper than the class statement.
FIELD_RE = re.compile(r"^(?P<indent>\s+)(?P<name>[a-z_][\w]*)\s*:\s*(?P<type>.+?)\s*$")


def parse_models(source: str) -> dict[str, Model]:
    """Parse Pydantic model classes and their declared fields."""
    lines = source.splitlines()

    # Locate every class header with its line number and indentation.
    headers: list[tuple[int, int, str, list[str]]] = []
    for index, line in enumerate(lines):
        match = CLASS_DECL_RE.match(line)
        if not match:
            continue
        indent = len(line) - len(line.lstrip())
        bases = [
            base.strip().split("[")[0]
            for base in (match.group("bases") or "").split(",")
            if base.strip()
        ]
        headers.append((index, indent, match.group("name"), bases))

    models: dict[str, Model] = {}
    for position, (start, indent, name, bases) in enumerate(headers):
        # The class body ends at the next class header, or at EOF.
        end = headers[position + 1][0] if position + 1 < len(headers) else len(lines)
        model = Model(name=name, bases=bases)

        for line in lines[start + 1 : end]:
            if not line.strip():
                continue
            body_indent = len(line) - len(line.lstrip())
            # Only direct children of the class body.
            if body_indent != indent + 4:
                continue
            # Skip nested classes (Config), decorators, and methods.
            if line.lstrip().startswith(
                ("class ", "def ", "@", "#", '"""', "'''", "model_config")
            ):
                continue

            match = FIELD_RE.match(line)
            if not match:
                continue
            field_name = match.group("name")
            # ClassVar / private attributes are not part of the wire contract.
            if field_name.startswith("_"):
                continue
            model.fields[field_name] = match.group("type").split("=")[0].strip()

        models[name] = model

    return models


def resolve_model_fields(
    models: dict[str, Model], name: str, seen: set[str] | None = None
) -> dict[str, str]:
    """Flatten a model's fields including those inherited from its bases."""
    seen = seen or set()
    if name in seen or name not in models:
        return {}
    seen.add(name)

    model = models[name]
    resolved: dict[str, str] = {}
    for base in model.bases:
        if base in SKIP_MODEL_NAMES:
            continue
        resolved.update(resolve_model_fields(models, base, seen))
    resolved.update(model.fields)
    return resolved


# ---------------------------------------------------------------------------
# Frontend: TypeScript interfaces
# ---------------------------------------------------------------------------

INTERFACE_RE = re.compile(
    r"^export\s+interface\s+(?P<name>\w+)\s*(?:extends\s+(?P<bases>[^{]*?))?\s*\{",
    re.MULTILINE,
)
TS_FIELD_RE = re.compile(r"^\s{2}(?P<name>[A-Za-z_]\w*)\??\s*:\s*(?P<type>.+?);?\s*$")


def parse_interfaces(source: str) -> dict[str, Interface]:
    interfaces: dict[str, Interface] = {}
    lines = source.splitlines()

    for index, line in enumerate(lines):
        match = INTERFACE_RE.match(line)
        if not match:
            continue

        name = match.group("name")
        bases = [
            base.strip().split("<")[0].strip()
            for base in (match.group("bases") or "").split(",")
            if base.strip()
        ]
        interface = Interface(name=name, bases=bases)

        depth = 1
        for body_line in lines[index + 1 :]:
            depth += body_line.count("{") - body_line.count("}")
            if depth <= 0:
                break
            field_match = TS_FIELD_RE.match(body_line)
            if not field_match:
                continue
            # A method signature is not a field.
            if "(" in field_match.group("type"):
                continue
            interface.fields[field_match.group("name")] = field_match.group("type")

        interfaces[name] = interface

    return interfaces


def resolve_interface_fields(
    interfaces: dict[str, Interface], name: str, seen: set[str] | None = None
) -> dict[str, str]:
    seen = seen or set()
    if name in seen or name not in interfaces:
        return {}
    seen.add(name)

    interface = interfaces[name]
    resolved: dict[str, str] = {}
    for base in interface.bases:
        resolved.update(resolve_interface_fields(interfaces, base, seen))
    resolved.update(interface.fields)
    return resolved


# ---------------------------------------------------------------------------
# Comparison
# ---------------------------------------------------------------------------


def compare(
    models: dict[str, Model],
    interfaces: dict[str, Interface],
    report: Report,
) -> None:
    for ts_name, py_name in sorted(TYPE_MAP.items()):
        if not py_name:
            continue
        if ts_name not in interfaces:
            report.warn(f"types.ts has no interface '{ts_name}' (expected)")
            continue
        if py_name not in models:
            report.error(
                f"backend has no model '{py_name}' for interface '{ts_name}'"
            )
            continue

        report.compared += 1
        ts_fields = resolve_interface_fields(interfaces, ts_name)
        py_fields = resolve_model_fields(models, py_name)

        exempt = ALLOWED_FRONTEND_ONLY.get(ts_name, {})
        wildcard = "*" in exempt

        # Dangerous direction: frontend reads a field the backend never sends.
        for field_name in sorted(set(ts_fields) - set(py_fields)):
            if wildcard or field_name in exempt:
                continue
            report.error(
                f"{ts_name}.{field_name} is declared in types.ts but "
                f"{py_name} never sends it — it will read as undefined"
            )

        # Harmless but worth knowing: the API sends fields the UI cannot use.
        for field_name in sorted(set(py_fields) - set(ts_fields)):
            report.warn(
                f"{py_name}.{field_name} is sent by the API but "
                f"{ts_name} does not declare it"
            )


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main() -> int:
    repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", default=repo)
    parser.add_argument(
        "--allow-missing",
        action="store_true",
        help="report drift but exit 0",
    )
    args = parser.parse_args()

    schemas_path = os.path.join(
        args.repo, "backend", "app", "schemas", "__init__.py"
    )
    types_path = os.path.join(
        args.repo, "frontend", "src", "types", "index.ts"
    )

    for path in (schemas_path, types_path):
        if not os.path.isfile(path):
            print(f"missing required file: {path}", file=sys.stderr)
            return 2

    with open(schemas_path, encoding="utf-8") as handle:
        models = parse_models(handle.read())
    with open(types_path, encoding="utf-8") as handle:
        interfaces = parse_interfaces(handle.read())

    report = Report()
    compare(models, interfaces, report)

    for warning in report.warnings:
        print(f"WARN  {warning}")
    for error in report.errors:
        print(f"ERROR {error}")

    print(
        f"\ncontract check: {len(models)} model(s) parsed, "
        f"{len(interfaces)} interface(s) parsed, "
        f"{report.compared} pair(s) compared -> "
        f"{len(report.errors)} error(s), {len(report.warnings)} warning(s)"
    )
    if args.allow_missing:
        return 0
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
