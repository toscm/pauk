"""The local session host (docs/tutor.md 7): FastAPI routes over one
Session. Bound to 127.0.0.1 by the launcher; every route needs the
key of its role (learner: `X-Pauk-Key` header or `?k=`, needed for
EventSource; teacher and observer: `Authorization: Bearer <key>`).
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path
from typing import Callable, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from pauk.client import ApiError
from pauk.tutor import protocol as p
from pauk.tutor.session import LEARNER, OBSERVER, TEACHER, Session, SessionError

STATIC = Path(__file__).parent / "static"


def harness_text() -> str:
    return resources.files("pauk.tutor").joinpath("harness.md").read_text(encoding="utf-8")


def create_app(session: Session, base_url: str = "", restart_agent: Optional[Callable[[], None]] = None) -> FastAPI:
    app = FastAPI(title="pauk tutor", docs_url=None, redoc_url=None, openapi_url=f"/s/{session.sid}/openapi.json")
    prefix = f"/s/{session.sid}"

    # --- errors ----------------------------------------------------------------

    @app.exception_handler(SessionError)
    async def _session_error(request: Request, e: SessionError):
        return JSONResponse({"error": {"code": e.code, "message": str(e)}, **e.data}, status_code=e.status)

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError):
        return JSONResponse({"error": {"code": e.code, "message": str(e)}, **{k: v for k, v in e.data.items() if k != "error"}},
                            status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def _validation(request: Request, e: RequestValidationError):
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'][1:])}: {err['msg']}" for err in e.errors())
        return JSONResponse({"error": {"code": "validation", "message": problems}}, status_code=400)

    @app.exception_handler(ValidationError)
    async def _model_validation(request: Request, e: ValidationError):
        problems = "; ".join(f"{'.'.join(str(x) for x in err['loc'])}: {err['msg']}" for err in e.errors())
        return JSONResponse({"error": {"code": "validation", "message": problems}}, status_code=400)

    # --- auth --------------------------------------------------------------------

    def role(expected: str):
        def check(request: Request) -> None:
            key = request.headers.get("X-Pauk-Key") or request.query_params.get("k")
            auth = request.headers.get("Authorization", "")
            if auth.startswith("Bearer "):
                key = auth[7:]
            if key != session.keys[expected]:
                raise HTTPException(status_code=401, detail="bad key")
        return Depends(check)

    learner, teacher, observer = role(LEARNER), role(TEACHER), role(OBSERVER)

    # --- pages ---------------------------------------------------------------------

    @app.get(prefix + "/")
    def index():
        return FileResponse(STATIC / "index.html")

    if STATIC.is_dir():
        app.mount(prefix + "/static", StaticFiles(directory=STATIC), name="static")

    @app.get(prefix + "/teach", response_class=PlainTextResponse)
    def manual_teacher(key: str = Query(...)):
        """Manual mode: what to tell an agent that should take over."""
        if key != session.keys[TEACHER]:
            raise HTTPException(status_code=401, detail="bad key")
        url = f"{base_url}{prefix}?key={key}"
        return (f"# pauk tutor session {session.sid}\n\n"
                f"Run every command as `pauk teach --session '{url}' <command> ...`\n"
                f"(or export PAUK_SESSION='{base_url}{prefix}' PAUK_TEACHER_KEY='{key}').\n\n"
                + harness_text())

    # --- learner ----------------------------------------------------------------

    api = f"{prefix}/api"

    @app.get(api + "/learner/state", dependencies=[learner])
    def learner_state():
        return session.learner_state()

    @app.get(api + "/learner/events", dependencies=[learner])
    def learner_events(request: Request, after: int = 0):
        resumed = request.headers.get("last-event-id", "")
        start = max(after, int(resumed)) if resumed.isdigit() else after

        def stream():
            last = start
            yield "retry: 2000\n\n"
            while True:
                result = session.wait(LEARNER, last, 15)
                for event in result["events"]:
                    yield f"id: {event['seq']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"
                last = result["last_seq"]
                if result["ended"] and not result["events"]:
                    yield "event: ended\ndata: {}\n\n"
                    return
                if not result["events"]:
                    yield ": keepalive\n\n"
        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})

    @app.get(api + "/learner/wait", dependencies=[learner])
    def learner_wait(after: int = 0, timeout: float = Query(default=60, ge=0, le=110)):
        return session.wait(LEARNER, after, timeout)

    @app.get(api + "/learner/status", dependencies=[learner])
    def learner_status():
        return session.status()

    @app.post(api + "/learner/start", dependencies=[learner])
    def start(body: p.Start):
        return session.start(body)

    @app.post(api + "/learner/message", dependencies=[learner])
    def message(body: p.Message):
        return session.message(body)

    @app.post(api + "/learner/answer", dependencies=[learner])
    def answer(body: p.Answer):
        return session.answer(body)

    @app.post(api + "/learner/dont-know", dependencies=[learner])
    def dont_know(body: p.ExerciseRef):
        return session.dont_know(body)

    @app.post(api + "/learner/reveal", dependencies=[learner])
    def reveal(body: p.ExerciseRef):
        return session.reveal(body)

    @app.post(api + "/learner/self-grade", dependencies=[learner])
    def self_grade(body: p.SelfGrade):
        return session.self_grade(body)

    @app.post(api + "/learner/hint-request", dependencies=[learner])
    def hint_request(body: p.ExerciseRef):
        return session.hint_request(body)

    @app.post(api + "/learner/proposal", dependencies=[learner])
    def proposal(body: p.ProposalDecision):
        return session.decide_proposal(body)

    @app.post(api + "/learner/activity", dependencies=[learner])
    def learner_activity(body: p.ActivityAct):
        return session.activity_act(LEARNER, body)

    @app.post(api + "/learner/report", dependencies=[learner])
    def learner_report(body: p.LearnerReport):
        return session.learner_report(body)

    @app.post(api + "/learner/end", dependencies=[learner])
    def learner_end():
        return session.learner_end()

    @app.post(api + "/learner/restart-teacher", dependencies=[learner])
    def restart_teacher():
        if restart_agent is None:
            raise SessionError(409, "no_agent", "This session has no managed teacher agent (started with --no-agent)")
        restart_agent()
        return {"ok": True}

    @app.get(api + "/learner/subjects", dependencies=[learner])
    def subjects():
        return {"items": [{"path": d["path"], "name": d["name"]} for d in session.api.quiz_dirs()]}

    @app.get(api + "/learner/settings", dependencies=[learner])
    def get_settings():
        return session.settings

    @app.patch(api + "/learner/settings", dependencies=[learner])
    def patch_settings(changes: dict):
        return session.update_settings(changes)

    @app.get(api + "/learner/profile", dependencies=[learner])
    def learner_profile(dir: Optional[str] = None):
        dir_id = session._dir_id(dir)
        return {"summary": session._api(lambda: session.api.profile(dir_id)),
                "next": session._api(lambda: session.api.next_items(dir_id, n=10))}

    @app.get(api + "/learner/items", dependencies=[learner])
    def learner_items(dir: Optional[str] = None, q: Optional[str] = None, space: Optional[str] = None):
        dir_id = session._dir_id(dir)
        return {"items": session._api(lambda: session.api.list_items(
            dir=dir_id, recursive="1" if dir_id else None, q=q, space=space, limit=200))}

    @app.get(api + "/learner/item", dependencies=[learner])
    def learner_item(ref: str):
        return session._api(lambda: session.api.get_item(ref))

    @app.get(api + "/learner/merges", dependencies=[learner])
    def learner_merges(status: Optional[str] = "suggested"):
        return {"items": session._api(lambda: session.api.list_merges(status))}

    @app.post(api + "/learner/merges/{merge_id}/{action}", dependencies=[learner])
    def learner_decide_merge(merge_id: int, action: str):
        if action not in ("accept", "dismiss"):
            raise SessionError(400, "validation", "action is accept or dismiss")
        return session._api(lambda: session.api.decide_merge(merge_id, action))

    # --- teacher -----------------------------------------------------------------

    @app.post(api + "/teacher/attach", dependencies=[teacher])
    def attach(body: p.Attach):
        return session.attach(body)

    @app.get(api + "/teacher/instructions", dependencies=[teacher], response_class=PlainTextResponse)
    def instructions():
        session.audit("instructions")
        return harness_text()

    @app.get(api + "/teacher/schemas", dependencies=[teacher])
    def schemas():
        return p.schemas()

    @app.get(api + "/teacher/state", dependencies=[teacher])
    def teacher_state():
        return session.teacher_state()

    @app.get(api + "/teacher/wait", dependencies=[teacher])
    def teacher_wait(after: int = 0, timeout: float = Query(default=90, ge=0, le=110)):
        return session.wait(TEACHER, after, timeout)

    @app.get(api + "/teacher/profile", dependencies=[teacher])
    def teacher_profile(dir: Optional[str] = None):
        return session.profile(dir)

    @app.get(api + "/teacher/next", dependencies=[teacher])
    def teacher_next(dir: Optional[str] = None, n: int = Query(default=10, ge=1, le=50)):
        return session.next(dir, n)

    @app.get(api + "/teacher/items", dependencies=[teacher])
    def teacher_items(q: Optional[str] = None, dir: Optional[str] = None, space: Optional[str] = None, kind: Optional[str] = None):
        return session.items(q, dir, space, kind)

    @app.get(api + "/teacher/activity", dependencies=[teacher])
    def teacher_activity(aid: str):
        return session.activity_observe(aid)

    @app.get(api + "/teacher/item", dependencies=[teacher])
    def teacher_item(ref: str):
        return session.item(ref)

    actions = {
        "say": (p.Say, session.say), "introduce": (p.Introduce, session.introduce), "ask": (p.Ask, session.ask),
        "drill": (p.Drill, session.drill), "grade": (p.Grade, session.grade), "override": (p.Override, session.override),
        "hint": (p.Hint, session.hint), "note": (p.Note, session.note),
        "focus": (p.Flag, lambda b: session.flag("focus", b)), "suspend": (p.Flag, lambda b: session.flag("suspended", b)),
        "link": (p.Link, session.link), "merge": (p.Merge, session.merge), "add-item": (p.AddItem, session.add_item),
        "report": (p.Report, session.teacher_report), "end": (p.End, session.end),
        "activity-start": (p.ActivityStart, session.activity_start),
        "activity-act": (p.ActivityAct, lambda b: session.activity_act(TEACHER, b)),
        "activity-end": (p.ActivityRef, session.activity_end),
    }
    for name, (model, handler) in actions.items():
        def make(model=model, handler=handler):
            def route(body: dict):
                return handler(model.model_validate(body))
            return route
        app.post(f"{api}/teacher/{name}", dependencies=[teacher])(make())

    # --- observer ---------------------------------------------------------------

    @app.get(api + "/observer/state", dependencies=[observer])
    def observer_state():
        return {**session.status(), "events": session.events_for(OBSERVER), "last_seq": len(session.events),
                "harness": harness_text()}

    @app.get(api + "/observer/wait", dependencies=[observer])
    def observer_wait(after: int = 0, timeout: float = Query(default=60, ge=0, le=110)):
        return session.wait(OBSERVER, after, timeout)

    @app.post(api + "/observer/annotate", dependencies=[observer])
    def annotate(body: p.Annotate):
        return session.annotate(body)

    @app.post(api + "/observer/report", dependencies=[observer])
    def observer_report(body: p.Report):
        return session.observer_report(body)

    return app
