"""
ThreatRecall Authentication — Community stub.

Community edition runs in single-tenant mode with no authentication.
For multi-tenant OAuth/JWT, install zettelforge-enterprise.

This stub provides the same interface so web/app.py works without changes.
"""
from typing import Optional, Dict

_default_mm = None


def get_current_user(request) -> Optional[Dict]:
    """Community: no authentication, always returns None."""
    return None


def get_mm_for_request(request):
    """Community: single-tenant mode, returns the default MemoryManager."""
    global _default_mm
    if _default_mm is None:
        from zettelforge import MemoryManager
        _default_mm = MemoryManager()
    return _default_mm


def register_auth_routes(app):
    """Community: register minimal auth endpoints that report single-tenant mode."""

    @app.get("/auth/me")
    async def me():
        return {"authenticated": False, "edition": "community"}

    @app.get("/auth/providers")
    async def providers():
        return {
            "providers": [],
            "message": "Multi-tenant auth requires ThreatRecall Enterprise. https://threatengram.com/enterprise",
        }

    @app.get("/auth/login/{provider}")
    async def login(provider: str):
        from fastapi.responses import JSONResponse
        return JSONResponse(
            status_code=402,
            content={"error": "OAuth requires ThreatRecall Enterprise", "upgrade_url": "https://threatengram.com/enterprise"},
        )
