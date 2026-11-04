"""Loopback-only HTTP adapter; operational traffic always uses shared TCP clients."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
import json
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.exceptions import HTTPException

from simquaro.checks import run_checks
from simquaro.configuration import (ConfigurationError, ConfigurationService, configuration_io,
                                    entry_from_record, entry_record)
from simquaro.control import control_request
from simquaro.registry import get_model
from simquaro.runtime import Runtime
from simquaro.web import ServiceError
from simquaro.web.jobs import JobManager
from simquaro.web.sessions import SessionManager
from synqaro_protocol.client import LocalFailure


def success(result, status=200):
    return JSONResponse({"version": 1, "ok": True, "result": result}, status_code=status)


def failure(code, message, status=400, *, uncertain=False):
    return JSONResponse({"version": 1, "ok": False, "error": {
        "code": code, "message": str(message)[:1024], "uncertain": uncertain,
        "actions": ["Inspect current state before retrying a modification.",
                    "Reload saved configuration or reconnect explicitly if needed."]}}, status_code=status)


class LocalBoundary:
    """Reject browser cross-origin requests and bound bodies before routing."""
    def __init__(self, app, *, origin):
        self.app, self.origin, self.host = app, origin, urlsplit(origin).netloc

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http": return await self.app(scope, receive, send)
        pairs = scope["headers"]
        headers = dict(pairs)
        async def secure_send(message):
            if message["type"] == "http.response.start":
                message["headers"] = list(message.get("headers", [])) + [
                    (b"content-security-policy", b"default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"),
                    (b"x-content-type-options", b"nosniff"), (b"referrer-policy", b"no-referrer"),
                    (b"cache-control", b"no-store")]
            await send(message)
        async def reject(code, message, status):
            await failure(code, message, status)(scope, receive, secure_send)
        for key in (b"host", b"origin", b"x-simquaro-client", b"content-type", b"content-length"):
            if sum(k == key for k, _ in pairs) > 1:
                return await reject("FORBIDDEN_ORIGIN", "Duplicate security headers are not supported", 403)
        if (headers.get(b"host", b"").decode("latin1") != self.host
                or headers.get(b"origin", self.origin.encode()).decode("latin1") != self.origin
                or headers.get(b"sec-fetch-site") == b"cross-site"):
            return await reject("FORBIDDEN_ORIGIN", "Use the printed local GUI URL, not a foreign origin or proxy", 403)
        mutation = scope["method"] not in ("GET", "HEAD")
        if mutation and (headers.get(b"x-simquaro-client") != b"1" or
                         headers.get(b"content-type", b"").split(b";", 1)[0].strip().lower() != b"application/json"):
            return await reject("FORBIDDEN_ACTION", "Use application/json and X-Simquaro-Client: 1", 403)
        try:
            length = int(headers.get(b"content-length", b"0"))
            if length < 0: raise ValueError
        except ValueError:
            return await reject("INVALID_ARGUMENTS", "Invalid Content-Length", 400)
        if length > 1048576:
            return await reject("BODY_LIMIT", "Reduce the request body to at most 1 MiB", 413)
        body = bytearray()
        try:
            async with asyncio.timeout(10):
                while True:
                    message = await receive()
                    if message["type"] == "http.disconnect": return
                    body.extend(message.get("body", b""))
                    if len(body) > 1048576:
                        return await reject("BODY_LIMIT", "Reduce the request body to at most 1 MiB", 413)
                    if not message.get("more_body", False): break
        except TimeoutError:
            return await reject("BODY_TIMEOUT", "Complete the local HTTP body within 10 seconds", 400)
        delivered = False
        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {"type": "http.request", "body": bytes(body), "more_body": False}
            return await receive()
        await self.app(scope, replay, secure_send)


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result: raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _nonfinite(value):
    raise ValueError("JSON numbers must be finite")


async def payload(request, required=(), optional=()):
    try:
        raw = await request.body()
        result = json.loads(raw or b"{}", object_pairs_hook=_pairs, parse_constant=_nonfinite)
    except (UnicodeError, ValueError, RecursionError):
        raise ValueError("Expected strict UTF-8 JSON without duplicate keys or nonfinite values") from None
    if type(result) is not dict or not set(required) <= set(result) or set(result) - set(required) - set(optional):
        raise ValueError("Missing or unknown fields")
    return result


def create_app(store, *, runtime_root=None, origin="http://127.0.0.1:8765"):
    parsed = urlsplit(origin)
    if (parsed.scheme != "http" or parsed.hostname != "127.0.0.1" or parsed.port is None
            or parsed.path or parsed.query or parsed.fragment or parsed.username or parsed.password):
        raise ValueError("Use an exact http://127.0.0.1:PORT origin")

    @asynccontextmanager
    async def lifespan(app):
        app.state.runtime = Runtime(runtime_root)
        app.state.configuration = ConfigurationService(store, app.state.runtime)
        app.state.jobs = JobManager()
        app.state.sessions = SessionManager(store, busy=app.state.jobs.busy)
        try: yield
        finally:
            await app.state.sessions.close()
            await app.state.jobs.close()

    app = FastAPI(lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(LocalBoundary, origin=origin)

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        code = getattr(exc, "code", "INVALID_ARGUMENTS")
        status = (404 if code.startswith("UNKNOWN_") else 403 if code.startswith("FORBIDDEN_") else
                  409 if code in ("CONFIG_CONFLICT", "CONFIG_BUSY", "TARGET_BUSY") else
                  429 if code in ("SESSION_LIMIT", "JOB_LIMIT") else
                  503 if isinstance(exc, ConfigurationError) and code != "INVALID_ARGUMENTS" else 400)
        return failure(code, exc, status)

    @app.exception_handler(LocalFailure)
    async def communication(request, exc):
        return failure(exc.code, str(exc), 503, uncertain=exc.uncertain)

    @app.exception_handler(OSError)
    async def unavailable(request, exc):
        return failure("CONNECTION_FAILED", "Cannot reach the saved endpoint; start the simulator or check host/port", 503)

    @app.exception_handler(RequestValidationError)
    async def validation(request, exc): return failure("INVALID_ARGUMENTS", "Invalid path, cursor or arguments", 400)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc): return failure("UNKNOWN_ROUTE", "Unknown local API route or method", exc.status_code)

    async def target(name, *, simulator=False):
        snapshot = await configuration_io(store.load)
        entry = ConfigurationService.target(snapshot, name)
        if simulator and entry.kind != "simulator":
            raise ServiceError("FORBIDDEN_TARGET_KIND", "Physical hardware has no simulator administration interface")
        return snapshot, entry

    def saved(snapshot):
        return {"path": str(snapshot.path), "source": snapshot.source, "revision": snapshot.revision,
                "instances": [entry_record(entry) for entry in snapshot.entries.values()]}

    @app.get("/api/targets")
    async def targets():
        snapshot = await configuration_io(store.load)
        return success({"targets": [{**entry_record(entry),
            "editable_settings": list(get_model(entry.config.model).editable_settings) if entry.kind == "simulator" else ["hardware_id"]}
            for entry in snapshot.entries.values()], "revision": snapshot.revision, "source": snapshot.source})

    @app.get("/api/config")
    async def configuration(): return success(saved(await configuration_io(store.load)))

    @app.put("/api/config/{name}")
    async def save_configuration(name: str, request: Request):
        data = await payload(request, ("revision", "record"))
        snapshot, previous = await target(name)
        if type(data["revision"]) is not str: raise ValueError("Supply the revision shown in the editor")
        entry = entry_from_record(data["record"], tagged=True)
        if (entry.config.name, entry.config.model, entry.kind) != (previous.config.name, previous.config.model, previous.kind):
            raise ServiceError("FORBIDDEN_EDIT", "GUI cannot rename targets or change their model/kind; edit the file with affected simulators stopped")
        definition = get_model(entry.config.model)
        allowed = set(definition.editable_settings) if entry.kind == "simulator" else {"hardware_id"}
        for key, value in asdict(entry.config.settings).items():
            if key not in allowed and value != getattr(previous.config.settings, key):
                raise ServiceError("FORBIDDEN_EDIT", "This setting is read-only in the GUI: " + key)
        entries = dict(snapshot.entries)
        entries[name] = entry
        updated = await configuration_io(store.save, entries, expected_revision=data["revision"])
        return success(saved(updated))

    @app.get("/api/targets/{name}/admin")
    async def admin(name: str):
        await target(name, simulator=True)
        return success(await app.state.configuration.inspect(name))

    @app.post("/api/targets/{name}/lifecycle")
    async def lifecycle(name: str, request: Request):
        data = await payload(request, ("action",), ("revision",))
        snapshot, entry = await target(name, simulator=True)
        action = data["action"]
        if action not in ("start", "stop", "restart", "apply"): raise ValueError("Choose start, stop, restart, or apply")
        if action == "apply" and data.get("revision") != snapshot.revision:
            raise ConfigurationError("CONFIG_CONFLICT", "Reload before applying saved settings")
        async def operate():
            await app.state.sessions.disconnect_target(name)
            runtime = app.state.runtime
            if action == "stop": return await runtime.stop(name)
            # Snapshot pinned before job registration; no reread may retarget this job.
            started = await (runtime.start(entry.config) if action == "start" else runtime.restart(entry.config))
            app.state.jobs.own(runtime, started)
            return {**started.outcome, "requested_revision": snapshot.revision}
        jid = app.state.jobs.start(action, name, operate())
        return success({"id": jid, "revision": snapshot.revision}, 202)

    async def fault_state(name):
        snapshot, entry = await target(name, simulator=True)
        state = await app.state.runtime.inspect(entry.config)
        if not state["ok"]: raise ServiceError("CONTROL_UNAVAILABLE", "Inspect simulator administration and restart if needed")
        return entry, state

    @app.get("/api/targets/{name}/faults")
    async def faults(name: str):
        entry, state = await fault_state(name)
        return success({"catalog": get_model(entry.config.model).fault_factory().catalog(),
                        "state": state.get("status", {}).get("faults"), "runtime": state["outcome"]})

    @app.post("/api/targets/{name}/faults")
    async def fault(name: str, request: Request):
        data = await payload(request, ("action", "arguments"))
        entry, state = await fault_state(name)
        if app.state.jobs.busy(name): raise ServiceError("TARGET_BUSY", "Wait for the current target job")
        if state["outcome"] != "running": raise ServiceError("CONTROL_UNAVAILABLE", "Start this simulator before changing faults")
        if data["action"] not in ("activate", "clear", "schedule", "cancel") or type(data["arguments"]) is not dict:
            raise ValueError("Use activate, clear, schedule or cancel with its documented arguments")
        response = await control_request(app.state.runtime.root / (name + ".sock"), "fault." + data["action"], data["arguments"])
        if not response["ok"]: return failure(response["error"]["code"], response["error"]["message"], 400)
        return success(response["result"])

    @app.post("/api/sessions")
    async def connect(request: Request):
        data = await payload(request, ("target", "mode"))
        if type(data["target"]) is not str or type(data["mode"]) is not str: raise ValueError("Target/mode must be strings")
        return success(await app.state.sessions.connect(data["target"], data["mode"]))

    @app.post("/api/sessions/{sid}/requests")
    async def submit(sid: str, request: Request):
        data = await payload(request, (), ("verb", "fields", "text"))
        return success(await app.state.sessions.submit(sid, data))

    @app.get("/api/sessions/{sid}/events")
    async def events(sid: str, after: int = 0): return success(app.state.sessions.events(sid, after))

    @app.post("/api/sessions/{sid}/heartbeat")
    async def heartbeat(sid: str, request: Request):
        await payload(request)
        return success(app.state.sessions.heartbeat(sid))

    @app.delete("/api/sessions/{sid}")
    async def disconnect(sid: str, request: Request):
        await payload(request)
        return success(await app.state.sessions.disconnect(sid))

    @app.post("/api/targets/{name}/tests")
    async def tests(name: str, request: Request):
        data = await payload(request, ("allow_changes",))
        if type(data["allow_changes"]) is not bool: raise ValueError("allow_changes must be a boolean for this run")
        snapshot, entry = await target(name)
        if app.state.sessions.has_target(name): raise ServiceError("TARGET_BUSY", "Disconnect all GUI sessions for this target before running checks")
        definition = get_model(entry.config.model)
        if definition.client_factory is None or not definition.checks: raise ValueError("No checks registered for this model")
        async def operate():
            client = definition.client_factory(entry.config.host, entry.config.port, entry.config.settings,
                                               read_only=not data["allow_changes"])
            report = await run_checks(client, definition.checks, allow_changes=data["allow_changes"],
                emit=lambda event: app.state.jobs.progress(jid, asdict(event)))
            return {**report.as_dict(), "revision": snapshot.revision, "read_only": not data["allow_changes"]}
        jid = app.state.jobs.start("tests", name, operate())
        return success({"id": jid, "revision": snapshot.revision}, 202)

    @app.get("/api/jobs/{jid}")
    async def job(jid: str): return success(app.state.jobs.get(jid))

    @app.get("/api/targets/{name}/jobs")
    async def jobs(name: str):
        await target(name)
        return success({"jobs": app.state.jobs.list(name)})

    static = Path(__file__).parent / "static"
    if static.is_dir(): app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/")
    async def index():
        if not (static / "index.html").is_file(): return failure("UI_NOT_INSTALLED", "Browser assets not installed yet", 503)
        return FileResponse(static / "index.html")

    return app
