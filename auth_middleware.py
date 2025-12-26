from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from app.core.security import decode_access_token

class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("Authorization")
        if token:
            payload = decode_access_token(token.replace("Bearer ", ""))
            request.state.user = payload
        return await call_next(request)
