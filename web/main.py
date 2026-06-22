"""Lightweight FastAPI server that exposes agent graph data to the frontend.

Runs on port 8001 alongside the ADK backend (port 8000).

Endpoints
---------
GET /api/agent-graph/{session_id}
    Returns the JSON graph file for the session, or an empty graph if not found.
GET /api/workspace/files?path=<path>
    Serves any file from the workspace root (absolute or relative path).
    Returns 403 if the path escapes the workspace root.
GET /api/sessions/{session_id}/files
    Lists all files under the session's working directory.

The vite dev server proxies /api/* here and /run_sse + /apps/* to the ADK server.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import signal
import socket
import sqlite3
import subprocess
import sys
import threading
from pathlib import Path
from typing import List

import yaml

from dotenv import dotenv_values
from dotenv import set_key as dotenv_set_key
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
# Allow importing from agents/ and src/ when running as script
ROOT = Path(__file__).parent.parent
_WEB_DIR = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(_WEB_DIR) not in sys.path:
    sys.path.insert(0, str(_WEB_DIR))

import users_db  # noqa: E402

from agents.MatCreator.workspace import get_session_workdir, get_workspace_root, workspace_skills_dir  # noqa: E402
from agents.MatCreator.agents.cancellation import (  # noqa: E402
    request_cancellation,
    is_cancellation_requested,
    get_cancellation_reason,
    clear_cancellation,
    request_step_cancellation,
)
from agents.MatCreator.agents.graph_logger import AgentGraphLogger  # noqa: E402
from agents.MatCreator.skill import ALL_SKILLS, PLANNING_SKILL_NAMES, refresh_skills, get_default_skill_names  # noqa: E402
from agents.MatCreator.config import load_config, save_config, get_disabled_skills  # noqa: E402
from agents.MatCreator.constants import GRAPH_AGENT_MODEL  # noqa: E402
from agents.MatCreator.knowledge.query import _get_kg  # noqa: E402
from agents.MatCreator.knowledge.review import run_review_pipeline  # noqa: E402

app = FastAPI(title="MatCreator Graph API", version="1.0.0")
APP_NAME = "MatCreator"
SESSION_DB_PATH = ROOT / "agents" / "MatCreator" / ".adk" / "session.db"
DEFAULT_ADMIN_USERS = {"admin"}

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

ENV_PATH = ROOT / "agents" / "MatCreator" / ".env"
_SENSITIVE_FIELDS = frozenset({"LLM_API_KEY", "BOHRIUM_PASSWORD"})
_ENV_FIELDS = [
    "LLM_MODEL", "LLM_API_KEY", "LLM_BASE_URL", "EMBEDDING_MODEL",
    "BOHRIUM_EMAIL", "BOHRIUM_PASSWORD", "BOHRIUM_PROJECT_ID",
    "BOHRIUM_VASP_IMAGE", "BOHRIUM_VASP_MACHINE",
    "BOHRIUM_DEEPMD_IMAGE", "BOHRIUM_DEEPMD_MACHINE", "DEEPMD_MODEL_PATH",
]

_adk_process: subprocess.Popen | None = None
_knowledge_review_lock = threading.Lock()
_knowledge_review_task: asyncio.Task | None = None
_knowledge_review_state = {
    "status": "idle",
    "trigger_session_id": None,
    "progress": {"completed": 0, "total": 0, "percent": 0},
    "results": [],
    "errors": [],
    "summary": "",
}


def _is_port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _kill_port(port: int) -> None:
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True, text=True, timeout=5,
        )
        for pid_str in result.stdout.strip().splitlines():
            try:
                os.kill(int(pid_str.strip()), signal.SIGTERM)
            except (ProcessLookupError, ValueError):
                pass
    except Exception:
        pass


def _admin_users() -> set[str]:
    raw_value = os.environ.get("MATCREATOR_ADMIN_USERS")
    if raw_value is None:
        return DEFAULT_ADMIN_USERS.copy()

    return {
        item.strip()
        for item in raw_value.split(",")
        if item.strip()
    }


def _is_admin(user_id: str) -> bool:
    admin_names = _admin_users()
    if user_id in admin_names:
        return True  # legacy path: user_id is a display name (pre-UUID)
    user = users_db.get_by_id(user_id)
    return user is not None and user["display_name"] in admin_names


def _session_row_to_summary(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "appName": row["app_name"],
        "userId": row["user_id"],
        "createTime": row["create_time"],
        "lastUpdateTime": row["update_time"],
    }


def _query_session_summaries(user_id: str | None = None) -> list[dict]:
    if not SESSION_DB_PATH.exists():
        return []

    where_clause = "WHERE app_name = ?"
    params: tuple[str, ...] = (APP_NAME,)
    if user_id is not None:
        where_clause += " AND user_id = ?"
        params = (APP_NAME, user_id)

    try:
        with sqlite3.connect(SESSION_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"""
                SELECT app_name, user_id, id, create_time, update_time
                FROM sessions
                {where_clause}
                ORDER BY update_time DESC
                """,
                params,
            ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read sessions: {exc}")

    return [_session_row_to_summary(row) for row in rows]


def _load_json_field(raw_value: str | None, fallback):
    if not raw_value:
        return fallback
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError:
        return fallback


def _load_agent_graph_data(session_id: str) -> dict:
    graph_path = get_workspace_root() / "agent_graphs" / f"{session_id}.json"
    if not graph_path.exists():
        return {}
    try:
        return json.loads(graph_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _safe_upload_filename(filename: str) -> str:
    cleaned = Path(filename or "upload").name.strip()
    if not cleaned or cleaned in {".", ".."}:
        cleaned = "upload"
    return "".join(ch if ch.isalnum() or ch in "._- " else "_" for ch in cleaned)


def _available_upload_path(upload_dir: Path, filename: str) -> Path:
    candidate = upload_dir / filename
    if not candidate.exists():
        return candidate

    stem = candidate.stem or "upload"
    suffix = candidate.suffix
    for i in range(1, 10000):
        next_candidate = upload_dir / f"{stem}-{i}{suffix}"
        if not next_candidate.exists():
            return next_candidate

    raise HTTPException(status_code=409, detail="Too many files with the same name")


@app.get("/api/health")
async def health_check():
    return {"status": "ok"}
@app.on_event("startup")
async def _on_startup() -> None:
    users_db.init_db()
    users_db.migrate_legacy_adk_sessions(SESSION_DB_PATH, APP_NAME)


class LoginBody(BaseModel):
    display_name: str
    password: str | None = None


class RegisterBody(BaseModel):
    display_name: str
    password: str


class SetPasswordBody(BaseModel):
    user_id: str
    old_password: str | None = None
    new_password: str


class KnowledgeReviewBody(BaseModel):
    session_id: str


def _knowledge_review_snapshot() -> dict:
    with _knowledge_review_lock:
        return dict(_knowledge_review_state)


def _set_knowledge_review_state(**changes) -> None:
    with _knowledge_review_lock:
        _knowledge_review_state.update(changes)


def _review_model_config() -> tuple[str, str, str | None]:
    model = os.environ.get("REVIEW_AGENT_MODEL") or os.environ.get(
        "GRAPH_AGENT_MODEL",
        GRAPH_AGENT_MODEL,
    )
    api_key = os.environ.get("LLM_API_KEY") or os.environ.get("MINIMAX_API_KEY", "")
    base_url = os.environ.get("LLM_BASE_URL") or os.environ.get("MINIMAX_API_BASE") or None
    if "/" in model:
        model = model.split("/", 1)[1]
    return model, api_key, base_url


async def _run_knowledge_review(session_id: str) -> None:
    try:
        model, api_key, base_url = _review_model_config()
        if not api_key:
            raise RuntimeError(
                "No review API key configured. Set LLM_API_KEY in Settings or "
                "MINIMAX_API_KEY in agents/MatCreator/.env."
            )
        if not model:
            raise RuntimeError("No REVIEW_AGENT_MODEL or GRAPH_AGENT_MODEL configured.")

        def run_review() -> dict:
            graph = _get_kg()
            result = run_review_pipeline(
                graph,
                model=model,
                api_key=api_key,
                base_url=base_url,
                batch_size=20,
                strategy=os.environ.get("MATCREATOR_REVIEW_STRATEGY", "auto"),
                on_status=lambda phase, status: _set_knowledge_review_state(
                    **status,
                    phase=phase,
                    trigger_session_id=session_id,
                ),
            )
            return result

        result = await asyncio.to_thread(run_review)
        _set_knowledge_review_state(**result, trigger_session_id=session_id)
    except Exception as exc:
        _set_knowledge_review_state(
            status="failed",
            trigger_session_id=session_id,
            progress={"completed": 0, "total": 0, "percent": 0},
            results=[],
            errors=[str(exc)],
            summary="",
        )
    finally:
        global _knowledge_review_task
        _knowledge_review_task = None


@app.post("/api/knowledge-review/start")
async def start_knowledge_review(body: KnowledgeReviewBody) -> JSONResponse:
    global _knowledge_review_task
    if _knowledge_review_task is not None and not _knowledge_review_task.done():
        return JSONResponse(_knowledge_review_snapshot(), status_code=202)

    _set_knowledge_review_state(
        status="running",
        trigger_session_id=body.session_id,
        progress={"completed": 0, "total": 0, "percent": 0},
        results=[],
        errors=[],
        summary="",
    )
    _knowledge_review_task = asyncio.create_task(_run_knowledge_review(body.session_id))
    return JSONResponse(_knowledge_review_snapshot(), status_code=202)


@app.get("/api/knowledge-review/status")
async def get_knowledge_review_status() -> JSONResponse:
    return JSONResponse(_knowledge_review_snapshot())


@app.post("/api/auth/login")
async def auth_login(body: LoginBody) -> JSONResponse:
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name cannot be empty")

    # Special identity: "user" always allowed, no password required.
    if name == users_db.LEGACY_USER:
        return JSONResponse({
            "user_id": users_db.LEGACY_USER,
            "display_name": users_db.LEGACY_USER,
            "is_admin": _is_admin(users_db.LEGACY_USER),
        })

    user = users_db.get_by_display_name(name)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found. Please register first.")
    if user["password_hash"] is not None and not users_db.verify_password(user["password_hash"], body.password):
        raise HTTPException(status_code=401, detail="Invalid password.")

    return JSONResponse({
        "user_id": user["id"],
        "display_name": user["display_name"],
        "is_admin": _is_admin(user["id"]),
    })


@app.post("/api/auth/register")
async def auth_register(body: RegisterBody) -> JSONResponse:
    name = body.display_name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="display_name cannot be empty")
    if name == users_db.LEGACY_USER:
        raise HTTPException(status_code=400, detail="'user' is a reserved username.")
    if not body.password:
        raise HTTPException(status_code=422, detail="Password is required for registration.")

    existing = users_db.get_by_display_name(name)
    if existing is not None:
        raise HTTPException(status_code=409, detail="Username already taken.")

    user = users_db.create_user(name, body.password)
    return JSONResponse({
        "user_id": user["id"],
        "display_name": user["display_name"],
        "is_admin": _is_admin(user["id"]),
    }, status_code=201)


@app.post("/api/auth/set-password")
async def auth_set_password(body: SetPasswordBody) -> JSONResponse:
    if body.user_id == users_db.LEGACY_USER:
        raise HTTPException(status_code=400, detail="Cannot set password for the 'user' account")
    user = users_db.get_by_id(body.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if not users_db.verify_password(user["password_hash"], body.old_password):
        raise HTTPException(status_code=401, detail="Current password is incorrect")
    users_db.set_password(body.user_id, body.new_password)
    return JSONResponse({"status": "ok"})


@app.get("/api/session-access/{user_id}")
async def get_session_access(user_id: str) -> JSONResponse:
    return JSONResponse({"user_id": user_id, "is_admin": _is_admin(user_id)})


@app.get("/api/users/{user_id}/sessions")
async def list_user_sessions(user_id: str) -> JSONResponse:
    return JSONResponse(_query_session_summaries(user_id))


@app.get("/api/users/{user_id}/sessions/{session_id}")
async def get_user_session(user_id: str, session_id: str) -> JSONResponse:
    if not SESSION_DB_PATH.exists():
        raise HTTPException(status_code=404, detail="Session not found")

    try:
        with sqlite3.connect(SESSION_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            session = conn.execute(
                """
                SELECT app_name, user_id, id, state, create_time, update_time
                FROM sessions
                WHERE app_name = ? AND user_id = ? AND id = ?
                """,
                (APP_NAME, user_id, session_id),
            ).fetchone()
            if session is None:
                raise HTTPException(status_code=404, detail="Session not found")

            event_rows = conn.execute(
                """
                SELECT event_data
                FROM events
                WHERE app_name = ? AND user_id = ? AND session_id = ?
                ORDER BY timestamp ASC
                """,
                (APP_NAME, user_id, session_id),
            ).fetchall()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=500, detail=f"Failed to read session: {exc}")

    summary = _session_row_to_summary(session)
    summary["state"] = _load_json_field(session["state"], {})
    events = [
        _load_json_field(row["event_data"], {})
        for row in event_rows
    ]
    # Return the canonical session history as-is so the frontend reflects only
    # what was actually persisted in the session DB.
    summary["events"] = events
    return JSONResponse(summary)


@app.get("/api/admin/sessions")
async def list_all_sessions(user_id: str = Query(..., description="Current signed-in user")) -> JSONResponse:
    if not _is_admin(user_id):
        raise HTTPException(status_code=403, detail="Admin access required")
    return JSONResponse(_query_session_summaries())


@app.delete("/api/sessions/{session_id}")
async def delete_session(session_id: str) -> JSONResponse:
    """Delete a session and all associated data."""
    # 1. Delete from session DB (events cascade-deleted via FK)
    if SESSION_DB_PATH.exists():
        try:
            with sqlite3.connect(SESSION_DB_PATH) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                conn.execute(
                    "DELETE FROM sessions WHERE app_name = ? AND id = ?",
                    (APP_NAME, session_id),
                )
        except sqlite3.Error as exc:
            raise HTTPException(status_code=500, detail=f"Failed to delete session from DB: {exc}")

    # 2. Remove summary entry
    summaries = _load_summaries()
    if session_id in summaries:
        del summaries[session_id]
        _save_summaries(summaries)

    # 3. Delete associated files/directories
    workspace = get_workspace_root()
    targets = [
        workspace / "agent_graphs" / f"{session_id}.json",
        workspace / "sessions" / session_id,           # recursive dir
        workspace / "trajectories" / f"{session_id}.jsonl",
        workspace / "trajectories" / f"{session_id}_summary.json",
        workspace / "cancellation" / f"{session_id}.flag",
    ]
    for target in targets:
        try:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.is_file():
                target.unlink()
        except OSError:
            pass  # best-effort cleanup

    return JSONResponse({"status": "ok", "deleted": session_id})


def _load_execution_graph(session_id: str) -> dict:
    """Read execution_graph from the SQLite session state."""
    if not SESSION_DB_PATH.exists():
        return {"nodes": {}, "edges": []}
    try:
        with sqlite3.connect(SESSION_DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT state FROM sessions WHERE app_name = ? AND id = ?",
                (APP_NAME, session_id),
            ).fetchone()
            if row is None:
                return {"nodes": {}, "edges": []}
            state = _load_json_field(row["state"], {})
            raw = state.get("execution_graph")
            if isinstance(raw, str):
                raw = _load_json_field(raw, None)
            if not isinstance(raw, dict):
                return {"nodes": {}, "edges": []}
            return raw
    except sqlite3.Error:
        return {"nodes": {}, "edges": []}


@app.get("/api/execution-graph/{session_id}")
async def get_execution_graph(session_id: str) -> JSONResponse:
    """Return the execution graph (plan DAG) from session state for frontend visualization."""
    data = _load_execution_graph(session_id)
    return JSONResponse(data)



@app.get("/api/agent-graph/{session_id}")
async def get_agent_graph(session_id: str) -> JSONResponse:
    data = _load_agent_graph_data(session_id)
    if not data:
        return JSONResponse({"session_id": session_id, "nodes": {}, "edges": [], "updated_at": None})
    return JSONResponse(data)


@app.get("/api/workspace/files")
async def serve_workspace_file(path: str = Query(..., description="Absolute or workspace-relative file path")) -> FileResponse:
    ws_root = get_workspace_root().resolve()
    p = Path(path)
    resolved = p.resolve() if p.is_absolute() else (ws_root / p).resolve()
    if not resolved.is_relative_to(ws_root):
        raise HTTPException(status_code=403, detail="Access denied: path is outside workspace")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(resolved)


@app.get("/api/structure/view")
async def view_structure(path: str = Query(..., description="Absolute or workspace-relative structure file path")) -> JSONResponse:
    from io import StringIO

    try:
        from ase.io import read as ase_read
        from ase.io import write as ase_write
    except ImportError:
        raise HTTPException(status_code=500, detail="ASE is not installed")

    ws_root = get_workspace_root().resolve()
    p = Path(path)
    resolved = p.resolve() if p.is_absolute() else (ws_root / p).resolve()
    if not resolved.is_relative_to(ws_root):
        raise HTTPException(status_code=403, detail="Access denied: path is outside workspace")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        atoms = ase_read(str(resolved))
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Cannot parse structure: {exc}")

    buf = StringIO()
    ase_write(buf, atoms, format="xyz")
    xyz_data = buf.getvalue()

    return JSONResponse({
        "xyz": xyz_data,
        "formula": atoms.get_chemical_formula(),
        "n_atoms": len(atoms),
        "periodic": bool(atoms.pbc.any()),
        "cell": atoms.cell.tolist() if atoms.pbc.any() else None,
    })


@app.get("/api/sessions/{session_id}/files")
async def list_session_files(session_id: str) -> JSONResponse:
    session_dir = get_session_workdir(session_id)
    if not session_dir.exists():
        return JSONResponse({"files": []})
    files = [
        {"name": f.name, "path": str(f), "size": f.stat().st_size}
        for f in sorted(session_dir.rglob("*"))
        if f.is_file()
    ]
    return JSONResponse({"files": files})


@app.post("/api/sessions/{session_id}/files")
async def upload_session_file(session_id: str, file: UploadFile = File(...)) -> JSONResponse:
    session_dir = get_session_workdir(session_id)
    upload_dir = session_dir / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)

    filename = _safe_upload_filename(file.filename or "")
    target = _available_upload_path(upload_dir, filename)

    size = 0
    try:
        with target.open("wb") as fh:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                fh.write(chunk)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}")
    finally:
        await file.close()

    return JSONResponse({
        "name": target.name,
        "path": str(target),
        "size": size,
    })


@app.delete("/api/sessions/{session_id}/files")
async def delete_session_file(
    session_id: str,
    path: str = Query(..., description="Absolute or session-relative file path"),
) -> JSONResponse:
    session_dir = get_session_workdir(session_id).resolve()
    p = Path(path)
    resolved = p.resolve() if p.is_absolute() else (session_dir / p).resolve()

    if not resolved.is_relative_to(session_dir):
        raise HTTPException(status_code=403, detail="Access denied: path is outside session")
    if not resolved.is_file():
        raise HTTPException(status_code=404, detail="File not found")

    try:
        resolved.unlink()
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete file: {exc}")

    return JSONResponse({"deleted": True, "path": str(resolved)})


@app.post("/api/sessions/{session_id}/cancel")
async def cancel_session_execution(
    session_id: str,
    reason: str = Query(default="user_requested", description="Cancellation reason"),
) -> JSONResponse:
    """Request cancellation of any ongoing execution for this session.

    The agent runner checks this flag before each step (graceful) and
    periodically during a step (force). The flag is cleared automatically
    when the orchestrator routes back to the planner.
    """
    request_cancellation(session_id, reason)
    AgentGraphLogger(session_id).mark_running_nodes_cancelled(
        summary=f"Cancelled by user ({reason})"
    )
    return JSONResponse({
        "status": "ok",
        "session_id": session_id,
        "message": "Cancellation requested. The running step will stop at the next checkpoint.",
    })


@app.get("/api/sessions/{session_id}/cancel")
async def get_cancellation_status(session_id: str) -> JSONResponse:
    """Check whether a cancellation is currently pending for this session."""
    flagged = is_cancellation_requested(session_id)
    return JSONResponse({
        "session_id": session_id,
        "cancellation_requested": flagged,
        "reason": get_cancellation_reason(session_id) if flagged else None,
    })


@app.delete("/api/sessions/{session_id}/cancel")
async def clear_cancellation_flag(session_id: str) -> JSONResponse:
    """Manually clear a pending cancellation flag."""
    clear_cancellation(session_id)
    return JSONResponse({
        "status": "ok",
        "session_id": session_id,
        "message": "Cancellation flag cleared.",
    })


@app.post("/api/sessions/{session_id}/cancel-step/{step_number}")
async def cancel_individual_step(
    session_id: str,
    step_number: int,
    reason: str = Query(default="user_requested", description="Cancellation reason"),
) -> JSONResponse:
    """Cancel a specific running step without stopping the whole session.

    The step executor polls the per-step flag and exits at the next checkpoint.
    The graph node for that step is updated immediately so the frontend reflects
    the cancellation before the executor polls.
    """
    request_step_cancellation(session_id, step_number, reason)
    found = AgentGraphLogger(session_id).cancel_step_node_by_number(
        step_number, summary=f"Cancelled by user ({reason})"
    )
    return JSONResponse({
        "status": "ok",
        "session_id": session_id,
        "step_number": step_number,
        "graph_updated": found,
        "message": f"Step {step_number} cancellation requested.",
    })


@app.get("/api/skills")
async def list_skills() -> JSONResponse:
    """Return all loaded skills with their planning_enabled status and parent skill (if any)."""
    from agents.MatCreator.skill import _MODULE_SKILLS_ROOT, _discover_skill_dirs  # noqa: PLC0415

    parent_map: dict[str, str] = {}
    for root in [_MODULE_SKILLS_ROOT, workspace_skills_dir()]:
        for path in _discover_skill_dirs(root):
            parent_skill_md = path.parent / "SKILL.md"
            if parent_skill_md.is_file():
                parent_map[path.name] = path.parent.name

    default_skill_names = get_default_skill_names()
    disabled_skills = set(get_disabled_skills())
    skills = [
        {
            "name": s.name,
            "description": s.description or "",
            "planning_enabled": s.name in PLANNING_SKILL_NAMES,
            "enabled": s.name not in disabled_skills,
            "parent": parent_map.get(s.name),
            "is_custom": s.name not in default_skill_names,
        }
        for s in sorted(ALL_SKILLS, key=lambda s: s.name)
    ]
    return JSONResponse(skills)


@app.get("/api/skills/defaults")
async def list_default_skill_names() -> JSONResponse:
    """Return the names of all bundled default skills."""
    return JSONResponse({"names": sorted(get_default_skill_names())})


_SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


def _validate_skill_md_name(content: bytes, expected_name: str) -> None:
    """Raise ValueError if the SKILL.md frontmatter name field doesn't match expected_name."""
    text = content.decode("utf-8", errors="replace")
    parts = text.split("---")
    if len(parts) < 3:
        return  # No frontmatter; ADK will catch structural issues later
    try:
        frontmatter = yaml.safe_load(parts[1])
    except yaml.YAMLError as exc:
        raise ValueError(f"SKILL.md has invalid YAML frontmatter: {exc}")
    if not isinstance(frontmatter, dict):
        return
    md_name = frontmatter.get("name")
    if md_name is not None and md_name != expected_name:
        raise ValueError(
            f"SKILL.md 'name' field ('{md_name}') does not match the skill directory name ('{expected_name}'). "
            f"Update the 'name' field in SKILL.md to '{expected_name}'."
        )


@app.post("/api/skills/custom")
async def create_custom_skill(
    name: str = Form(...),
    skill_md: UploadFile = File(...),
    references: List[UploadFile] = File(default=[]),
    scripts: List[UploadFile] = File(default=[]),
) -> JSONResponse:
    """Upload a custom skill to the workspace skills directory."""
    name = name.strip()
    if not _SKILL_NAME_RE.match(name):
        raise HTTPException(
            status_code=422,
            detail="Skill name must be lowercase alphanumeric with hyphens/underscores, starting with a letter or digit.",
        )
    if name in get_default_skill_names():
        raise HTTPException(
            status_code=409,
            detail=f"'{name}' is a built-in default skill. Custom skills cannot use the same name.",
        )

    skill_dir = workspace_skills_dir() / name
    skill_dir.mkdir(parents=True, exist_ok=True)

    try:
        skill_md_content = await skill_md.read()
        try:
            _validate_skill_md_name(skill_md_content, name)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        (skill_dir / "SKILL.md").write_bytes(skill_md_content)

        ref_names = []
        non_empty_refs = [r for r in references if r.filename]
        if non_empty_refs:
            ref_dir = skill_dir / "references"
            ref_dir.mkdir(exist_ok=True)
            for ref_file in non_empty_refs:
                safe_name = _safe_upload_filename(ref_file.filename or "ref")
                (ref_dir / safe_name).write_bytes(await ref_file.read())
                ref_names.append(safe_name)

        script_names = []
        non_empty_scripts = [s for s in scripts if s.filename]
        if non_empty_scripts:
            scripts_dir = skill_dir / "scripts"
            scripts_dir.mkdir(exist_ok=True)
            for script_file in non_empty_scripts:
                safe_name = _safe_upload_filename(script_file.filename or "script")
                (scripts_dir / safe_name).write_bytes(await script_file.read())
                script_names.append(safe_name)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to write skill files: {exc}")
    finally:
        await skill_md.close()
        for r in references:
            await r.close()
        for s in scripts:
            await s.close()

    try:
        refresh_skills()
    except Exception as exc:
        shutil.rmtree(skill_dir, ignore_errors=True)
        raise HTTPException(status_code=422, detail=f"Skill files were written but failed to load: {exc}")
    return JSONResponse({"status": "ok", "name": name, "references": ref_names, "scripts": script_names})


@app.delete("/api/skills/custom/{skill_name}")
async def delete_custom_skill(skill_name: str) -> JSONResponse:
    """Delete a custom workspace skill. Default skills cannot be deleted."""
    if not _SKILL_NAME_RE.match(skill_name):
        raise HTTPException(status_code=400, detail=f"Invalid skill name: '{skill_name}'.")
    if skill_name in get_default_skill_names():
        raise HTTPException(
            status_code=400,
            detail=f"'{skill_name}' is a built-in default skill and cannot be deleted.",
        )
    root = workspace_skills_dir()
    skill_dir = root / skill_name
    if skill_dir.resolve() == root.resolve() or not skill_dir.resolve().is_relative_to(root.resolve()):
        raise HTTPException(status_code=400, detail="Invalid skill path.")
    if not skill_dir.exists():
        raise HTTPException(status_code=404, detail=f"Custom skill '{skill_name}' not found in workspace.")
    try:
        shutil.rmtree(skill_dir)
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to delete skill: {exc}")

    try:
        refresh_skills()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Skill deleted but registry reload failed: {exc}")
    return JSONResponse({"status": "ok", "deleted": skill_name})


@app.get("/api/settings")
async def get_settings() -> JSONResponse:
    """Return the current user config."""
    return JSONResponse(load_config())


class SettingsBody(BaseModel):
    planning: dict | None = None
    user: dict | None = None
    skills: dict | None = None


@app.put("/api/settings")
async def update_settings(body: SettingsBody) -> JSONResponse:
    """Merge *body* into the config, persist it, and reload skills."""
    config = load_config()
    if body.planning is not None:
        config.setdefault("planning", {}).update(body.planning)
    if body.user is not None:
        config.setdefault("user", {}).update(body.user)
    if body.skills is not None:
        config.setdefault("skills", {}).update(body.skills)
    save_config(config)
    try:
        refresh_skills()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Settings saved but skill registry reload failed: {exc}")
    return JSONResponse({
        "status": "ok",
        "planning_skill_names": sorted(PLANNING_SKILL_NAMES),
    })


@app.get("/api/env-config")
async def get_env_config() -> JSONResponse:
    """Return the current .env configuration, masking sensitive fields."""
    values = dotenv_values(ENV_PATH) if ENV_PATH.exists() else {}
    result = {}
    for field in _ENV_FIELDS:
        val = values.get(field, "")
        result[field] = "***" if (field in _SENSITIVE_FIELDS and val) else val
    return JSONResponse(result)


class EnvConfigBody(BaseModel):
    values: dict[str, str]


@app.put("/api/env-config")
async def update_env_config(body: EnvConfigBody) -> JSONResponse:
    """Write updated .env fields to disk. Skips masked (***) sensitive values."""
    ENV_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not ENV_PATH.exists():
        ENV_PATH.touch()

    for key, value in body.values.items():
        if key not in _ENV_FIELDS:
            continue
        if key in _SENSITIVE_FIELDS and value == "***":
            continue
        dotenv_set_key(str(ENV_PATH), key, value)

    return JSONResponse({"status": "ok"})


@app.post("/api/restart-backend")
async def restart_backend() -> JSONResponse:
    """Kill the ADK API server on port 8000 and relaunch it."""
    global _adk_process

    _kill_port(8000)
    await asyncio.sleep(1.5)

    try:
        _adk_process = subprocess.Popen(
            ["matcreator", "api-server"],
            cwd=str(ROOT),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        raise HTTPException(status_code=500, detail="'matcreator' command not found in PATH")
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"Failed to start backend: {exc}")

    return JSONResponse({"status": "restarting", "pid": _adk_process.pid})


@app.get("/api/backend-status")
async def get_backend_status() -> JSONResponse:
    """Check whether the ADK API server on port 8000 is reachable."""
    return JSONResponse({"ready": _is_port_open(8000)})


# Serve built frontend in production
_dist = Path(__file__).parent / "vite-frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=str(_dist), html=True), name="static")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=8001)
