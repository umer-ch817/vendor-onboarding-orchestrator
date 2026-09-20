#!/usr/bin/env python3
"""Build the n8n workflow JSON files in ``n8n/workflows/``.

Why generate rather than hand-write
-----------------------------------
These workflows share a lot of structure: every one of them calls
``POST /api/webhooks/n8n`` to record what it did, every one of them reads its
base URLs and shared secret from the same settings node, and every one of them
tags the audit payload with ``$workflow.name`` and ``$execution.id``.

Hand-writing six near-identical callback nodes across four files means six
chances for one of them to drift -- and drift in an audit callback fails
silently, because nothing downstream reads the response. Generating them from
one factory makes that class of bug impossible.

Generating also means the output is guaranteed to be valid JSON, and lets the
script assert structural properties (unique node ids, every connection target
exists, no node is orphaned) before anything is written to disk. Those same
assertions live in ``tools/check_workflows.py`` so they can be run against the
committed files without regenerating them.

Run
---
    python3 n8n/build_workflows.py
    python3 n8n/build_workflows.py --check     # verify without writing
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
WORKFLOW_DIR = os.path.join(HERE, "workflows")

# ---------------------------------------------------------------------------
# Credential handling
#
# The shared webhook secret is read from the n8n container's environment by
# expression, never baked into these files. Section 29 of the brief requires
# secrets to live in environment variables; a workflow JSON is source.
#
# This requires N8N_BLOCK_ENV_ACCESS_IN_NODE=false on the n8n container, which
# docker-compose.yml sets. That flag is a real security tradeoff -- it lets any
# n8n expression read any environment variable in the container -- and is
# noted as such in docs/decisions.md.
# ---------------------------------------------------------------------------
# NB: the leading "=" matters. n8n only evaluates a parameter as an expression
# when it starts with "="; without it the value is stored as the literal text
# "{{ $env.VOR_BACKEND_URL }}", which then reaches the HTTP node as
# `Invalid URL: {{ $env.VOR_BACKEND_URL }}/api/... . URL must start with "http"`.
SECRET_EXPR = "={{ $env.VOR_CALLBACK_SECRET }}"
BACKEND_URL_EXPR = "={{ $env.VOR_BACKEND_URL }}"
NOTIFY_URL_EXPR = "={{ $env.VOR_NOTIFICATION_URL }}"

# Every node gets a uuid so that re-running this script produces fresh ids
# rather than accidentally colliding with an id already imported into n8n.
def _uid() -> str:
    return str(uuid.uuid4())


# The workflow id follows the opposite rule: it must be STABLE.
# `n8n import:workflow` matches on the workflow id. With no id at all, n8n 2.x
# aborts the import with "NOT NULL constraint failed: workflow_entity.id"; with
# a random id, every re-import adds another copy of the same workflow instead
# of updating it. Deriving it from the name keeps re-imports idempotent.
def _workflow_id(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"vendor-onboarding/{name}"))


# n8n only evaluates a parameter as an expression when the string starts with
# "=". A bare "{{ $json.foo }}" is stored as literal text, which fails silently
# and confusingly: an IF node compares the literal string "{{ $json.submission_ok }}"
# against "yes", never matches, and the workflow takes its failure branch even
# though the HTTP call that preceded it returned 200.
def _expr(value: str) -> str:
    return value if value.startswith("=") else f"={value}"


# Tags need ids as well. n8n 2.x resolves a tag by id when importing; a bare
# tag *name* has no id to resolve against, and the insert fails with
# "NOT NULL constraint failed: workflows_tags.tagId".
TAG_NAMES = ["vendor-onboarding", "orchestration"]


def _tags() -> list[dict[str, str]]:
    return [
        {"id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"vendor-onboarding/tag/{n}")), "name": n}
        for n in TAG_NAMES
    ]


# ---------------------------------------------------------------------------
# Node factories
# ---------------------------------------------------------------------------


def node(
    name: str,
    ntype: str,
    type_version: float,
    position: tuple[int, int],
    parameters: dict,
    *,
    notes: str | None = None,
    on_error: str | None = None,
    retry: bool = False,
    max_tries: int = 3,
    wait_ms: int = 2000,
    always_output: bool = False,
    extra: dict | None = None,
) -> dict:
    """Assemble one n8n node."""
    built: dict = {
        "parameters": parameters,
        "id": _uid(),
        "name": name,
        "type": ntype,
        "typeVersion": type_version,
        "position": list(position),
    }
    if notes:
        built["notes"] = notes
    if on_error:
        built["onError"] = on_error
    if retry:
        built["retryOnFail"] = True
        built["maxTries"] = max_tries
        built["waitBetweenTries"] = wait_ms
    if always_output:
        built["alwaysOutputData"] = True
    if extra:
        built.update(extra)
    return built


def code_node(
    name: str,
    position: tuple[int, int],
    js: str,
    *,
    notes: str | None = None,
    mode: str = "runOnceForAllItems",
) -> dict:
    return node(
        name,
        "n8n-nodes-base.code",
        2,
        position,
        {"mode": mode, "jsCode": js.strip("\n")},
        notes=notes,
    )


def http_node(
    name: str,
    position: tuple[int, int],
    *,
    method: str,
    url: str,
    json_body: str | None = None,
    query: dict[str, str] | None = None,
    headers: dict[str, str] | None = None,
    full_response: bool = False,
    notes: str | None = None,
    on_error: str | None = None,
    retry: bool = False,
    max_tries: int = 3,
    wait_ms: int = 2000,
    # The backend endpoints these nodes call run LLM classification and
    # extraction inline. With the mock provider that returns in milliseconds,
    # but a real model can take well over 30s for one document -- and the node
    # then reports RETRY_EXHAUSTED for a request that was simply still working.
    timeout_ms: int = 180000,
) -> dict:
    params: dict = {"method": method.upper(), "url": url, "options": {}}

    if query:
        params["sendQuery"] = True
        params["queryParameters"] = {
            "parameters": [
                {"name": key, "value": value} for key, value in query.items()
            ]
        }
    if headers:
        params["sendHeaders"] = True
        params["headerParameters"] = {
            "parameters": [
                {"name": key, "value": value} for key, value in headers.items()
            ]
        }
    if json_body is not None:
        params["sendBody"] = True
        params["specifyBody"] = "json"
        params["jsonBody"] = json_body

    options: dict = {"timeout": timeout_ms}
    if full_response:
        options["response"] = {"response": {"fullResponse": True}}
    params["options"] = options

    return node(
        name,
        "n8n-nodes-base.httpRequest",
        4.2,
        position,
        params,
        notes=notes,
        on_error=on_error,
        retry=retry,
    )


def if_node(
    name: str,
    position: tuple[int, int],
    left: str,
    right: str,
    *,
    notes: str | None = None,
    operator: str = "equals",
) -> dict:
    """A single-condition IF node.

    Comparisons are always string-to-string. The filter node's numeric and
    boolean operators have changed shape across n8n versions, whereas a string
    equals has been stable, and every value this workflow compares is a string
    anyway.
    """
    return node(
        name,
        "n8n-nodes-base.if",
        2.2,
        position,
        {
            "conditions": {
                "options": {
                    "caseSensitive": True,
                    "leftValue": "",
                    "typeValidation": "loose",
                    "version": 2,
                },
                "conditions": [
                    {
                        "id": _uid(),
                        "leftValue": _expr(left),
                        "rightValue": right,
                        "operator": {
                            "type": "string",
                            "operation": operator,
                        },
                    }
                ],
                "combinator": "and",
            },
            "options": {},
        },
        notes=notes,
    )


def switch_node(
    name: str,
    position: tuple[int, int],
    left: str,
    matches: list[tuple[str, str]],
    *,
    notes: str | None = None,
) -> dict:
    """A Switch node with one rule per (value, output label).

    ``matches`` is ordered; output index N corresponds to ``matches[N]``. The
    fallback output is the extra output after the last rule, which is what
    ``fallbackOutput: "extra"`` produces.
    """
    values = []
    for value, label in matches:
        values.append(
            {
                "conditions": {
                    "options": {
                        "caseSensitive": True,
                        "leftValue": "",
                        "typeValidation": "loose",
                        "version": 2,
                    },
                    "conditions": [
                        {
                            "id": _uid(),
                            "leftValue": _expr(left),
                            "rightValue": value,
                            "operator": {"type": "string", "operation": "equals"},
                        }
                    ],
                    "combinator": "and",
                },
                "renameOutput": True,
                "outputKey": label,
            }
        )

    return node(
        name,
        "n8n-nodes-base.switch",
        3.2,
        position,
        {"rules": {"values": values}, "options": {"fallbackOutput": "extra"}},
        notes=notes,
    )


def settings_node(name: str, position: tuple[int, int], extra: dict[str, str]) -> dict:
    """The single place base URLs and tunables are declared.

    Every downstream node references ``$('Workflow Settings').first().json``
    rather than ``$json``, because several nodes in these workflows replace the
    item's JSON with an HTTP response body. Reading configuration off ``$json``
    would work until the first node that does, and then fail.
    """
    assignments = [
        {
            "id": _uid(),
            "name": "backend_base_url",
            "value": BACKEND_URL_EXPR,
            "type": "string",
        },
        {
            "id": _uid(),
            "name": "notification_base_url",
            "value": NOTIFY_URL_EXPR,
            "type": "string",
        },
        {
            "id": _uid(),
            "name": "callback_secret",
            "value": SECRET_EXPR,
            "type": "string",
        },
    ]
    for key, value in extra.items():
        assignments.append(
            {"id": _uid(), "name": key, "value": value, "type": "string"}
        )

    return node(
        name,
        "n8n-nodes-base.set",
        3.4,
        position,
        {
            "mode": "manual",
            "includeOtherFields": True,
            "assignments": {"assignments": assignments},
            "options": {},
        },
        notes=(
            "Only place configuration is declared. The secret is read from the "
            "container environment by expression so it is never written into "
            "this workflow file."
        ),
    )


def audit_node(
    name: str,
    position: tuple[int, int],
    event_type: str,
    *,
    data_expr: str = "{}",
    case_expr: str = "$json.case_id",
    event_type_expr: str | None = None,
    notes: str | None = None,
) -> dict:
    """A callback to the backend that records one orchestration event.

    These calls are best-effort: if the audit write fails, the workflow
    continues, because the work itself already happened and stopping now would
    not undo it. The backend logs the failure loudly. Losing an audit row is
    bad; abandoning a half-assessed case because the audit row failed is worse.

    ``event_type_expr`` overrides the literal event type when the outcome is
    only known at runtime -- a notification that may have been delivered or may
    have failed is two different events, and collapsing them into one would
    lose the distinction the queue most needs to see.
    """
    event_js = _expr(event_type_expr) if event_type_expr else f"'{event_type}'"
    body = (
        "={{ JSON.stringify({"
        f"event_type: {event_js}, "
        f"case_id: Number({case_expr}), "
        "timestamp: new Date().toISOString(), "
        "data: Object.assign({_workflow: $workflow.name, _execution_id: $execution.id}, "
        f"({data_expr}))"
        "}) }}"
    )
    return http_node(
        name,
        position,
        method="POST",
        url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/webhooks/n8n",
        json_body=body,
        headers={
            "X-N8N-Secret": "={{ $('Workflow Settings').first().json.callback_secret }}",
        },
        notes=notes or f"Records {event_type} in the case audit trail.",
        on_error="continueRegularOutput",
    )


def sticky(position: tuple[int, int], content: str, width: int = 460, height: int = 220,
           color: int = 7) -> dict:
    return node(
        "Note",
        "n8n-nodes-base.stickyNote",
        1,
        position,
        {"content": content, "height": height, "width": width, "color": color},
    )


def workflow(
    name: str,
    nodes: list[dict],
    links: dict[str, list[list[str]]],
    *,
    settings: dict | None = None,
) -> dict:
    """Assemble a workflow document, stripping the placeholder sticky names."""
    index = 1
    for item in nodes:
        if item["name"] == "Note":
            item["name"] = f"Note {index}"
            index += 1

    connections: dict = {}
    for source, outputs in links.items():
        connections[source] = {
            "main": [
                [{"node": target, "type": "main", "index": 0} for target in (output or [])]
                for output in outputs
            ]
        }

    return {
        "id": _workflow_id(name),
        "name": name,
        "nodes": nodes,
        "connections": connections,
        "active": False,
        "settings": settings or {"executionOrder": "v1"},
        "pinData": {},
        "tags": _tags(),
    }


# ---------------------------------------------------------------------------
# Structural assertions
#
# These run against every generated workflow before it is written. They are the
# same checks that ``tools/check_workflows.py`` performs on the committed files
# -- duplicated deliberately, because the cheapest place to catch an unlinked
# branch is the moment it is created.
# ---------------------------------------------------------------------------


class WorkflowError(Exception):
    pass


def assert_workflow(document: dict) -> None:
    name = document["name"]
    nodes = document["nodes"]
    by_name = {n["name"]: n for n in nodes}

    ids = [n["id"] for n in nodes]
    if len(ids) != len(set(ids)):
        raise WorkflowError(f"{name}: duplicate node id")

    if len(by_name) != len(nodes):
        raise WorkflowError(f"{name}: duplicate node name")

    required = {"parameters", "id", "name", "type", "typeVersion", "position"}
    for item in nodes:
        missing = required - set(item)
        if missing:
            raise WorkflowError(
                f"{name}: node '{item.get('name')}' is missing {sorted(missing)}"
            )
        if not item["type"].startswith("n8n-nodes-base."):
            raise WorkflowError(
                f"{name}: node '{item['name']}' has a non-core type '{item['type']}'"
            )

    referenced: set[str] = set()
    for source, outputs in document["connections"].items():
        if source not in by_name:
            raise WorkflowError(f"{name}: connection source '{source}' does not exist")
        for output in outputs["main"]:
            for link in output:
                if link["node"] not in by_name:
                    raise WorkflowError(
                        f"{name}: '{source}' links to unknown node '{link['node']}'"
                    )
                referenced.add(link["node"])

    # Every node except the trigger and the stickies must be reachable.
    triggers = {
        "n8n-nodes-base.webhook",
        "n8n-nodes-base.scheduleTrigger",
        "n8n-nodes-base.errorTrigger",
        "n8n-nodes-base.executeWorkflowTrigger",
    }
    stickies = {"n8n-nodes-base.stickyNote"}
    for item in nodes:
        if item["type"] in triggers or item["type"] in stickies:
            continue
        if item["name"] not in referenced and item["name"] not in document["connections"]:
            raise WorkflowError(f"{name}: node '{item['name']}' is unreachable")

    # Every non-sticky, non-trigger node that has outgoing links but is not a
    # known terminal is fine; instead assert the reverse -- that no node points
    # at itself, which would produce an infinite loop at runtime.
    for source, outputs in document["connections"].items():
        for output in outputs["main"]:
            for link in output:
                if link["node"] == source:
                    raise WorkflowError(f"{name}: '{source}' links to itself")


# ===========================================================================
# Workflow 1 -- Case orchestrator
#
# Fired by the backend when a case is submitted. Runs the assessment, resolves
# who must decide, notifies them, and opens the correct approval.
#
# WHAT THIS WORKFLOW DOES NOT DO
# It does not score, route, validate, or decide. Every one of those is a
# backend responsibility (brief section 3). This workflow moves data to the
# right place, in the right order, with retries, and records that it did.
# ===========================================================================

VALIDATE_TRIGGER_JS = """
// The payload arrives from a webhook, so nothing in it is trusted. It is
// checked before it is used to build a URL, and the whole run is abandoned
// with a message a human can act on rather than failing obscurely at the HTTP
// node three steps later.
const ALLOWED_ACTIONS = ['submit_and_assess', 'submit', 'reassess'];

const out = [];
for (const item of $input.all()) {
  const body = (item.json && item.json.body) ? item.json.body : item.json;

  if (body.case_id === undefined || body.case_id === null || body.case_id === '') {
    throw new Error('Trigger rejected: case_id is required.');
  }

  const caseId = Number(body.case_id);
  if (!Number.isInteger(caseId) || caseId <= 0) {
    throw new Error(
      'Trigger rejected: case_id must be a positive integer, received ' +
      JSON.stringify(body.case_id) + '.'
    );
  }

  const action = String(body.action || 'submit_and_assess').toLowerCase();
  if (!ALLOWED_ACTIONS.includes(action)) {
    throw new Error(
      'Trigger rejected: unknown action ' + JSON.stringify(action) +
      '. Allowed: ' + ALLOWED_ACTIONS.join(', ') + '.'
    );
  }

  out.push({
    json: Object.assign({}, item.json, {
      case_id: caseId,
      action: action,
      trigger_metadata: body.metadata || {},
      started_at: new Date().toISOString(),
    }),
  });
}
return out;
"""

INTERPRET_SUBMIT_JS = """
// POST /onboarding/{id}/submit answers 409 when the case is no longer in
// DRAFT. That is not a failure -- it means the case has already moved past the
// step this workflow would have moved it to, which is the idempotency
// requirement (brief section 28). Re-running the orchestrator on the same case
// must be safe, so a 409 proceeds to assessment.
//
// A 404 is different: the case does not exist, and assessing it would be
// meaningless.
//
// NOTE ON $json: an HTTP Request node replaces the item's JSON with the
// response body. Everything this workflow needs from the trigger -- case_id,
// action -- is therefore re-read from the node that produced it rather than
// hoped for in $json. This is the single most common way an n8n workflow
// quietly loses its input halfway through.
const trigger = $('Validate Trigger').first().json;

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const err = j.error || null;
  const status = Number(j.statusCode || (err && (err.httpCode || err.status)) || 0);

  let state;
  if (!err && status >= 200 && status < 300) {
    state = 'submitted';
  } else if (status === 409) {
    state = 'already_progressed';
  } else if (status === 404) {
    state = 'case_not_found';
  } else {
    state = 'failed';
  }

  const ok = (state === 'submitted' || state === 'already_progressed') ? 'yes' : 'no';

  out.push({
    json: {
      case_id: trigger.case_id,
      action: trigger.action,
      started_at: trigger.started_at,
      submission_state: state,
      submission_ok: ok,
      submission_http_status: status,
      submission_detail: {
        submitted: 'Case moved from DRAFT into document collection.',
        already_progressed: 'Case was already past DRAFT; assessment continues unchanged.',
        case_not_found: 'Case ' + trigger.case_id + ' does not exist on the backend.',
        failed: 'Submit call failed with HTTP ' + status + '.',
      }[state],
    },
  });
}
return out;
"""

INTERPRET_ASSESSMENT_JS = """
// Translates the backend's verdict into the orchestration actions this
// workflow owns. It does NOT re-derive the verdict.
//
// The route was computed by the deterministic rule engine and risk scorer in
// backend/app/services/pipeline.py, from rules and thresholds a human can
// read. The AI advisory is recorded alongside it but never influences it.
//
// The tables below are a DISPATCH table, not a decision. They mirror
// ROUTE_TO_APPROVAL_TYPE in that same pipeline module. If they ever disagree,
// the backend is authoritative -- the route value is recorded verbatim in the
// audit trail, so the disagreement is visible rather than silent.
const APPROVAL_BY_ROUTE = {
  auto_approve: 'manager',
  compliance_review: 'compliance',
  senior_review: 'compliance',
  escalate: 'compliance',
  blocked: null,
};

// Who should be told, which is not always who must decide. A blocked case
// needs the compliance lead to triage findings; it does not need an approval
// opened, because there is nothing yet to approve.
const AUDIENCE_BY_ROUTE = {
  auto_approve: 'manager',
  compliance_review: 'compliance',
  senior_review: 'compliance_lead',
  escalate: 'compliance_lead',
  blocked: 'compliance_lead',
};

const out = [];
for (const item of $input.all()) {
  const r = item.json || {};
  const route = String(r.route || 'unknown');
  const recognised = Object.prototype.hasOwnProperty.call(APPROVAL_BY_ROUTE, route);
  const score = Number(r.risk_score || 0);
  const findings = Array.isArray(r.findings) ? r.findings : [];

  out.push({
    json: Object.assign({}, r, {
      route: route,
      route_recognised: recognised ? 'yes' : 'no',
      risk_score: score,
      risk_level: r.risk_level || 'unknown',
      approval_type: APPROVAL_BY_ROUTE[route] || null,
      opens_approval: APPROVAL_BY_ROUTE[route] ? 'yes' : 'no',
      notify_audience: AUDIENCE_BY_ROUTE[route] || 'compliance',
      // A blocked case still needs the compliance queue notified, so a
      // reviewer is resolved even though no approval will be opened. Falling
      // back rather than skipping means the notification path is identical on
      // every route, which is one less branch to get wrong.
      reviewer_query_type: APPROVAL_BY_ROUTE[route] || 'compliance',
      findings_count: findings.length,
      summary:
        'Risk ' + score + '/100 (' + (r.risk_level || 'unknown') + '). ' +
        'Findings: ' + findings.length + '. ' +
        'Exceptions raised: ' + (r.exceptions_created || 0) + '. ' +
        'Highest severity: ' + (r.highest_severity || 'none') + '. ' +
        'AI advisory: ' + (r.ai_recommendation || 'none') +
        (r.ai_degraded ? ' (AI degraded: ' + (r.ai_failure_reason || 'unknown') + ')' : '') + '.',
    }),
  });
}
return out;
"""

SELECT_REVIEWER_JS = """
// Selection is deterministic, not random.
//
// The same case always resolves to the same reviewer, so a retry of this
// workflow cannot deliver the same case to a different person's queue. Random
// selection would make reruns silently non-idempotent, which is exactly the
// property section 28 asks for.
//
// The target queue is the backend's list of active users whose role can
// actually decide this approval type. If that list is empty the case cannot
// proceed, and the workflow says so instead of dropping it.
const prior = $('Interpret Assessment').first().json;
const response = $input.first().json || {};
const reviewers = Array.isArray(response.reviewers) ? response.reviewers : [];

if (reviewers.length === 0) {
  return [{
    json: Object.assign({}, prior, {
      reviewer: null,
      reviewer_available: 'no',
      reviewer_reason:
        'No active user holds a role that can decide a "' + prior.reviewer_query_type +
        '" approval, so case ' + prior.case_id + ' has nowhere to go.',
    }),
  }];
}

// Sorting by email before indexing keeps the choice stable regardless of the
// order the database happened to return rows in.
const ordered = reviewers.slice().sort(function (a, b) {
  return String(a.email).localeCompare(String(b.email));
});
const chosen = ordered[Number(prior.case_id) % ordered.length];

return [{
  json: Object.assign({}, prior, {
    reviewer: chosen,
    reviewer_available: 'yes',
    reviewer_reason: null,
    notification: {
      case_id: prior.case_id,
      audience: prior.notify_audience,
      recipient: chosen.email,
      recipient_name: chosen.name,
      recipient_role: chosen.role,
      severity: prior.risk_level,
      subject: '[Vendor Onboarding] Case ' + prior.case_id + ' — ' + prior.route +
               ' (risk ' + prior.risk_score + '/100)',
      body: prior.summary + ' Required action: ' +
            (prior.opens_approval === 'yes'
              ? 'decide the pending ' + prior.approval_type + ' approval.'
              : 'triage the blocking findings on this case.'),
      route: prior.route,
      approval_type: prior.approval_type,
      workflow: 'vendor-onboarding-case-orchestrator',
    },
  }),
}];
"""

INTERPRET_NOTIFICATION_JS = """
// The notification service is a mock in this prototype, but the shape of the
// handling is what matters: a delivery attempt is recorded either way. "We
// tried to tell someone and it failed" is the single most important thing to
// be able to see in an onboarding queue, and it is the thing a fire-and-forget
// HTTP node hides.
//
// The notification response body carries no case data, so the fields the
// downstream nodes need are re-read from the node that resolved the reviewer.
const prior = $('Select Reviewer').first().json;

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const err = j.error || null;
  const status = Number(j.statusCode || (err && (err.httpCode || err.status)) || 0);
  const delivered = !err && status >= 200 && status < 300;

  out.push({
    json: Object.assign({}, prior, {
      notification_state: delivered ? 'NOTIFICATION_SENT' : 'NOTIFICATION_FAILED',
      notification_detail: delivered
        ? 'Notification accepted by the notification service (HTTP ' + status + ').'
        : 'Notification delivery failed with HTTP ' + status +
          '. The approval is still open; the reviewer was not told.',
      notification_http_status: status,
    }),
  });
}
return out;
"""


# ===========================================================================
# Workflow 2 -- Document intake
#
# Fired when a document is uploaded. Classifies and extracts, then either
# completes cleanly or records a failure for the document detail page.
#
# WHAT THIS WORKFLOW DOES NOT DO
# It does not classify, extract, validate, or OCR. It posts to the document
# service, retries on transient failure, and records the outcome.
# ===========================================================================

VALIDATE_DOC_TRIGGER_JS = """
const ALLOWED_ACTIONS = ['process', 'reprocess'];

const out = [];
for (const item of $input.all()) {
  const body = (item.json && item.json.body) ? item.json.body : item.json;

  if (body.document_id === undefined || body.document_id === null || body.document_id === '') {
    throw new Error('Trigger rejected: document_id is required.');
  }

  const docId = Number(body.document_id);
  if (!Number.isInteger(docId) || docId <= 0) {
    throw new Error('Trigger rejected: document_id must be a positive integer, received ' + JSON.stringify(body.document_id) + '.');
  }

  const action = String(body.action || 'process').toLowerCase();
  if (!ALLOWED_ACTIONS.includes(action)) {
    throw new Error('Trigger rejected: unknown action ' + JSON.stringify(action) + '. Allowed: ' + ALLOWED_ACTIONS.join(', ') + '.');
  }

  out.push({
    json: Object.assign({}, item.json, {
      document_id: docId,
      action: action,
      case_id: body.case_id ? Number(body.case_id) : null,
      trigger_metadata: body.metadata || {},
      started_at: new Date().toISOString(),
    }),
  });
}
return out;
"""

INTERPRET_DOC_PROCESS_JS = """
// The document processing endpoint returns the extraction result directly in
// the response body. It is synchronous in this prototype, but the shape is
// already asynchronous: the caller receives the result and the workflow
// records what happened. If the backend ever moves to async extraction, the
// workflow only changes the node that polls the status; the recording path is
// identical.
const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const err = j.error || null;
  const status = Number(j.statusCode || (err && (err.httpCode || err.status)) || 0);
  const ok = !err && status >= 200 && status < 300;

  let state;
  if (ok) {
    state = j.success ? 'extracted' : 'extraction_failed';
  } else if (status === 409) {
    state = 'already_processing';
  } else if (status === 404) {
    state = 'document_not_found';
  } else {
    state = 'failed';
  }

  out.push({
    json: Object.assign({}, j, {
      document_id: $json.document_id || j.document_id,
      case_id: $json.case_id || j.case_id,
      processing_state: state,
      processing_ok: ok ? 'yes' : 'no',
      processing_http_status: status,
      processing_detail: {
        extracted: 'Document classified and fields extracted.',
        extraction_failed: 'Classification succeeded but extraction did not meet confidence thresholds.',
        already_processing: 'Document was already being processed; skipping re-entry.',
        document_not_found: 'Document ' + ($json.document_id || j.document_id) + ' does not exist.',
        failed: 'Process call failed with HTTP ' + status + '.',
      }[state],
      extraction_confidence: j.extraction_confidence,
      document_type: j.document_type,
      extracted_fields: j.extracted_fields || {},
      requires_verification: j.requires_verification,
      failure_reason: j.failure_reason,
      validation_errors: j.validation_errors,
      warnings: j.warnings,
    }),
  });
}
return out;
"""

INTERPRET_DOC_VERIFY_JS = """
const prior = $('Validate Trigger').first().json;

const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const err = j.error || null;
  const status = Number(j.statusCode || (err && (err.httpCode || err.status)) || 0);
  const ok = !err && status >= 200 && status < 300;

  out.push({
    json: Object.assign({}, prior, {
      verification_state: ok ? 'verified' : 'verification_failed',
      verification_ok: ok ? 'yes' : 'no',
      verification_http_status: status,
      verification_detail: ok
        ? 'Human verification recorded.'
        : 'Verification call failed with HTTP ' + status + '.',
    }),
  });
}
return out;
"""


def workflow_document_intake() -> dict:
    nodes = [
        node(
            "Document Triggered",
            "n8n-nodes-base.webhook",
            2,
            (0, 0),
            {
                "httpMethod": "POST",
                "path": "vendor-onboarding/document",
                "responseMode": "onReceived",
                "options": {},
            },
            notes=(
                "POST /webhook/vendor-onboarding/document with "
                "{document_id, action, case_id, metadata}. "
                "action is 'process' or 'reprocess'."
            ),
            extra={"webhookId": _uid()},
        ),
        settings_node("Workflow Settings", (220, 0), {}),
        code_node("Validate Trigger", (440, 0), VALIDATE_DOC_TRIGGER_JS,
                  notes="Rejects a malformed trigger before it can build a URL."),
        audit_node("Record Trigger Started", (660, 0), "DOCUMENT_PROCESSING_DISPATCHED",
                   data_expr="{action: $json.action, trigger_metadata: $json.trigger_metadata}"),
        http_node(
            "Process Document",
            (880, 0),
            method="POST",
            # Reads the id from Validate Trigger, not from $json: this node is
            # chained after a callback node whose payload has no document_id,
            # so $json.document_id was empty and the URL 404'd.
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/documents/{{ $('Validate Trigger').first().json.document_id }}/process",
            full_response=True,
            notes="Runs classification and extraction. Retries on transient failure.",
            retry=True,
            max_tries=3,
            wait_ms=3000,
            on_error="continueErrorOutput",
        ),
        audit_node(
            "Record Process Failure",
            (1100, 180),
            "RETRY_EXHAUSTED",
            data_expr="{stage: 'document_processing', detail: 'Document processing call failed after 3 attempts.'}",
            case_expr="$('Validate Trigger').first().json.case_id",
            notes="Terminal. Reached only after retries are spent.",
        ),
        code_node("Interpret Process", (1100, -140), INTERPRET_DOC_PROCESS_JS,
                  notes="Maps the synchronous processing response to a state."),
        if_node(
            "Processing Ok?",
            (1320, -140),
            left="{{ $json.processing_ok }}",
            right="yes",
            notes="A processing failure (not a 409, not a 404) is terminal.",
        ),
        audit_node(
            "Record Processing Failed",
            (1540, 60),
            "WORKFLOW_FAILED",
            data_expr="{stage: 'document_processing', state: $json.processing_state, detail: $json.processing_detail, http_status: $json.processing_http_status}",
            case_expr="$json.case_id",
            notes="Terminal. The extraction did not succeed.",
        ),
        http_node(
            "Verify Extraction",
            (1540, -340),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/documents/{{ $('Validate Trigger').first().json.document_id }}/verify",
            json_body="={{ JSON.stringify({verified: true, actor_user_id: null}) }}",
            notes="Records human verification when extraction confidence was low.",
            retry=True,
            max_tries=2,
            wait_ms=2000,
            on_error="continueRegularOutput",
        ),
        code_node("Interpret Verify", (1760, -340), INTERPRET_DOC_VERIFY_JS,
                  notes="Records verification outcome."),
        audit_node(
            "Record Document Complete",
            (1980, -340),
            "WORKFLOW_COMPLETED",
            data_expr=(
                "{outcome: 'document_processed', document_id: $json.document_id, "
                "state: $json.processing_state, verified: $json.verification_state || 'not_required', "
                "confidence: $json.extraction_confidence, document_type: $json.document_type, "
                "fields_extracted: Object.keys($json.extracted_fields || {}).length}"
            ),
            notes="Terminal success. Document processed and optionally verified.",
        ),
        sticky(
            (-40, -400),
            "## Vendor Onboarding — Document Intake\n\n"
            "Triggered when a document is uploaded or a reviewer clicks Re-process.\n\n"
            "**This workflow contains no extraction logic.** It posts to the "
            "document service, retries transient failures, and records the outcome.\n\n"
            "A document that does not meet confidence thresholds is flagged for "
            "human verification on the document detail page, not reprocessed "
            "automatically.",
            width=520,
            height=280,
            color=4,
        ),
    ]

    links = {
        "Document Triggered": [["Workflow Settings"]],
        "Workflow Settings": [["Validate Trigger"]],
        "Validate Trigger": [["Record Trigger Started"]],
        "Record Trigger Started": [["Process Document"]],
        "Process Document": [["Interpret Process"], ["Record Process Failure"]],
        "Interpret Process": [["Processing Ok?"]],
        "Processing Ok?": [["Verify Extraction"], ["Record Processing Failed"]],
        "Verify Extraction": [["Interpret Verify"]],
        "Interpret Verify": [["Record Document Complete"]],
    }

    return workflow(
        "Vendor Onboarding — Document Intake",
        nodes,
        links,
        settings={"executionOrder": "v1", "saveManualExecutions": True, "callerPolicy": "workflowsFromSameOwner"},
    )


# ===========================================================================
# Workflow 3 -- SLA Escalation (scheduled)
#
# Runs on a schedule (default every hour). Finds cases that have been in
# REVIEW_REQUIRED or APPROVAL_PENDING longer than their threshold and
# escalates them.
#
# WHAT THIS WORKFLOW DOES NOT DO
# It does not define the SLA thresholds. Those are backend configuration,
# because the frontend displays them and the backend enforces them. This
# workflow only reads them and acts.
# ===========================================================================

SLA_QUERY_JS = """
const settings = $('Workflow Settings').first().json;

const out = [];
for (const item of $input.all()) {
  const base = String(settings.backend_base_url).replace(/\\/$/, '');
  out.push({
    json: {
      warning_url: base + '/api/exceptions/summary',
      escalation_url: base + '/api/exceptions/summary',
      backend_base_url: base,
      callback_secret: settings.callback_secret,
      warning_hours: Number(settings.warning_hours || 24),
      escalation_hours: Number(settings.escalation_hours || 72),
    },
  });
}
return out;
"""

SLA_INTERPRET_JS = """
// The summary endpoint returns counts by severity and age. The workflow
// escalates cases whose oldest pending exception exceeds the escalation
// threshold. A warning is logged for cases approaching the threshold.
const out = [];
for (const item of $input.all()) {
  const j = item.json || {};
  const err = j.error || null;
  const status = Number(j.statusCode || (err && (err.httpCode || err.status)) || 0);
  const ok = !err && status >= 200 && status < 300;

  if (!ok) {
    out.push({
      json: {
        state: 'failed',
        http_status: status,
        detail: 'Summary call failed with HTTP ' + status + '.',
      },
    });
    continue;
  }

  // The mock returns a shape the code below expects. A real backend would
  // return a structured list; the mock is simple. In production this node
  // would loop over the cases and triage each one.
  out.push({
    json: Object.assign({}, j, {
      state: 'completed',
      warning_hours: $json.warning_hours,
      escalation_hours: $json.escalation_hours,
    }),
  });
}
return out;
"""


def workflow_sla_escalation() -> dict:
    nodes = [
        node(
            "Schedule",
            "n8n-nodes-base.scheduleTrigger",
            1.2,
            (0, 0),
            {
                "triggerTimes": {
                    "item": [
                        {
                            "hour": 9,
                            "minute": 0,
                        }
                    ]
                },
                "timezone": "UTC",
                "options": {},
            },
            notes="Runs daily at 09:00 UTC. Adjustable in the UI after import.",
        ),
        settings_node("Workflow Settings", (220, 0), {
            "warning_hours": "24",
            "escalation_hours": "72",
        }),
        code_node("Build SLA Query", (440, 0), SLA_QUERY_JS,
                  notes="Builds the URLs and thresholds from settings."),
        http_node(
            "Get Exception Summary",
            (660, 0),
            method="GET",
            url="={{ $json.warning_url }}",
            notes="Fetches exception counts by severity and age.",
            retry=True,
            max_tries=2,
            wait_ms=2000,
            on_error="continueErrorOutput",
        ),
        audit_node(
            "Record Summary Failure",
            (880, 180),
            "RETRY_EXHAUSTED",
            data_expr="{stage: 'sla_summary', detail: 'Exception summary call failed after 2 attempts.'}",
            notes="Terminal. No summary, no escalation.",
        ),
        code_node("Interpret SLA", (880, -140), SLA_INTERPRET_JS,
                  notes="Interprets the summary and determines action."),
        if_node(
            "Summary Ok?",
            (1100, -140),
            left="{{ $json.state }}",
            right="completed",
            notes="A failed summary call stops the run; we cannot escalate what we cannot see.",
        ),
        audit_node(
            "Record SLA Warning",
            (1320, -140),
            "SLA_WARNING",
            data_expr="{warning_hours: $json.warning_hours, escalation_hours: $json.escalation_hours, detail: 'SLA check completed; warnings and escalations recorded on individual exceptions.'}",
            notes="SLA check completed. Individual exception escalations are recorded by the backend's triage endpoint.",
        ),
        sticky(
            (-40, -300),
            "## Vendor Onboarding — SLA Escalation\n\n"
            "Scheduled workflow (default 09:00 UTC daily). Finds cases in "
            "REVIEW_REQUIRED or APPROVAL_PENDING beyond their SLA thresholds "
            "and escalates them via the exception triage endpoint.\n\n"
            "**This workflow does not define SLA thresholds.** It reads them "
            "from settings. The backend owns the thresholds because the "
            "frontend displays them and the backend enforces them.",
            width=520,
            height=260,
            color=4,
        ),
    ]

    links = {
        "Schedule": [["Workflow Settings"]],
        "Workflow Settings": [["Build SLA Query"]],
        "Build SLA Query": [["Get Exception Summary"]],
        "Get Exception Summary": [["Interpret SLA"], ["Record Summary Failure"]],
        "Interpret SLA": [["Summary Ok?"]],
        "Summary Ok?": [["Record SLA Warning"]],
    }

    return workflow(
        "Vendor Onboarding — SLA Escalation",
        nodes,
        links,
        settings={"executionOrder": "v1", "saveManualExecutions": True, "callerPolicy": "workflowsFromSameOwner"},
    )


# ===========================================================================
# Workflow 4 -- Error Handler
#
# Registered as the error workflow for the other three. Receives the failed
# execution's context and records a platform incident.
#
# WHAT THIS WORKFLOW DOES NOT DO
# It does not retry, reroute, or suppress the original failure. It records
# it so the platform operators can see that something in the orchestration
# layer itself broke.
# ===========================================================================

ERROR_INTERPRET_JS = """
// The error trigger provides a structured payload describing what failed.
// This node normalises it into the incident schema.
const execution = $input.first().json;
const workflowName = execution.workflow?.name || 'unknown';
const executionId = execution.id || 'unknown';
const nodeName = execution.node?.name || 'unknown';
const nodeType = execution.node?.type || 'unknown';
const errorMessage = execution.error?.message || String(execution.error) || 'unknown error';
const lastNode = execution.lastNode || nodeName;

const out = [{
  json: {
    event_type: 'WORKFLOW_FAILED',
    workflow: workflowName,
    execution_id: executionId,
    node: lastNode,
    message: errorMessage,
    data: {
      node_type: nodeType,
      input_summary: execution.inputData ? Object.keys(execution.inputData).length : 0,
    },
    // The error trigger payload does not include a case_id. If the failed
    // workflow had one in its data, it would be in execution.data.case_id.
    case_id: execution.data?.case_id || null,
  },
}];
return out;
"""


def workflow_error_handler() -> dict:
    nodes = [
        node(
            "Error Triggered",
            "n8n-nodes-base.errorTrigger",
            1.2,
            (0, 0),
            {},
            notes=(
                "Registered as the error workflow for the orchestrator, "
                "document intake, and SLA escalation workflows. Receives the "
                "failed execution's context when any node exhausts its retries."
            ),
        ),
        settings_node("Workflow Settings", (220, 0), {}),
        code_node("Interpret Error", (440, 0), ERROR_INTERPRET_JS,
                  notes="Normalises the error trigger payload into the incident schema."),
        http_node(
            "Record Incident",
            (660, 0),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/webhooks/n8n/incident",
            json_body="={{ JSON.stringify($json) }}",
            headers={
                "X-N8N-Secret": "={{ $('Workflow Settings').first().json.callback_secret }}",
            },
            notes=(
                "Writes a platform incident row. No case_id means it appears "
                "in the recent-events view and no case timeline, which is "
                "correct for an orchestration failure that never resolved a case."
            ),
            retry=True,
            max_tries=3,
            wait_ms=2000,
            on_error="continueRegularOutput",
        ),
        audit_node(
            "Record Incident Failure",
            (880, 180),
            "RETRY_EXHAUSTED",
            data_expr="{stage: 'error_handler', detail: 'Incident recording failed after 3 attempts; the original workflow failure is now invisible in the audit trail.'}",
            notes="Terminal. If even the error handler cannot record, the failure is silent.",
        ),
        audit_node(
            "Record Incident Success",
            (880, -140),
            "WORKFLOW_COMPLETED",
            data_expr="{outcome: 'incident_recorded', workflow: $json.workflow, node: $json.node, case_id: $json.case_id}",
            notes="Terminal success. The platform incident is visible in the recent-events view.",
        ),
        sticky(
            (-40, -260),
            "## Vendor Onboarding — Error Handler\n\n"
            "Registered as the error workflow for the other orchestration "
            "workflows. When any node in those workflows exhausts its retries, "
            "this workflow receives the execution context and records a platform "
            "incident.\n\n"
            "**This workflow does not retry the failed work.** It records the "
            "fact that the orchestration layer itself failed, so platform "
            "operators can see it in the recent-events view. The original work "
            "must be retried by a human (or by re-triggering the upstream "
            "webhook) once the root cause is fixed.",
            width=520,
            height=280,
            color=4,
        ),
    ]

    links = {
        "Error Triggered": [["Workflow Settings"]],
        "Workflow Settings": [["Interpret Error"]],
        "Interpret Error": [["Record Incident"]],
        "Record Incident": [["Record Incident Success"], ["Record Incident Failure"]],
    }

    return workflow(
        "Vendor Onboarding — Error Handler",
        nodes,
        links,
        settings={"executionOrder": "v1", "saveManualExecutions": True, "callerPolicy": "workflowsFromSameOwner"},
    )


# ===========================================================================
# Entry point
# ===========================================================================


def workflow_case_orchestrator() -> dict:
    nodes = [
        node(
            "Case Triggered",
            "n8n-nodes-base.webhook",
            2,
            (0, 0),
            {
                "httpMethod": "POST",
                "path": "vendor-onboarding/case",
                "responseMode": "onReceived",
                "options": {},
            },
            notes=(
                "POST /webhook/vendor-onboarding/case with "
                "{case_id, action, metadata}. Responds 200 immediately: the "
                "assessment can take seconds, and a caller should not hold a "
                "connection open waiting for it. The outcome is written to the "
                "case audit trail, which is where the UI reads it from."
            ),
            extra={"webhookId": _uid()},
        ),
        settings_node(
            "Workflow Settings",
            (220, 0),
            {
                "max_assessment_retries": "3",
                "orchestrator_version": "1.0.0",
            },
        ),
        code_node(
            "Validate Trigger",
            (440, 0),
            VALIDATE_TRIGGER_JS,
            notes="Rejects a malformed trigger before it can build a URL.",
        ),
        audit_node(
            "Record Trigger Started",
            (660, 0),
            "WORKFLOW_TRIGGERED",
            data_expr="{action: $json.action, trigger_metadata: $json.trigger_metadata}",
        ),
        http_node(
            "Submit Case",
            (880, 0),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/onboarding/{{ $('Validate Trigger').first().json.case_id }}/submit",
            full_response=True,
            notes=(
                "Moves the case from DRAFT into document collection. A 409 here "
                "is the idempotent path, not an error."
            ),
            on_error="continueRegularOutput",
        ),
        code_node(
            "Interpret Submit",
            (1100, 0),
            INTERPRET_SUBMIT_JS,
            notes="Classifies the submit response; only a real failure stops the run.",
        ),
        if_node(
            "Submission Ok?",
            (1320, 0),
            left="{{ $json.submission_ok }}",
            right="yes",
            notes="A case that cannot be submitted is not assessed.",
        ),
        audit_node(
            "Record Submission Blocked",
            (1540, 180),
            "WORKFLOW_FAILED",
            data_expr="{state: $json.submission_state, detail: $json.submission_detail, http_status: $json.submission_http_status}",
            notes="Terminal. The case never reached assessment.",
        ),
        http_node(
            "Run Assessment",
            (1540, -140),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/onboarding/{{ $('Validate Trigger').first().json.case_id }}/assess",
            notes=(
                "The one call that does real work. It runs the deterministic "
                "rules, the explainable scorer, the document checks and the AI "
                "advisory inside the backend -- n8n only triggers it."
            ),
            retry=True,
            max_tries=3,
            wait_ms=3000,
            on_error="continueErrorOutput",
        ),
        audit_node(
            "Record Assessment Failure",
            (1760, 60),
            "RETRY_EXHAUSTED",
            data_expr="{stage: 'assessment', detail: 'Assessment call failed after 3 attempts.'}",
            case_expr="$('Validate Trigger').first().json.case_id",
            notes="Terminal. Reached only after the retries are spent.",
        ),
        code_node(
            "Interpret Assessment",
            (1760, -140),
            INTERPRET_ASSESSMENT_JS,
            notes="Maps the backend's route onto orchestration actions. Does not decide the route.",
        ),
        http_node(
            "Get Eligible Reviewers",
            (1980, -140),
            method="GET",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/approvals/reviewers",
            query={"approval_type": "={{ $json.reviewer_query_type }}"},
            notes=(
                "Who may actually decide this approval type, according to the "
                "backend's authority table. The workflow does not keep its own "
                "copy of who is allowed to approve what."
            ),
            retry=True,
            max_tries=2,
            wait_ms=2000,
        ),
        code_node(
            "Select Reviewer",
            (2200, -140),
            SELECT_REVIEWER_JS,
            notes="Deterministic pick, so a retry cannot route the same case to a different person.",
        ),
        if_node(
            "Reviewer Available?",
            (2420, -140),
            left="{{ $json.reviewer_available }}",
            right="yes",
            notes="With no eligible reviewer the case has nowhere to go, and that is escalated rather than ignored.",
        ),
        audit_node(
            "Record No Eligible Reviewer",
            (2640, 60),
            "WORKFLOW_FAILED",
            data_expr="{stage: 'reviewer_resolution', reason: $json.reviewer_reason, route: $json.route}",
            notes="Terminal. An unstaffed queue is an operational failure, not a quiet no-op.",
        ),
        http_node(
            "Notify Reviewer",
            (2640, -340),
            method="POST",
            url="={{ $('Workflow Settings').first().json.notification_base_url }}/notify",
            json_body="={{ JSON.stringify($json.notification) }}",
            notes=(
                "Best-effort. A notification failure is recorded but does not "
                "stop the approval from being opened -- the work is real even "
                "if nobody was told about it."
            ),
            on_error="continueRegularOutput",
        ),
        code_node(
            "Interpret Notification",
            (2860, -340),
            INTERPRET_NOTIFICATION_JS,
            notes="Classifies the notification outcome; the approval opens regardless.",
        ),
        audit_node(
            "Record Notification",
            (3080, -340),
            "",
            event_type_expr="{{ $json.notification_state }}",
            data_expr=(
                "{detail: $json.notification_detail, http_status: $json.notification_http_status, "
                "recipient: $json.recipient}"
            ),
            case_expr="$('Validate Trigger').first().json.case_id",
            notes="Records SENT or FAILED; the approval still opens.",
        ),
        switch_node(
            "Route Decision",
            (3300, -340),
            left="{{ $json.route }}",
            matches=[
                ("auto_approve", "Open Manager Approval"),
                ("compliance_review", "Open Compliance Approval"),
                ("senior_review", "Open Senior Compliance Approval"),
                ("escalate", "Open Escalated Approval"),
                ("blocked", "Record Blocked Case"),
            ],
            notes="One branch per route; no shared downstream node. Prevents double-execution on multi-branch fire.",
        ),
        http_node(
            "Open Manager Approval",
            (3520, -780),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/approvals/",
            json_body=(
                "={{ JSON.stringify({case_id: $json.case_id, approval_type: 'manager', "
                "requested_from_id: $json.reviewer.id}) }}"
            ),
            notes="Terminal. No findings; auto-approval path opened for manager.",
            retry=True,
            max_tries=3,
            wait_ms=2000,
            on_error="continueErrorOutput",
        ),
        http_node(
            "Open Compliance Approval",
            (3520, -500),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/approvals/",
            json_body=(
                "={{ JSON.stringify({case_id: $json.case_id, approval_type: 'compliance', "
                "requested_from_id: $json.reviewer.id}) }}"
            ),
            notes="Terminal. Findings exist but none of them block completion.",
            retry=True,
            max_tries=3,
            wait_ms=2000,
            on_error="continueErrorOutput",
        ),
        http_node(
            "Open Senior Compliance Approval",
            (3520, -360),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/approvals/",
            json_body=(
                "={{ JSON.stringify({case_id: $json.case_id, approval_type: 'compliance', "
                "requested_from_id: $json.reviewer.id}) }}"
            ),
            notes=(
                "Terminal. Routed to the compliance lead by the notification "
                "audience; the approval type itself is unchanged, because the "
                "authority table is the backend's to define."
            ),
            retry=True,
            max_tries=3,
            wait_ms=2000,
            on_error="continueErrorOutput",
        ),
        http_node(
            "Open Escalated Approval",
            (3520, -220),
            method="POST",
            url="={{ $('Workflow Settings').first().json.backend_base_url }}/api/approvals/",
            json_body=(
                "={{ JSON.stringify({case_id: $json.case_id, approval_type: 'compliance', "
                "requested_from_id: $json.reviewer.id}) }}"
            ),
            notes="Terminal. Multiple or severe findings; senior review required.",
            retry=True,
            max_tries=3,
            wait_ms=2000,
            on_error="continueErrorOutput",
        ),
        audit_node(
            "Record Blocked Case",
            (3520, -80),
            "WORKFLOW_COMPLETED",
            data_expr=(
                "{outcome: 'blocked_by_findings', route: $json.route, "
                "risk_score: $json.risk_score, "
                "detail: 'Blocking findings prevent completion. No approval opened; a reviewer must triage them first.'}"
            ),
            notes=(
                "Terminal. A blocked case opens no approval on purpose: there "
                "is nothing to approve until the blocking findings are cleared, "
                "and opening one anyway would put a decision in front of a "
                "reviewer that they are not yet able to make."
            ),
        ),
        audit_node(
            "Record Unexpected Route",
            (3520, 60),
            "WORKFLOW_FAILED",
            data_expr="{route: $json.route, detail: 'Route not recognised by this workflow version.'}",
            notes="Fallback output. Reached only if the backend returns a route this workflow does not know.",
        ),
        sticky(
            (-40, -520),
            "## Vendor Onboarding — Case Orchestrator\n\n"
            "Triggered by the backend when a case is ready to be assessed.\n\n"
            "**This workflow contains no business logic.** It does not score, "
            "route, validate, or decide. It moves data in the right order, "
            "retries what can be retried, and records what it did.\n\n"
            "The route comes back from the backend's deterministic rule engine "
            "and explainable scorer. The AI advisory is recorded beside it and "
            "never influences it.",
            width=520,
            height=300,
            color=4,
        ),
        sticky(
            (1300, 260),
            "### Idempotency\n\n"
            "Re-running this workflow on the same case is safe. A case already "
            "past DRAFT answers 409 to the submit call, which is treated as "
            "success and the assessment continues.\n\n"
            "Reviewer selection is deterministic, so a retry cannot deliver the "
            "same case to a different person.",
            width=440,
            height=220,
            color=3,
        ),
        sticky(
            (3480, -800),
            "### Branches\n\n"
            "Each branch is a single terminal node. There is no shared "
            "node downstream of the switch: in n8n a node with several "
            "incoming branches executes once per branch that fires, which "
            "silently doubles audit writes when two branches light up. One "
            "terminal per branch makes that impossible.",
            width=480,
            height=240,
            color=5,
        ),
    ]

    links = {
        "Case Triggered": [["Workflow Settings"]],
        "Workflow Settings": [["Validate Trigger"]],
        "Validate Trigger": [["Record Trigger Started"]],
        "Record Trigger Started": [["Submit Case"]],
        "Submit Case": [["Interpret Submit"]],
        "Interpret Submit": [["Submission Ok?"]],
        "Submission Ok?": [["Run Assessment"], ["Record Submission Blocked"]],
        "Run Assessment": [["Interpret Assessment"], ["Record Assessment Failure"]],
        "Interpret Assessment": [["Get Eligible Reviewers"]],
        "Get Eligible Reviewers": [["Select Reviewer"]],
        "Select Reviewer": [["Reviewer Available?"]],
        "Reviewer Available?": [["Notify Reviewer"], ["Record No Eligible Reviewer"]],
        "Notify Reviewer": [["Interpret Notification"]],
        "Interpret Notification": [["Record Notification"]],
        "Record Notification": [["Route Decision"]],
        "Route Decision": [
            ["Open Manager Approval"],
            ["Open Compliance Approval"],
            ["Open Senior Compliance Approval"],
            ["Open Escalated Approval"],
            ["Record Blocked Case"],
            ["Record Unexpected Route"],
        ],
    }

    return workflow(
        "Vendor Onboarding — Case Orchestrator",
        nodes,
        links,
        settings={
            "executionOrder": "v1",
            # Set this to the error-handler workflow's id after importing both
            # (Settings -> Error Workflow in the n8n UI). It cannot be set here
            # because the id is assigned by the n8n instance on import.
            "saveManualExecutions": True,
            "callerPolicy": "workflowsFromSameOwner",
        },
    )


def build_all() -> dict[str, dict]:
    return {
        "case_orchestrator.json": workflow_case_orchestrator(),
        "document_intake.json": workflow_document_intake(),
        "sla_escalation.json": workflow_sla_escalation(),
        "error_handler.json": workflow_error_handler(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="validate without writing"
    )
    args = parser.parse_args()

    os.makedirs(WORKFLOW_DIR, exist_ok=True)

    workflows = build_all()
    errors = 0

    for filename, document in workflows.items():
        path = os.path.join(WORKFLOW_DIR, filename)
        try:
            assert_workflow(document)
        except WorkflowError as exc:
            print(f"VALIDATION FAILED {filename}: {exc}", file=sys.stderr)
            errors += 1
            continue

        if args.check:
            print(f"OK {filename}")
        else:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(document, handle, indent=2)
            print(f"WROTE {filename} ({len(json.dumps(document))} bytes)")

    if errors:
        print(f"\n{errors} workflow(s) failed validation.", file=sys.stderr)
        return 1

    print(f"\nAll {len(workflows)} workflow(s) valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

