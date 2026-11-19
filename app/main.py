from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from app.api import router
from app.keitaro import KeitaroError
from app.services.creator import CreatorError
from app.services.editor import EditorError

STATIC = Path(__file__).parent / "static"

app = FastAPI(title="Keitaro wrapper", version="1.0")
app.include_router(router)


@app.exception_handler(KeitaroError)
@app.exception_handler(CreatorError)
@app.exception_handler(EditorError)
async def domain_error(_: Request, exc):
    return JSONResponse(status_code=exc.status, content={"detail": exc.message})


@app.exception_handler(ValueError)
async def value_error(_: Request, exc: ValueError):
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.mount("/static", StaticFiles(directory=STATIC), name="static")


@app.get("/", include_in_schema=False)
def index():
    return FileResponse(STATIC / "index.html")
