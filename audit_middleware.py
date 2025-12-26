from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.services.audit_service import log_action

class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        await log_action(
            user=getattr(request.state, "user", None),
            action=request.url.path,
            status=response.status_code,
        )
        return response
