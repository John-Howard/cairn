from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

import cairn
from cairn.activities import router as activities_router
from cairn.auth import LoginRequired
from cairn.auth import router as auth_router
from cairn.dashboard import router as dashboard_router
from cairn.regime_policy import router as regime_policy_router
from cairn.settings import get_settings
from cairn.setup import router as setup_router
from cairn.vocabularies import router as vocabularies_router

STATIC_DIR = Path(__file__).parent / "static"
GOVUK_ASSETS_DIR = STATIC_DIR / "govuk" / "assets"


def create_app() -> FastAPI:
    settings = get_settings()
    if settings.auth_mode != "dev" and settings.session_secret == "dev-secret-change-me":
        raise RuntimeError("SESSION_SECRET must be set when AUTH_MODE is not 'dev'")
    app = FastAPI()

    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.session_secret,
        session_cookie="cairn_session",
        same_site="lax",
        https_only=False,
    )

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = "default-src 'self'; frame-ancestors 'none'"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.exception_handler(LoginRequired)
    async def login_required(request: Request, exc: LoginRequired):
        if request.headers.get("HX-Request") == "true":
            return Response(status_code=401)
        return RedirectResponse("/login", status_code=302)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
    app.mount("/assets", StaticFiles(directory=str(GOVUK_ASSETS_DIR)), name="govuk-assets")

    @app.get("/healthz")
    def healthz():
        return {"status": "ok", "version": cairn.__version__}

    app.include_router(auth_router)
    app.include_router(setup_router)
    app.include_router(dashboard_router)
    app.include_router(vocabularies_router)
    app.include_router(regime_policy_router)
    app.include_router(activities_router)

    return app


app = create_app()
