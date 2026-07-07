"""
Audit logger — consumes the RequestContext event stream and emits one
structured record per request.
"""
import json
import logging

from app.observability.context import RequestContext

audit_logger = logging.getLogger("nom-py.audit")


def emit(ctx: RequestContext) -> None:
    """Emit one structured audit record for the entire request."""
    audit_logger.info(json.dumps({
        "request_id": ctx.request_id,
        "user_id": ctx.principal.user_id if ctx.principal else None,
        "method": ctx.method,
        "duration_ms": ctx.duration_ms,
        "events": ctx.events,
    }))