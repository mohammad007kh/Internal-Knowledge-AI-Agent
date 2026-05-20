"""MongoDB schema inspector for the studying-agent (schema-on-read).

MongoDB has no declared schema, so this inspector *infers* one by sampling
a small number of documents per collection and unioning their top-level
keys.  It follows the same six-phase shape as the SQL inspector — see
:mod:`src.services.db_introspection.sql_inspector` — adapted as follows:

1. **CONNECTING** — ``AsyncIOMotorClient(uri)``, ping the database.  Fatal
   failures raise :class:`SchemaStudyPhaseError(phase='CONNECTING', ...)`.
2. **INVENTORY** — ``db.list_collection_names()`` (skip ``system.*``), cap
   at :data:`_MAX_COLLECTIONS`.  Each becomes a
   ``TableDoc(name="db.coll", kind="collection")``.
3. **COLUMNS** — per collection: sample up to :data:`_SAMPLE_DOCS` docs via
   ``find().limit(N)``, union their top-level keys, infer each field's type
   from the sampled values.  Every Mongo column is ``inferred=True`` and
   ``nullable=True`` (schema-on-read).  Per-collection failure → a
   ``PhaseError`` row, the collection is skipped, study continues.
4. **SAMPLING** — for each field, ≤3 distinct non-null PII-redacted values
   pulled from the docs already sampled in COLUMNS (no extra round-trip).
   BSON binary fields are never fetched/stringified.  Per-collection
   failure → a ``PhaseError`` row.
5. **DESCRIBING** — same as the SQL inspector: per-collection
   ``schema_inspector``-stage LLM call → 2-3 sentence description + ≤3
   tags; then one corpus-summary call.  No resolver → skipped + partial.
6. **INDEXING** — no-op; ``vector_index_ref=None``.

``motor`` / ``pymongo`` are **not** installed in this environment; the
driver import is done lazily inside :func:`study_mongo_schema` so this
module always imports cleanly.  If the driver genuinely isn't present the
function raises ``SchemaStudyPhaseError(phase='CONNECTING',
error_key='MONGO_DRIVER_MISSING', ...)``.

Read-only everywhere: only ``ping``, ``list_collection_names`` and
``find().limit(N)`` are ever issued — never a write.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, Final

from src.services.db_introspection._errors import SchemaStudyPhaseError
from src.services.db_introspection.fingerprint import compute_fingerprint
from src.services.db_introspection.pii_redaction import (
    column_name_looks_pii,
    looks_pii,
    redact_value,
)
from src.services.db_introspection.schema_doc import (
    ColumnDoc,
    PhaseError,
    SchemaDocument,
    TableDoc,
)

if TYPE_CHECKING:  # pragma: no cover - typing only
    from src.services.ai_model_resolver import AIModelResolver

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants / caps  (kept consistent with sql_inspector where they overlap)
# ---------------------------------------------------------------------------

#: Studying-agent version stamped on the document. Kept in sync with
#: :data:`src.services.db_introspection.sql_inspector.AGENT_VERSION` and
#: :data:`src.tasks.study_source._AGENT_VERSION`.
AGENT_VERSION = "studying-agent@0.3"

#: Hard cap on collections inspected per source (mirrors sql_inspector's
#: ``_MAX_TABLES`` so a database with 5k collections can't run away).
_MAX_COLLECTIONS = 200

#: Documents sampled per collection (the schema-on-read "peek").
_SAMPLE_DOCS = 25

#: Max distinct sample values stored per field (contract caps at 3 too).
_MAX_SAMPLES_PER_FIELD = 3

#: Wall-clock budget for the SAMPLING phase across the whole source (seconds).
_SAMPLING_BUDGET_SECONDS = 60.0

#: Wall-clock budget for the DESCRIBING phase across the whole source (seconds).
_DESCRIBING_BUDGET_SECONDS = 120.0

#: Resolver stage slot for the per-collection / summary LLM calls.
_LLM_STAGE = "schema_inspector"

#: Collection-name prefixes we never inspect (Mongo internal bookkeeping).
_SYSTEM_PREFIXES: Final[tuple[str, ...]] = ("system.",)


# --- Error-message sanitisation -------------------------------------------
#
# Mirrors sql_inspector._sanitise — anything headed for a persisted
# PhaseError must not leak the connection URI or credentials.

#: DSN-style ``key=value`` fragments that name the host/db/user/credentials.
#: pymongo error text rarely uses this shape, but a wrapped driver/socket
#: error might; redacting it is harmless either way.
_DSN_KV_RE: Final[re.Pattern[str]] = re.compile(
    r"\b(host|hostaddr|port|dbname|database|user|username|password|passwd)\s*=\s*"
    r"('[^']*'|\"[^\"]*\"|\S+)",
    re.IGNORECASE,
)

#: ``scheme://user:pass@host`` → ``scheme://***@host``
_CRED_URL_RE: Final[re.Pattern[str]] = re.compile(r"://[^@\s/]+@")

#: A bare ``hostname:port`` (2-5 digit port).
_HOST_PORT_RE: Final[re.Pattern[str]] = re.compile(r"\b[\w.-]+:\d{2,5}\b")


def _sanitise(message: object) -> str:
    """Redact credentials / host:port fragments from an error message.

    Order matters: redact credentials *first* — the DSN ``key=value``
    fragments and the ``scheme://user:pass@`` URL form — then collapse any
    remaining bare ``host:port``.  Doing it the other way round risks the
    ``host:port`` regex mangling an all-digit password fragment (e.g.
    ``user:1234@``) into ``<host>:<port>`` before the credential redaction
    sees it.
    """
    text = str(message)
    text = _DSN_KV_RE.sub(lambda m: f"{m.group(1).lower()}=<redacted>", text)
    text = _CRED_URL_RE.sub("://***@", text)
    text = _HOST_PORT_RE.sub("<host>:<port>", text)
    return text


# ---------------------------------------------------------------------------
# Type inference (schema-on-read)
# ---------------------------------------------------------------------------


def _class_name(value: object) -> str:
    """Return the (lowercased) class name of *value* — used for BSON detection
    without importing ``bson`` (not installed in this environment)."""
    return type(value).__name__.lower()


def _is_objectid(value: object) -> bool:
    return _class_name(value) == "objectid"


def _is_bson_binary(value: object) -> bool:
    # bson.Binary subclasses bytes; also the legacy ``bson.binary.Binary``.
    name = _class_name(value)
    return name in {"binary"} or isinstance(value, (bytes, bytearray, memoryview))


def _native_bson_name(value: object) -> str:
    """A human-ish BSON type name for ``ColumnDoc.native_type`` (audit-only)."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        # Mongo distinguishes int32 / int64, but the Python driver collapses
        # both to ``int``; we can't tell them apart from a sampled value.
        return "int"
    if isinstance(value, float):
        return "double"
    if isinstance(value, str):
        return "string"
    if isinstance(value, datetime):
        return "date"
    if _is_objectid(value):
        return "objectId"
    if _is_bson_binary(value):
        return "binData"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        return "array"
    return _class_name(value) or "unknown"


def _infer_type(value: object) -> str:
    """Map one sampled value to a contract :data:`ColumnTypeLiteral`.

    Lists become ``array<T>`` where ``T`` is inferred from the first element
    (``array<unknown>`` for an empty list).  ``ObjectId`` → ``"uuid"`` (it's
    the closest fixed-shape opaque identifier in the contract enum).
    """
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, datetime):
        return "datetime"
    if _is_objectid(value):
        return "uuid"
    if _is_bson_binary(value):
        return "binary"
    if isinstance(value, str):
        return "text"
    if isinstance(value, dict):
        return "object"
    if isinstance(value, (list, tuple)):
        seq = list(value)
        if not seq:
            return "array<unknown>"
        return f"array<{_infer_type(seq[0])}>"
    return "unknown"


def _coalesce_field_type(values: list[object]) -> str:
    """Pick a single contract type for a field given its sampled values.

    Skips ``None`` (a missing key contributes nothing).  If the non-null
    values disagree, ``"unknown"`` is the honest answer; if they all agree,
    that type wins; if there are no non-null values at all, ``"unknown"``.
    """
    inferred = {_infer_type(v) for v in values if v is not None}
    if not inferred:
        return "unknown"
    if len(inferred) == 1:
        return next(iter(inferred))
    # Mixed — collapse array<*>/array<*> down to a single "array<unknown>" if
    # they're all arrays; otherwise just "unknown".
    if all(t.startswith("array<") for t in inferred):
        return "array<unknown>"
    return "unknown"


def _coalesce_native_type(values: list[object]) -> str:
    names = {_native_bson_name(v) for v in values if v is not None}
    if not names:
        return "null"
    return next(iter(sorted(names))) if len(names) == 1 else "mixed"


# ---------------------------------------------------------------------------
# Driver access (lazy)
# ---------------------------------------------------------------------------


def _import_motor_client() -> Any:
    """Return ``AsyncIOMotorClient``, or raise a CONNECTING phase error.

    The import is done here (not at module load) so this module imports
    cleanly even when ``motor`` / ``pymongo`` aren't installed.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient  # noqa: PLC0415
    except Exception:  # noqa: BLE001 - missing/broken driver
        raise SchemaStudyPhaseError(
            phase="CONNECTING",
            error_key="MONGO_DRIVER_MISSING",
            message=(
                "The MongoDB driver (motor/pymongo) is not installed; cannot "
                "study a MongoDB source."
            ),
        ) from None
    return AsyncIOMotorClient


# ---------------------------------------------------------------------------
# Phases
# ---------------------------------------------------------------------------


async def _phase_connecting(client: Any, database: str) -> None:
    try:
        await client[database].command("ping")
    except Exception as exc:  # noqa: BLE001 - classify + re-raise sanitised
        message = _sanitise(exc).lower()
        if "timeout" in message or "timed out" in message:
            error_key = "CONNECT_TIMEOUT"
        elif (
            "auth" in message
            or "password" in message
            or "not authorized" in message
            or "unauthorized" in message
        ):
            error_key = "CONNECT_AUTH_FAILED"
        else:
            error_key = "CONNECT_REFUSED"
        raise SchemaStudyPhaseError(
            phase="CONNECTING",
            error_key=error_key,
            message="Could not connect to the MongoDB source (see server logs).",
        ) from None


async def _phase_inventory(
    client: Any, database: str, collection_filter: str | None
) -> tuple[list[str], int]:
    """Return ``(collection_names, total_seen)``.

    *collection_filter* — when set, restrict to that single collection (the
    source config's ``collection`` key).

    ``total_seen`` is the full count of non-system collections the source
    reported (before the :data:`_MAX_COLLECTIONS` cap is applied) so the
    orchestrator can populate :attr:`SchemaDocument.truncated_at`. An empty
    inventory is NOT fatal — the database may simply have no collections yet
    and the admin viewer surfaces a distinct empty-database state.

    Raises :class:`SchemaStudyPhaseError` only when the listing itself
    fails (a fatal INVENTORY error).
    """
    try:
        names = await client[database].list_collection_names()
    except SchemaStudyPhaseError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise SchemaStudyPhaseError(
            phase="INVENTORY",
            error_key="LIST_FAILED",
            message=f"Could not list MongoDB collections: {_sanitise(exc)}",
        ) from None

    collections = [
        n
        for n in names
        if not any(n.startswith(p) for p in _SYSTEM_PREFIXES)
    ]
    if collection_filter:
        collections = [n for n in collections if n == collection_filter]
    collections.sort()

    total_seen = len(collections)
    if total_seen > _MAX_COLLECTIONS:
        logger.warning(
            "mongo_inspector: source has %d collections; truncating to %d",
            total_seen,
            _MAX_COLLECTIONS,
        )
        collections = collections[:_MAX_COLLECTIONS]
    return collections, total_seen


async def _sample_docs(client: Any, database: str, collection: str) -> list[dict[str, Any]]:
    """``find().limit(_SAMPLE_DOCS)`` — the schema-on-read peek for one collection."""
    cursor = client[database][collection].find().limit(_SAMPLE_DOCS)
    # Motor cursors expose ``to_list(length=...)``; the in-test fake mirrors it.
    docs = await cursor.to_list(length=_SAMPLE_DOCS)
    return [d for d in docs if isinstance(d, dict)]


def _columns_from_docs(docs: list[dict[str, Any]]) -> list[ColumnDoc]:
    """Union the top-level keys of *docs* and infer each field's type.

    Order: ``_id`` first (if present), then the remaining keys in first-seen
    order — stable so the fingerprint is reproducible across runs.
    """
    ordered_keys: list[str] = []
    seen: set[str] = set()
    for doc in docs:
        for key in doc.keys():
            sk = str(key)
            if sk not in seen:
                seen.add(sk)
                ordered_keys.append(sk)
    if "_id" in seen:
        ordered_keys = ["_id"] + [k for k in ordered_keys if k != "_id"]

    columns: list[ColumnDoc] = []
    for key in ordered_keys:
        values = [doc[key] for doc in docs if key in doc]
        columns.append(
            ColumnDoc(
                name=key,
                type=_coalesce_field_type(values),
                native_type=_coalesce_native_type(values),
                nullable=True,  # schema-on-read: any doc may omit any key
                default=None,
                sample_values=[],
                is_pii_candidate=column_name_looks_pii(key),
                inferred=True,
            )
        )
    return columns


def _fill_samples_from_docs(
    columns: list[ColumnDoc], docs: list[dict[str, Any]]
) -> list[ColumnDoc]:
    """Return a *new* list of columns with ``sample_values`` populated.

    ≤3 distinct, PII-redacted values per field, pulled from *docs* (already
    sampled in COLUMNS — no extra round-trip).  BSON binary fields are
    skipped entirely — never fetched/stringified.  The input ``columns`` are
    not mutated; each gets a fresh copy via :meth:`~pydantic.BaseModel.model_copy`.
    """
    column_names = {c.name for c in columns}
    per_field: dict[str, list[str]] = {c.name: [] for c in columns}
    for doc in docs:
        for key, raw in doc.items():
            name = str(key)
            if name not in column_names:
                continue
            if len(per_field[name]) >= _MAX_SAMPLES_PER_FIELD:
                continue
            if raw is None or _is_bson_binary(raw):
                continue
            # Don't try to stringify whole nested objects/arrays as a "value".
            if isinstance(raw, (dict, list, tuple)):
                continue
            redacted = redact_value(raw)
            if redacted in per_field[name]:
                continue
            per_field[name].append(redacted)

    enriched: list[ColumnDoc] = []
    for col in columns:
        samples = per_field.get(col.name, [])[:_MAX_SAMPLES_PER_FIELD]
        is_pii = col.is_pii_candidate or looks_pii(col.name, samples)
        enriched.append(
            col.model_copy(
                update={"sample_values": samples, "is_pii_candidate": is_pii}
            )
        )
    return enriched


# ---------------------------------------------------------------------------
# Heuristic tags + DESCRIBING (mirrors sql_inspector)
# ---------------------------------------------------------------------------

_AUDIT_NAME_RE = re.compile(r"(_log|_logs|_audit|_history|_events?)$|^audit|^event_log")


def _is_signal_free_for_llm(table: TableDoc) -> bool:
    """True iff the collection provides no useful signal for the LLM.

    Schema-on-read flavour: if COLUMNS sampled docs but found no fields and
    every column we *do* have has zero sample values, asking the LLM to
    describe the collection invites hallucination. ``row_count_estimate``
    is always ``None`` for Mongo (we never run ``count()``), so this is a
    pure "no columns and no values" check.
    """
    if not table.columns:
        return True
    return all(not c.sample_values for c in table.columns)


def _heuristic_tags(table: TableDoc) -> list[str]:
    """A couple of structural tags for a collection."""
    tags: list[str] = []
    bare = table.name.split(".")[-1].lower()
    if _AUDIT_NAME_RE.search(bare):
        tags.append("audit_log")
    n_fields = len(table.columns)
    if 1 <= n_fields <= 3:
        tags.append("lookup")
    if not tags:
        tags.append("document_store")
    seen: set[str] = set()
    out: list[str] = []
    for t in tags:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out[:3]


_TABLE_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "collection_description",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["description", "tags"],
            "properties": {
                "description": {"type": "string"},
                "tags": {
                    "type": "array",
                    "maxItems": 3,
                    "items": {"type": "string"},
                },
            },
        },
    },
}

_SUMMARY_RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "corpus_summary",
        "strict": True,
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "required": ["summary"],
            "properties": {"summary": {"type": "string"}},
        },
    },
}

_TABLE_SYSTEM_PROMPT = (
    "You are a database schema documentarian. Given a MongoDB collection's "
    "name and its inferred fields (name, inferred type, up to 3 redacted "
    "sample values), write a concise 2-3 sentence description of what the "
    "collection most likely stores. Then propose up to 3 short lowercase "
    "tags (e.g. audit_log, lookup, document_store). Never invent field "
    "names. Never echo raw values. Respond with JSON matching the schema."
)

_SUMMARY_SYSTEM_PROMPT = (
    "You are a database schema documentarian. Given a list of MongoDB "
    "collections with short descriptions, write a 4-6 sentence overview of "
    "what this database appears to be for. Respond with JSON matching the "
    "provided schema."
)


def _table_llm_payload(table: TableDoc, hints: list[str]) -> str:
    cols = [
        {"name": c.name, "type": str(c.type), "samples": c.sample_values}
        for c in table.columns
    ]
    return json.dumps(
        {
            "collection": table.name,
            "field_count": len(table.columns),
            "fields": cols,
            "structural_hints": hints,
        },
        separators=(",", ":"),
    )


async def _describe_collection(table: TableDoc, resolver: AIModelResolver) -> None:
    client = await resolver.resolve(_LLM_STAGE)
    hints = _heuristic_tags(table)
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": _TABLE_SYSTEM_PROMPT},
            {"role": "user", "content": _table_llm_payload(table, hints)},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_TABLE_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    description = payload.get("description")
    if isinstance(description, str):
        table.description = description.strip()
    llm_tags = payload.get("tags") or []
    merged: list[str] = list(hints)
    for t in llm_tags:
        if isinstance(t, str) and t.strip():
            normalised = t.strip().lower().replace(" ", "_")
            if normalised not in merged:
                merged.append(normalised)
    table.tags = merged[:3]


async def _summarise_corpus(
    tables: list[TableDoc], resolver: AIModelResolver
) -> str:
    client = await resolver.resolve(_LLM_STAGE)
    blurbs = [
        {"collection": t.name, "description": t.description, "tags": t.tags}
        for t in tables
    ]
    user_content = json.dumps(
        {"dialect": "mongodb", "collections": blurbs}, separators=(",", ":")
    )
    response = await client.http_client.chat.completions.create(
        model=client.model_id,
        messages=[
            {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        temperature=client.temperature,
        max_tokens=client.max_tokens,
        response_format=_SUMMARY_RESPONSE_FORMAT,  # type: ignore[arg-type]
    )
    raw = response.choices[0].message.content or "{}"
    payload = json.loads(raw)
    summary = payload.get("summary")
    return summary.strip() if isinstance(summary, str) else ""


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------


async def study_mongo_schema(
    *,
    uri: str,
    database: str,
    collection_filter: str | None = None,
    ai_model_resolver: AIModelResolver | None = None,
    sampling_budget_seconds: float = _SAMPLING_BUDGET_SECONDS,
    describing_budget_seconds: float = _DESCRIBING_BUDGET_SECONDS,
    _client_factory: Any | None = None,
) -> SchemaDocument:
    """Run the schema-on-read studying-agent pipeline for a MongoDB source.

    .. note::
       Known limitation: the COLUMNS phase runs ``find().limit(N)`` which
       pulls *complete* documents — including any large binary/embedded
       fields — into memory before the per-field binary-skip guard fires.
       Because the schema is inferred (not declared), there are no field
       names to project out ahead of time, so an unusually large field in
       the first ``N`` documents is fetched even though it never lands in
       the resulting ``SchemaDocument``.

    Parameters
    ----------
    uri:
        MongoDB connection URI (e.g. ``mongodb://host:27017``).  Consumed
        once here; never logged.
    database:
        Database name to inspect.
    collection_filter:
        When set, only this single collection is inspected (the source
        config's ``collection`` key); otherwise every non-``system.*``
        collection is inspected (capped at :data:`_MAX_COLLECTIONS`).
    ai_model_resolver:
        Resolver used for DESCRIBING.  ``None`` → DESCRIBING is skipped and
        the study is marked partial.
    _client_factory:
        Test seam — a callable ``(uri) -> motor-client-like``.  Production
        callers leave this ``None`` (the real ``AsyncIOMotorClient`` is
        imported lazily).

    Returns
    -------
    SchemaDocument
        ``dialect="mongodb"``, strictly validated, ``fingerprint`` via
        :func:`compute_fingerprint`, ``partial`` iff any phase error.

    Raises
    ------
    SchemaStudyPhaseError
        On a fatal failure (driver missing, cannot connect, cannot list /
        inspect any collection).
    """
    start = time.monotonic()
    phase_errors: list[PhaseError] = []
    skipped_tables: list[str] = []

    client_factory = _client_factory
    if client_factory is None:
        client_factory = _import_motor_client()  # raises CONNECTING/MONGO_DRIVER_MISSING

    try:
        client = client_factory(uri)
    except SchemaStudyPhaseError:
        raise
    except Exception:  # noqa: BLE001 - bad URI etc.
        raise SchemaStudyPhaseError(
            phase="CONNECTING",
            error_key="CONNECT_REFUSED",
            message="Could not initialise the MongoDB client (see server logs).",
        ) from None

    try:
        # --- Phase 1: CONNECTING -------------------------------------------
        await _phase_connecting(client, database)

        # --- Phase 2: INVENTORY --------------------------------------------
        coll_names, total_seen = await _phase_inventory(
            client, database, collection_filter
        )
        truncated_at: int | None = (
            total_seen if total_seen > len(coll_names) else None
        )
        tables: list[TableDoc] = [
            TableDoc(
                name=f"{database}.{name}",
                kind="collection",
                row_count_estimate=None,
                primary_key=[],  # filled in COLUMNS once we know if _id exists
                indexes=[],
                columns=[],
                relationships=[],
                description="",
                tags=[],
            )
            for name in coll_names
        ]

        # --- Phase 3: COLUMNS (sampling docs, inferring types) -------------
        # Keep (table, sampled-docs) pairs so SAMPLING reuses the same docs.
        kept: list[tuple[TableDoc, list[dict[str, Any]]]] = []
        for table, coll in zip(tables, coll_names):
            try:
                docs = await _sample_docs(client, database, coll)
            except Exception as exc:  # noqa: BLE001 - per-collection degradation
                phase_errors.append(
                    PhaseError(
                        phase="COLUMNS",
                        error_key="SAMPLE_DOCS_FAILED",
                        message=(
                            f"Could not sample documents from {table.name}: "
                            f"{_sanitise(exc)}"
                        ),
                    )
                )
                skipped_tables.append(table.name)
                logger.warning(
                    "mongo_inspector: COLUMNS failed for %s — skipping collection",
                    table.name,
                    exc_info=True,
                )
                continue
            columns = _columns_from_docs(docs)
            table.columns = columns
            if any(c.name == "_id" for c in columns):
                table.primary_key = ["_id"]
            kept.append((table, docs))
        tables = [t for t, _docs in kept]

        # --- Phase 4: SAMPLING --------------------------------------------
        sampling_deadline = time.monotonic() + sampling_budget_seconds
        sampling_truncated = False
        for table, docs in kept:
            if time.monotonic() >= sampling_deadline:
                if not sampling_truncated:
                    sampling_truncated = True
                    logger.warning(
                        "mongo_inspector: sampling budget exhausted — "
                        "remaining collections left without sample values"
                    )
                continue
            try:
                table.columns = _fill_samples_from_docs(table.columns, docs)
            except Exception as exc:  # noqa: BLE001 - never fatal
                phase_errors.append(
                    PhaseError(
                        phase="SAMPLING",
                        error_key="SAMPLE_FAILED",
                        message=(
                            f"Could not derive sample values for {table.name}: "
                            f"{_sanitise(exc)}"
                        ),
                    )
                )

        # --- Phase 5: DESCRIBING ------------------------------------------
        summary = ""
        llm_descriptions_available = True
        if ai_model_resolver is not None and tables:
            describing_deadline = time.monotonic() + describing_budget_seconds
            budget_exhausted = False
            described_any = False
            for table in tables:
                if time.monotonic() >= describing_deadline:
                    if not budget_exhausted:
                        budget_exhausted = True
                        logger.warning(
                            "mongo_inspector: describing budget exhausted"
                        )
                        phase_errors.append(
                            PhaseError(
                                phase="DESCRIBING",
                                error_key="LLM_BUDGET",
                                message=(
                                    "DESCRIBING time budget exhausted; some "
                                    "collections left undescribed."
                                ),
                            )
                        )
                    if not table.tags:
                        table.tags = _heuristic_tags(table)
                    continue
                if _is_signal_free_for_llm(table):
                    if not table.tags:
                        table.tags = _heuristic_tags(table)
                    phase_errors.append(
                        PhaseError(
                            phase="DESCRIBING",
                            error_key="NO_SIGNAL",
                            message=(
                                f"No fields or sample values for {table.name}; "
                                "skipping AI description."
                            ),
                        )
                    )
                    continue
                try:
                    await _describe_collection(table, ai_model_resolver)
                    described_any = True
                except Exception as exc:  # noqa: BLE001 - never fatal
                    if not table.tags:
                        table.tags = _heuristic_tags(table)
                    phase_errors.append(
                        PhaseError(
                            phase="DESCRIBING",
                            error_key="LLM_ERROR",
                            message=(
                                f"LLM could not describe {table.name}: "
                                f"{_sanitise(exc)}"
                            ),
                        )
                    )
            try:
                summary = await _summarise_corpus(tables, ai_model_resolver)
            except Exception as exc:  # noqa: BLE001 - never fatal
                phase_errors.append(
                    PhaseError(
                        phase="DESCRIBING",
                        error_key="LLM_ERROR",
                        message=f"LLM could not summarise the corpus: {_sanitise(exc)}",
                    )
                )
            if tables and not described_any:
                llm_descriptions_available = False
        else:
            # No resolver — heuristic tags only. We DON'T flag LLM_UNAVAILABLE
            # when there are no collections to describe.
            for table in tables:
                if not table.tags:
                    table.tags = _heuristic_tags(table)
            if ai_model_resolver is None and tables:
                phase_errors.append(
                    PhaseError(
                        phase="DESCRIBING",
                        error_key="LLM_UNAVAILABLE",
                        message="No LLM resolver available; descriptions skipped.",
                    )
                )
                llm_descriptions_available = False

        # --- Phase 6: INDEXING — not done; vector_index_ref=None.

        tables.sort(key=lambda t: t.name)
        duration_ms = max(0, int((time.monotonic() - start) * 1000))
        partial = bool(phase_errors)
        partial_coverage = bool(skipped_tables) or truncated_at is not None
        skipped_tables_sorted = sorted(set(skipped_tables))
        doc = SchemaDocument(
            dialect="mongodb",
            fingerprint="0" * 64,  # placeholder, replaced below
            generated_at=datetime.now(tz=timezone.utc),
            agent_version=AGENT_VERSION,
            study_duration_ms=duration_ms,
            partial=partial,
            partial_coverage=partial_coverage,
            skipped_tables=skipped_tables_sorted,
            truncated_at=truncated_at,
            llm_descriptions_available=llm_descriptions_available,
            phase_errors=phase_errors,
            tables=tables,
            summary=summary,
            vector_index_ref=None,
        )
        return doc.model_copy(update={"fingerprint": compute_fingerprint(doc)})
    finally:
        # Always close the motor client. ``close`` is sync on motor; the
        # in-test fake mirrors that.
        try:
            close = getattr(client, "close", None)
            if callable(close):
                close()
        except Exception:  # noqa: BLE001 - cleanup must never raise
            logger.warning("mongo_inspector: error closing motor client", exc_info=True)


__all__ = ["AGENT_VERSION", "study_mongo_schema"]
