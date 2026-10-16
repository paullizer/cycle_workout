import io
import json
import zipfile
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, Response
from pydantic import ValidationError
from starlette.datastructures import UploadFile
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.concurrency import run_in_threadpool

from terrain_coach.fit_export import course_fit, workout_fit
from terrain_coach.models import Rider, WorkoutSpec
from terrain_coach.planner import plan_workout
from terrain_coach.report import TRANSFER_INSTRUCTIONS, clock, cue_sheet, plan_summary
from terrain_coach.route import MAX_UPLOAD_BYTES, parse_route


class UploadTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        received = 0

        async def limited_receive():
            nonlocal received
            message = await receive()
            received += len(message.get("body", b""))
            if received > MAX_UPLOAD_BYTES + 128 * 1024:
                raise UploadTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except UploadTooLarge:
            response = Response('{"detail":"Upload exceeds 10 MiB plus form overhead."}', 413,
                                media_type="application/json")
            await response(scope, receive, send)


app = FastAPI(title="Terrain Coach", docs_url=None, redoc_url=None)
app.add_middleware(BodyLimitMiddleware)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]"])


@app.get("/", response_class=HTMLResponse)
def index():
    return Path(__file__).with_name("web.html").read_text(encoding="utf-8")


@app.get("/docs", response_class=HTMLResponse)
def docs():
    return """<!doctype html><html lang="en"><meta charset="utf-8"><title>Terrain Coach API</title>
<h1>Local API</h1><p>POST /plan with multipart fields <code>route</code> (GPX/TCX/FIT file),
<code>rider</code> (Rider JSON), and <code>spec</code> (WorkoutSpec JSON).
Omit rider/spec to use defaults. Durations and placement offsets are in seconds; weights are in pounds;
power is watts, except endurance values when endurance_unit is "percent". Grade tolerance is a fraction
(0.015 = 1.5 percentage points).</p><p>Returns a ZIP with two FIT files, cue_sheet.html,
plan.json and transfer instructions. Validation errors return HTTP 422; oversized uploads return 413.</p>
<p><a href="/openapi.json">OpenAPI schema</a> · <a href="/">Planner</a></p></html>"""


def make_bundle(data: bytes, filename: str, rider: Rider, spec: WorkoutSpec) -> tuple[bytes, str]:
    points = parse_route(data, filename)
    plan = plan_workout(points, rider, spec)
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("terrain_course.fit", course_fit(plan))
        archive.writestr("terrain_workout.fit", workout_fit(plan))
        archive.writestr("cue_sheet.html", cue_sheet(plan, rider, spec))
        archive.writestr("plan.json", json.dumps(plan_summary(plan, rider, spec), indent=2))
        archive.writestr("EDGE_TRANSFER.txt", TRANSFER_INSTRUCTIONS)
    return output.getvalue(), clock(plan.duration)


@app.post("/plan")
async def generate(request: Request):
    origin = request.headers.get("origin")
    if origin and urlsplit(origin).netloc != request.headers.get("host"):
        raise HTTPException(403, "Only same-origin local requests are allowed.")
    async with request.form(max_files=1, max_fields=2, max_part_size=64 * 1024) as form:
        route = form.get("route")
        if not isinstance(route, UploadFile):
            raise HTTPException(422, "The route file is required.")
        data = await route.read(MAX_UPLOAD_BYTES + 1)
        if len(data) > MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Route exceeds the 10 MiB limit.")
        try:
            rider_json, spec_json = form.get("rider", "{}"), form.get("spec", "{}")
            if not isinstance(rider_json, str) or not isinstance(spec_json, str):
                raise ValueError("rider and spec must be JSON text.")
            rider = Rider.model_validate_json(rider_json)
            spec = WorkoutSpec.model_validate_json(spec_json)
            bundle, duration = await run_in_threadpool(make_bundle, data, route.filename or "", rider, spec)
        except (ValueError, ValidationError) as exc:
            raise HTTPException(422, str(exc)) from exc
    return Response(bundle, media_type="application/zip", headers={
        "Content-Disposition": 'attachment; filename="terrain_coach.zip"',
        "X-Terrain-Duration": duration,
        "Cache-Control": "no-store",
        "X-Content-Type-Options": "nosniff",
    })
