import os

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.routes.auth import router as auth_router
from app.api.routes.admin import router as admin_router
from app.api.routes.voice import router as voice_router
from app.core.config import get_settings, reload_settings

app = FastAPI(
    title="AI Voice Agent Backend",
    version="1.0.0",
)

_default_cors = "http://localhost:5173,http://127.0.0.1:5173,http://localhost:3000"
_cors_origins = [
    origin.strip()
    for origin in os.getenv("CORS_ORIGINS", _default_cors).split(",")
    if origin.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def check_config():
    settings = reload_settings()
    if not settings.groq_api_key:
        print("WARNING: GROQ_API_KEY is missing — add it to .env and restart server")
    else:
        print(
            f"Groq API key loaded OK "
            f"(llm: {settings.groq_model}, stt: {settings.stt_provider}/{settings.groq_whisper_model})"
        )


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(request: Request, exc: StarletteHTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "success": False,
            "message": exc.detail if isinstance(exc.detail, str) else "Request failed",
        },
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={
            "success": False,
            "message": "Invalid request data",
        },
    )


app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(voice_router)