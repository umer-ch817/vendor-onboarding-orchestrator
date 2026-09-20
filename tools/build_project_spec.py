#!/usr/bin/env python3
"""Build ``project_spec.json`` -- the machine-readable description of the system.

Why this is generated
---------------------
A specification that is written by hand drifts from the code the first time a
route is renamed, and nothing fails when it does. This script reads the
artefacts that actually run -- the FastAPI route decorators, the SQLAlchemy
models, the n8n workflow JSON, the settings class -- and emits a single JSON
document from them. If a route is added, the spec changes; if it is deleted,
the spec changes. There is no second copy to forget.

What is derived vs. declared
----------------------------
Most of the document is parsed from source:

  * enums and tables from ``backend/app/models/__init__.py``
  * endpoints from the ``@router.<verb>(...)`` decorators in ``backend/app/api/``
  * the route prefixes from ``backend/app/api/__init__.py``
  * rule codes from the ``Rule`` subclasses in ``backend/app/rules/engine.py``
  * every tunable from the ``Settings`` class in ``backend/app/config.py``
  * workflow summaries from ``n8n/workflows/*.json``

A few things are genuinely prose -- what a workflow is *for*, what an event
type *means* -- and cannot be recovered from a decorator. Those live in the
``NARRATIVE`` block below and are asserted against the parsed source where an
assertion is possible, so a rename in the code fails this script rather than
producing a spec that quietly disagrees with it.

Usage
-----
    python3 tools/build_project_spec.py            # write project_spec.json
    python3 tools/build_project_spec.py --check    # verify the committed file
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "backend")
API_DIR = os.path.join(BACKEND, "app", "api")
MODELS_FILE = os.path.join(BACKEND, "app", "models", "__init__.py")
ENGINE_FILE = os.path.join(BACKEND, "app", "rules", "engine.py")
SCORING_FILE = os.path.join(BACKEND, "app", "rules", "risk_scoring.py")
CONFIG_FILE = os.path.join(BACKEND, "app", "config.py")
WORKFLOW_DIR = os.path.join(ROOT, "n8n", "workflows")

OUTPUT = os.path.join(ROOT, "project_spec.json")

HTTP_VERBS = {"get", "post", "patch", "put", "delete"}


class SpecError(Exception):
    """Raised when source and the declared narrative disagree."""


# ---------------------------------------------------------------------------
# Small AST helpers
# ---------------------------------------------------------------------------


def parse(path: str) -> ast.Module:
    with open(path, encoding="utf-8") as handle:
        return ast.parse(handle.read(), filename=path)


def literal(node: ast.AST) -> object:
    """Best-effort constant evaluation; returns None when not a literal."""
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def base_names(classdef: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for base in classdef.bases:
        if isinstance(base, ast.Name):
            names.add(base.id)
        elif isinstance(base, ast.Attribute):
            names.add(base.attr)
    return names


def iter_classdefs(module: ast.Module):
    for node in module.body:
        if isinstance(node, ast.ClassDef):
            yield node


# ---------------------------------------------------------------------------
# Enums and tables
# ---------------------------------------------------------------------------


def extract_enums() -> dict[str, list[str]]:
    """Every ``class X(str, PyEnum)`` in the models module, with its values.

    Only model-layer enums are emitted. Pydantic mirrors of them live in the
    schemas module and are kept in step by ``tools/check_contracts.py``; the
    model enum is the one the database stores, so it is the one the spec
    should carry.
    """
    module = parse(MODELS_FILE)
    enums: dict[str, list[str]] = {}

    for classdef in iter_classdefs(module):
        if not base_names(classdef) & {"PyEnum", "Enum"}:
            continue
        values: list[str] = []
        for stmt in classdef.body:
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if isinstance(target, ast.Name):
                    value = literal(stmt.value)
                    if isinstance(value, str):
                        values.append(value)
        if values:
            enums[classdef.name] = values

    return enums


def column_type(node: ast.Call) -> str:
    """Render the first argument of a ``Column(...)`` call as a type name."""
    if not node.args:
        return "Unknown"
    first = node.args[0]
    if isinstance(first, ast.Name):
        return first.id
    if isinstance(first, ast.Attribute):
        return f"{getattr(first.value, 'id', '')}.{first.attr}".lstrip(".")
    return "Unknown"


def extract_models(enums: dict[str, list[str]]) -> list[dict]:
    """Every ``class X(Base)`` in the models module, with its columns."""
    module = parse(MODELS_FILE)
    models: list[dict] = []

    for classdef in iter_classdefs(module):
        if "Base" not in base_names(classdef):
            continue

        table = None
        columns: list[dict] = []
        indexes: list[str] = []
        uniques: list[str] = []
        relationships: list[str] = []

        for stmt in classdef.body:
            # __tablename__ = "..."
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if isinstance(target, ast.Name) and target.id == "__tablename__":
                    table = literal(stmt.value)

            # relationship("X", ...)
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Name) and call.func.id == "relationship":
                    if call.args:
                        related = literal(call.args[0])
                        if isinstance(related, str) and isinstance(stmt.targets[0], ast.Name):
                            relationships.append(
                                f"{stmt.targets[0].id} -> {related}"
                            )

            # name = Column(...)
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.Call):
                call = stmt.value
                if isinstance(call.func, ast.Name) and call.func.id == "Column":
                    if not isinstance(stmt.targets[0], ast.Name):
                        continue
                    column: dict = {
                        "name": stmt.targets[0].id,
                        "type": column_type(call),
                    }
                    for keyword in call.keywords:
                        value = literal(keyword.value)
                        if keyword.arg == "nullable":
                            column["nullable"] = bool(value)
                        elif keyword.arg == "unique":
                            column["unique"] = bool(value)
                        elif keyword.arg == "default" and value is not None:
                            column["default"] = value
                        elif keyword.arg == "primary_key":
                            column["primary_key"] = bool(value)
                    # ForeignKey("table.column") lives in the first argument.
                    if call.args and isinstance(call.args[0], ast.Call):
                        fk_call = call.args[0]
                        if (
                            isinstance(fk_call.func, ast.Name)
                            and fk_call.func.id == "ForeignKey"
                            and fk_call.args
                        ):
                            fk_target = literal(fk_call.args[0])
                            if isinstance(fk_target, str):
                                column["foreign_key"] = fk_target
                    # An Enum(...) column names a model enum.
                    if call.args and isinstance(call.args[0], ast.Call):
                        enum_call = call.args[0]
                        if (
                            isinstance(enum_call.func, ast.Name)
                            and enum_call.func.id == "Enum"
                            and enum_call.args
                        ):
                            enum_name = literal(enum_call.args[0])
                            if isinstance(enum_name, str):
                                column["enum"] = enum_name
                    columns.append(column)

            # __table_args__ = ( Index(...), UniqueConstraint(...) )
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                target = stmt.targets[0]
                if isinstance(target, ast.Name) and target.id == "__table_args__":
                    tuple_node = stmt.value
                    if isinstance(tuple_node, ast.Tuple):
                        for element in tuple_node.elts:
                            if not isinstance(element, ast.Call):
                                continue
                            if isinstance(element.func, ast.Name):
                                if element.func.id == "Index" and element.args:
                                    name = literal(element.args[0])
                                    if isinstance(name, str):
                                        indexes.append(name)
                                elif (
                                    element.func.id == "UniqueConstraint"
                                    and element.args
                                ):
                                    parts = [
                                        literal(a) for a in element.args
                                        if literal(a) is not None
                                    ]
                                    uniques.append("+".join(str(p) for p in parts))

        if table:
            models.append(
                {
                    "table": table,
                    "class": classdef.name,
                    "columns": columns,
                    "indexes": indexes,
                    "unique_constraints": uniques,
                    "relationships": relationships,
                }
            )

    # A model whose enum reference is not a declared enum would produce a spec
    # pointing at nothing; fail loudly instead.
    for model in models:
        for column in model["columns"]:
            enum_name = column.get("enum")
            if enum_name and enum_name not in enums:
                raise SpecError(
                    f"{model['class']}.{column['name']} references undefined enum {enum_name}"
                )

    return models


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


def extract_prefixes() -> dict[str, dict[str, str]]:
    """Map each api module to its mount prefix and tag, by parsing __init__."""
    init_file = os.path.join(API_DIR, "__init__.py")
    module = parse(init_file)

    # `from app.api.vendors import router as vendors_router` binds the alias to
    # the *router object*, so the module it came from is ``node.module`` and
    # not ``alias.name`` (which is just the word "router").
    alias_to_module: dict[str, str] = {}
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom) and node.module:
            module_tail = node.module.rsplit(".", 1)[-1]
            for alias in node.names:
                if alias.asname:
                    alias_to_module[alias.asname] = module_tail

    prefixes: dict[str, dict[str, str]] = {}
    for node in ast.walk(module):
        if not isinstance(node, ast.Call):
            continue
        if not (isinstance(node.func, ast.Attribute) and node.func.attr == "include_router"):
            continue
        if not node.args:
            continue
        first = node.args[0]
        if not isinstance(first, ast.Name):
            continue
        module_name = alias_to_module.get(first.id, first.id)
        prefix = ""
        tag = ""
        for keyword in node.keywords:
            value = literal(keyword.value)
            if keyword.arg == "prefix" and isinstance(value, str):
                prefix = value
            elif keyword.arg == "tags" and isinstance(value, (list, tuple)):
                tag = str(value[0]) if value else ""
        prefixes[module_name] = {"prefix": prefix, "tag": tag}

    return prefixes


def extract_endpoints() -> list[dict]:
    prefixes = extract_prefixes()
    endpoints: list[dict] = []

    for filename in sorted(os.listdir(API_DIR)):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        module_name = filename[:-3]
        mount = prefixes.get(module_name, {"prefix": "", "tag": ""})
        path_file = os.path.join(API_DIR, filename)
        module = parse(path_file)

        for node in ast.walk(module):
            # FastAPI handlers are declared ``async def``; checking only
            # FunctionDef silently yields an empty endpoint list.
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not (isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name)):
                    continue
                if func.value.id != "router" or func.attr not in HTTP_VERBS:
                    continue
                if not decorator.args:
                    continue
                path = literal(decorator.args[0])
                if not isinstance(path, str):
                    continue

                endpoint: dict = {
                    "method": func.attr.upper(),
                    "path": f"/api{mount['prefix']}{path}" if path != "/" else f"/api{mount['prefix']}",
                    "handler": node.name,
                    "tag": mount["tag"],
                    "module": f"app/api/{filename}",
                }
                # Collapse the trailing slash of the collection route.
                if endpoint["path"].endswith("/") and len(endpoint["path"]) > 1:
                    endpoint["path"] = endpoint["path"].rstrip("/") or "/"

                for keyword in decorator.keywords:
                    value = literal(keyword.value)
                    if keyword.arg == "response_model":
                        endpoint["response_model"] = ast.unparse(keyword.value)
                    elif keyword.arg == "status_code" and value is not None:
                        endpoint["status_code"] = int(value)
                endpoints.append(endpoint)

    endpoints.sort(key=lambda e: (e["path"], e["method"]))
    return endpoints


# ---------------------------------------------------------------------------
# Rules and scoring
# ---------------------------------------------------------------------------


def extract_rule_codes() -> list[dict]:
    """Rule codes and severities, paired with the class that declares them."""
    module = parse(ENGINE_FILE)
    registry = None
    rules: list[dict] = []

    for classdef in iter_classdefs(module):
        code = None
        for stmt in classdef.body:
            # `code = "X"` on the concrete rules, `code: str = "UNKNOWN_RULE"`
            # on the abstract base -- both forms have to be read, or the base
            # class's placeholder becomes the only thing the parser sees.
            raw = None
            if isinstance(stmt, ast.Assign) and len(stmt.targets) == 1:
                if isinstance(stmt.targets[0], ast.Name) and stmt.targets[0].id == "code":
                    raw = stmt.value
            elif isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if stmt.target.id == "code" and stmt.value is not None:
                    raw = stmt.value
            if raw is not None:
                candidate = literal(raw)
                if isinstance(candidate, str):
                    code = candidate
        if code and classdef.name != "Rule":
            rules.append({"code": code, "class": classdef.name})

    # DEFAULT_RULES lists the registered instances in evaluation order.
    # Declared as `DEFAULT_RULES: list[Rule] = [...]`, so it is an AnnAssign.
    registered: list[str] = []
    for node in module.body:
        target_name = None
        value = None
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            if isinstance(node.targets[0], ast.Name):
                target_name, value = node.targets[0].id, node.value
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_name, value = node.target.id, node.value
        if target_name == "DEFAULT_RULES" and isinstance(value, ast.List):
            for element in value.elts:
                if isinstance(element, ast.Call) and isinstance(element.func, ast.Name):
                    registered.append(element.func.id)

    if not registered:
        raise SpecError("DEFAULT_RULES could not be parsed from engine.py")

    by_class = {rule["class"]: rule for rule in rules}
    ordered: list[dict] = []
    for class_name in registered:
        if class_name not in by_class:
            raise SpecError(f"DEFAULT_RULES names {class_name}, which declares no code")
        entry = dict(by_class[class_name])
        entry["order"] = len(ordered) + 1
        ordered.append(entry)

    return ordered


def extract_blocking_codes() -> list[str]:
    module = parse(SCORING_FILE)
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "BLOCKING_CODES":
                if isinstance(node.value, ast.Set):
                    return sorted(
                        v for v in (literal(e) for e in node.value.elts)
                        if isinstance(v, str)
                    )
    return []


def extract_route_table(variable: str) -> dict[str, str]:
    module = parse(SCORING_FILE)
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == variable:
                if isinstance(node.value, ast.Dict):
                    return {
                        str(literal(k)): str(literal(v))
                        for k, v in zip(node.value.keys, node.value.values)
                    }
    return {}


def extract_labels(variable: str) -> dict[str, str]:
    return extract_route_table(variable)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------


def extract_settings() -> list[dict]:
    """Every field on the Settings class, with its default and annotation."""
    module = parse(CONFIG_FILE)
    entries: list[dict] = []

    for classdef in iter_classdefs(module):
        if classdef.name != "Settings":
            continue
        for stmt in classdef.body:
            if not isinstance(stmt, ast.AnnAssign):
                continue
            if not isinstance(stmt.target, ast.Name):
                continue
            name = stmt.target.id
            if name.startswith("_"):
                continue
            annotation = ast.unparse(stmt.annotation)
            entry: dict = {"name": name, "type": annotation}
            default = literal(stmt.value) if stmt.value is not None else None
            if default is not None:
                entry["default"] = default
            elif stmt.value is not None:
                entry["default"] = "<computed>"
            entries.append(entry)

    return entries


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------


def extract_workflows() -> list[dict]:
    workflows: list[dict] = []
    if not os.path.isdir(WORKFLOW_DIR):
        return workflows

    for filename in sorted(os.listdir(WORKFLOW_DIR)):
        if not filename.endswith(".json"):
            continue
        with open(os.path.join(WORKFLOW_DIR, filename), encoding="utf-8") as handle:
            document = json.load(handle)

        node_types: dict[str, int] = {}
        triggers: list[str] = []
        for node in document.get("nodes", []):
            ntype = node.get("type", "unknown")
            node_types[ntype] = node_types.get(ntype, 0) + 1
            if "webhook" in ntype or "Trigger" in ntype or "errorTrigger" in ntype:
                triggers.append(node.get("name", "unknown"))

        workflows.append(
            {
                "file": filename,
                "name": document.get("name"),
                "node_count": len(document.get("nodes", [])),
                "connection_count": len(document.get("connections", {})),
                "trigger_nodes": triggers,
                "node_types": dict(sorted(node_types.items())),
                "settings": document.get("settings", {}),
                "tags": document.get("tags", []),
            }
        )

    return workflows


# ---------------------------------------------------------------------------
# Narrative -- the parts that are prose, asserted against source
# ---------------------------------------------------------------------------

WORKFLOW_PURPOSE = {
    "case_orchestrator.json": (
        "Main end-to-end orchestration. Triggered when a case is ready to be "
        "assessed; drives submit, assessment, reviewer resolution, notification "
        "and the branch that opens the correct approval. Contains no business logic."
    ),
    "document_intake.json": (
        "Async document classification and extraction. Triggered on upload or by a "
        "reviewer pressing Re-process; posts to the document service, retries "
        "transient failures, records the outcome."
    ),
    "sla_escalation.json": (
        "Scheduled SLA check. Runs daily; finds cases past their review deadline "
        "and records warnings and escalations. Does not define the SLA thresholds."
    ),
    "error_handler.json": (
        "Centralised error handling. Registered as the error workflow for the other "
        "three; records a platform incident when any of them exhausts its retries. "
        "Does not retry the failed work."
    ),
}

WEBHOOK_CONTRACTS = {
    "case_events": {
        "method": "POST",
        "path": "/api/webhooks/n8n",
        "auth": "Header X-N8N-Secret equals N8N_API_KEY (hmac.compare_digest)",
        "effect": "Appends exactly one audit event. Cannot mutate case state.",
        "request_schema": "WebhookPayload",
        "response_schema": "WebhookAck",
        "event_types": [
            "WORKFLOW_TRIGGERED",
            "WORKFLOW_COMPLETED",
            "WORKFLOW_FAILED",
            "NOTIFICATION_SENT",
            "NOTIFICATION_FAILED",
            "NOTIFICATION_SKIPPED",
            "REVIEWER_ASSIGNED",
            "APPROVAL_OPENED",
            "SLA_WARNING",
            "SLA_ESCALATED",
            "DOCUMENT_PROCESSING_DISPATCHED",
            "RETRY_EXHAUSTED",
        ],
    },
    "platform_incidents": {
        "method": "POST",
        "path": "/api/webhooks/n8n/incident",
        "auth": "Header X-N8N-Secret equals N8N_API_KEY",
        "effect": "Appends one platform audit row. case_id is optional.",
        "request_schema": "WorkflowIncident",
        "response_schema": "WebhookAck",
        "event_types": [
            "WORKFLOW_FAILED",
            "INTEGRATION_UNREACHABLE",
            "RETRY_EXHAUSTED",
            "WEBHOOK_REJECTED",
        ],
    },
    "allowlist_discovery": {
        "method": "GET",
        "path": "/api/webhooks/n8n/event-types",
        "auth": "None (public vocabulary)",
        "effect": "Returns the closed allowlists so a workflow can be validated before it runs.",
    },
}


def verify_narrative(endpoints: list[dict], workflows: list[dict]) -> None:
    """Fail if the declared narrative names something the source does not have.

    This is the guard that keeps the prose half of the spec honest. Renaming a
    webhook route or deleting a workflow file breaks this script instead of
    producing a document that describes a system that no longer exists.
    """
    paths = {e["path"] for e in endpoints}
    for contract in WEBHOOK_CONTRACTS.values():
        if contract["path"] not in paths:
            raise SpecError(f"webhook contract references missing route {contract['path']}")

    files = {w["file"] for w in workflows}
    for filename in WORKFLOW_PURPOSE:
        if filename not in files:
            raise SpecError(f"narrative describes {filename}, which does not exist")

    # The two webhook event vocabularies are declared in webhooks.py; if a
    # route survives but its allowlist entry is renamed, the contract above
    # would be a lie. Cross-check against the parsed allowlists.
    allowlists = extract_webhook_allowlists()
    declared_case = set(WEBHOOK_CONTRACTS["case_events"]["event_types"])
    if declared_case != allowlists["case"]:
        raise SpecError(
            "case event allowlist drifted: "
            f"spec={sorted(declared_case)} source={sorted(allowlists['case'])}"
        )
    declared_incident = set(WEBHOOK_CONTRACTS["platform_incidents"]["event_types"])
    if declared_incident != allowlists["incident"]:
        raise SpecError(
            "incident event allowlist drifted: "
            f"spec={sorted(declared_incident)} source={sorted(allowlists['incident'])}"
        )


def extract_webhook_allowlists() -> dict[str, set[str]]:
    """Parse the two allowlist dicts out of webhooks.py."""
    module = parse(os.path.join(API_DIR, "webhooks.py"))
    result: dict[str, set[str]] = {"case": set(), "incident": set()}
    for node in module.body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if not isinstance(node.value, ast.Dict):
                continue
            key = {"ALLOWED_EVENT_TYPES": "case", "INCIDENT_EVENT_TYPES": "incident"}.get(
                node.target.id
            )
            if key:
                result[key] = {
                    str(literal(k)) for k in node.value.keys if literal(k) is not None
                }
    return result


# ---------------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------------


def build_spec() -> dict:
    enums = extract_enums()
    models = extract_models(enums)
    endpoints = extract_endpoints()
    workflows = extract_workflows()
    verify_narrative(endpoints, workflows)

    settings_entries = extract_settings()
    settings_by_name = {entry["name"]: entry for entry in settings_entries}

    thresholds = {
        "score": {
            "auto_approve_max": settings_by_name.get("RULE_AUTO_APPROVE_MAX_RISK", {}).get("default"),
            "low_max": settings_by_name.get("RISK_THRESHOLD_LOW", {}).get("default"),
            "medium_max": settings_by_name.get("RISK_THRESHOLD_MEDIUM", {}).get("default"),
            "high_max": settings_by_name.get("RISK_THRESHOLD_HIGH", {}).get("default"),
            "scale_max": 100,
        },
        "weights": {
            name: entry["default"]
            for name, entry in settings_by_name.items()
            if name.startswith("RISK_WEIGHT_")
        },
        "confidence": {
            "high": settings_by_name.get("CONFIDENCE_HIGH", {}).get("default"),
            "medium": settings_by_name.get("CONFIDENCE_MEDIUM", {}).get("default"),
        },
    }

    rule_codes = extract_rule_codes()

    return {
        "spec_version": "1.0.0",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generator": "tools/build_project_spec.py",
        "project": {
            "name": "Vendor Onboarding & Risk Orchestrator",
            "version": "1.0.0",
            "summary": (
                "A vendor onboarding and risk workflow where n8n orchestrates and a "
                "FastAPI backend decides. Deterministic rules and explainable additive "
                "scoring produce every route; the AI layer contributes advisory signals "
                "only and can never approve, reject, or move a case."
            ),
            "architecture": {
                "orchestration": "n8n (webhooks, retries, scheduling, routing, notifications)",
                "business_logic": "FastAPI backend (rules, scoring, state machine, AI calls)",
                "state": "PostgreSQL via async SQLAlchemy 2.0",
                "interface": "React + Vite dashboard",
                "ai_provider_default": settings_by_name.get("LLM_PROVIDER", {}).get("default"),
            },
            "data_classification": "Demo Dataset — all records are synthetic.",
        },
        "enums": enums,
        "models": models,
        "api": {
            "base_path": "/api",
            "endpoint_count": len(endpoints),
            "endpoints": endpoints,
        },
        "rules": {
            "engine": "backend/app/rules/engine.py",
            "deterministic": True,
            "count": len(rule_codes),
            "codes": rule_codes,
            "blocking_codes": extract_blocking_codes(),
            "scoring": "backend/app/rules/risk_scoring.py",
            "scoring_model": "additive; the score is the sum of the findings a reviewer can read",
            "severity_route_floor": extract_route_table("SEVERITY_ROUTE_FLOOR"),
            "severity_level_floor": extract_route_table("SEVERITY_LEVEL_FLOOR"),
            "finding_labels": extract_labels("FINDING_LABELS"),
            "thresholds": thresholds,
        },
        "webhook_contracts": WEBHOOK_CONTRACTS,
        "workflows": [
            {**workflow, "purpose": WORKFLOW_PURPOSE.get(workflow["file"], "")}
            for workflow in workflows
        ],
        "configuration": {
            "source": "backend/app/config.py",
            "secret_variables": [
                "OPENAI_API_KEY",
                "SECRET_KEY",
                "N8N_API_KEY",
            ],
            "variables": settings_entries,
        },
        "verification": {
            "backend": "python3 backend/check_static.py",
            "frontend": "python3 frontend/check_static.py",
            "contracts": "python3 tools/check_contracts.py",
            "workflows": "python3 n8n/build_workflows.py --check",
            "spec": "python3 tools/build_project_spec.py --check",
        },
        "constraints": {
            "data": "Synthetic only. No real PII, banking details, or company data.",
            "ai_authority": "LLM cannot approve, reject, or take an irreversible action.",
            "ai_metadata": "Structured reasoning summaries are stored; hidden chain-of-thought is not.",
            "secrets": "Environment variables only. No keys in source or in workflow JSON.",
            "thresholds": "Prototype configuration, not scientifically optimal values.",
            "metrics": "Only numbers computed from the synthetic evaluation dataset.",
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="verify without writing")
    args = parser.parse_args()

    try:
        spec = build_spec()
    except SpecError as exc:
        print(f"SPEC ERROR: {exc}", file=sys.stderr)
        return 1

    rendered = json.dumps(spec, indent=2, sort_keys=False) + "\n"

    if args.check:
        if not os.path.isfile(OUTPUT):
            print("project_spec.json does not exist", file=sys.stderr)
            return 1
        with open(OUTPUT, encoding="utf-8") as handle:
            committed = json.load(handle)
        # generated_at is inherently volatile; compare everything else.
        committed.pop("generated_at", None)
        fresh = json.loads(rendered)
        fresh.pop("generated_at", None)
        if committed != fresh:
            print(
                "project_spec.json is stale; re-run tools/build_project_spec.py",
                file=sys.stderr,
            )
            return 1
        print(
            f"OK project_spec.json ({spec['api']['endpoint_count']} endpoints, "
            f"{len(spec['models'])} models, {len(spec['workflows'])} workflows)"
        )
        return 0

    with open(OUTPUT, "w", encoding="utf-8") as handle:
        handle.write(rendered)

    print(
        f"WROTE project_spec.json ({len(rendered)} bytes): "
        f"{spec['api']['endpoint_count']} endpoints, "
        f"{len(spec['models'])} models, "
        f"{len(spec['enums'])} enums, "
        f"{spec['rules']['count']} rules, "
        f"{len(spec['workflows'])} workflows"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
