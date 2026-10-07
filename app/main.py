import logging
from pathlib import Path
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from .api.files import router as files_router
from .database import Base, engine

logging.basicConfig(level=logging.INFO)

Base.metadata.create_all(engine)

app = FastAPI(
    title="Geospatial File Measurement API",
    version="1.0.0",
    description="Upload a Shapefile (.zip) or KML file, extract features, and calculate per-feature area/length measurements in projected CRS.",
)

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=BASE_DIR / "templates")

app.include_router(files_router)


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def home_dashboard(request: Request):
    """
    Interactive web UI dashboard for visual file testing, map rendering, and measurement inspection.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health", tags=["meta"])
def health():
    return {"status": "ok", "service": "Geospatial File Measurement API"}
