"""Guards against the defects that stopped this project from running.

Every test here corresponds to something that was actually broken. They are
deliberately cheap: no database fixture, no network, no LLM. That is the point
-- each of these bugs was invisible to "the server started", and a suite that
needs a seeded Postgres before it will run is a suite nobody runs.

Run with:  cd backend && python -m pytest
"""
from __future__ import annotations

import json
import uuid
from pathlib import Path

import pytest
from sqlalchemy.orm import configure_mappers

REPO_ROOT = Path(__file__).resolve().parents[2]
REQUIREMENTS = REPO_ROOT / "backend" / "requirements.txt"
WORKFLOW_DIR = REPO_ROOT / "n8n" / "workflows"


# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------


def _declared_packages() -> set[str]:
    """Package names actually requested, ignoring comments.

    A plain substring search is not good enough: requirements.txt discusses
    asyncpg and pypdf in its comments, so `"asyncpg" in text` still passes
    after the real dependency line is deleted.
    """
    names: set[str] = set()
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        # Drop any version specifier and extras: "uvicorn[standard]==0.27.0"
        name = line.split("=", 1)[0].split(">", 1)[0].split("<", 1)[0]
        name = name.split("[", 1)[0].strip()
        if name:
            names.add(name.lower().replace("_", "-"))
    return names


def test_asyncpg_is_declared():
    """app/database rewrites the URL to postgresql+asyncpg://, so the async
    driver must be installed or every request fails at connect time."""
    assert "asyncpg" in _declared_packages()


def test_pypdf_is_declared():
    """document_processing._extract_pdf imports `pypdf`; PyPDF2 does not
    provide that module, so PDF extraction always raised
    UnsupportedDocumentError."""
    assert "pypdf" in _declared_packages()


def test_database_url_is_rewritten_for_asyncpg():
    """The async engine needs the asyncpg driver in the URL."""
    import importlib
    import os

    os.environ["DATABASE_URL"] = "postgresql://u:p@host:5432/db"
    try:
        import app.database as database

        importlib.reload(database)
        assert database.ASYNC_DATABASE_URL.startswith("postgresql+asyncpg://")
    finally:
        os.environ.pop("DATABASE_URL", None)


# ---------------------------------------------------------------------------
# ORM / schema
# ---------------------------------------------------------------------------


def test_all_mappers_configure():
    """Catches ambiguous relationships.

    User.approvals and User.exceptions_resolved each had two foreign key
    paths to users, and User.audit_events pointed at a column that is not a
    foreign key at all. All three failed here, not at import, which is why
    the app started happily and then 500'd on the first real query.
    """
    import app.models  # noqa: F401  (registers the mappers)

    configure_mappers()


def test_vendor_name_index_declares_trigram_opclass():
    """A GIN index over a varchar has no default operator class; without
    gin_trgm_ops Postgres refuses the CREATE INDEX and startup aborts."""
    from app.models import Vendor

    indexes = list(Vendor.__table__.args) if False else Vendor.__table_args__
    gin = [i for i in indexes if getattr(i, "name", None) == "ix_vendors_legal_name_trgm"]
    assert gin, "the trigram index is gone; this test needs updating"
    dialect_options = gin[0].dialect_options["postgresql"]
    assert dialect_options["using"] == "gin"
    assert dialect_options["ops"].get("legal_name") == "gin_trgm_ops"


def test_user_has_no_audit_events_collection():
    """AuditEvent.actor_id is not a foreign key -- actors may be the system,
    the AI or n8n -- so a User.audit_events relationship can never join."""
    from app.models import User

    assert not hasattr(User, "audit_events")


def test_audit_event_user_is_view_only():
    """The relationship is spelled out with a primaryjoin because there is no
    FK to infer one from. It must stay read-only so it can never try to
    persist a non-user actor id."""
    from app.models import AuditEvent

    assert AuditEvent.user.property.viewonly is True


def test_onboarding_service_eager_loads_vendor():
    """Regression guard for the MissingGreenlet on POST /api/onboarding/.

    OnboardingCaseResponse embeds the vendor, so `create()` must re-select
    with selectinload rather than flush + refresh, and `get()` must eager
    load too (it backs update/update_status/update_risk). This asserts on
    the source because exercising it needs a live database.
    """
    import inspect

    from app.services.onboarding_service import OnboardingService

    for name in ("create", "get"):
        source = inspect.getsource(getattr(OnboardingService, name))
        assert "selectinload" in source, f"{name}() lost its eager load of vendor"


# ---------------------------------------------------------------------------
# Generated n8n workflows
# ---------------------------------------------------------------------------


def _workflow_paths():
    paths = sorted(WORKFLOW_DIR.glob("*.json"))
    assert paths, f"no workflows found in {WORKFLOW_DIR}"
    return paths


def _iter_strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _iter_strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _iter_strings(value)
    elif isinstance(node, str):
        yield node


def test_every_expression_is_prefixed_with_equals():
    """n8n only evaluates a parameter as an expression when it starts with
    '='. A bare '{{ $env.VOR_BACKEND_URL }}' is stored as literal text: the
    HTTP node built an invalid URL and IF nodes compared the literal string
    against 'yes' and always took the failure branch.
    """
    for path in _workflow_paths():
        document = json.loads(path.read_text(encoding="utf-8"))
        for node in document.get("nodes", []):
            for text in _iter_strings(node.get("parameters", {})):
                if "{{" in text:
                    assert text.startswith("="), (
                        f"{path.name}: node '{node.get('name')}' has an "
                        f"expression without the '=' prefix: {text!r}"
                    )


def test_workflows_carry_stable_ids():
    """n8n 2.x rejects an import with no workflow id, and a random id would
    make every re-import add a duplicate instead of updating."""
    for path in _workflow_paths():
        document = json.loads(path.read_text(encoding="utf-8"))
        name = document["name"]
        expected = str(uuid.uuid5(uuid.NAMESPACE_URL, f"vendor-onboarding/{name}"))
        assert document.get("id") == expected, f"{path.name}: id is not stable"


def test_workflow_tags_carry_ids():
    """Bare tag names fail the import with 'NOT NULL constraint failed:
    workflows_tags.tagId'."""
    for path in _workflow_paths():
        document = json.loads(path.read_text(encoding="utf-8"))
        tags = document.get("tags", [])
        assert tags, f"{path.name}: no tags"
        for tag in tags:
            assert isinstance(tag, dict) and tag.get("id"), (
                f"{path.name}: tag without an id: {tag!r}"
            )


# ---------------------------------------------------------------------------
# Application wiring
# ---------------------------------------------------------------------------


def test_app_exposes_health_and_api_routes():
    from app.main import app

    paths = {route.path for route in app.routes}
    assert "/health" in paths
    assert "/api/vendors/" in paths
    assert "/api/webhooks/n8n" in paths


def test_inbound_webhook_is_the_only_n8n_route_in_the_backend():
    """The backend does not call n8n. It exposes one inbound route that n8n
    reports to; asserting that here stops the old README claim from quietly
    becoming true-by-accident."""
    from app.main import app

    n8n_callables = {
        route.path for route in app.routes if "n8n" in getattr(route, "path", "")
    }
    assert n8n_callables == {"/api/webhooks/n8n", "/api/webhooks/n8n/event-types",
                             "/api/webhooks/n8n/incident"}


@pytest.mark.parametrize(
    "module",
    ["app.services.pipeline", "app.services.document_processing", "app.rules.engine"],
)
def test_core_modules_import(module):
    """Import-time failures here were silent until a request hit them."""
    __import__(module)
