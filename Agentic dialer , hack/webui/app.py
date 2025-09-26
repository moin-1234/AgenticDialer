# -----------------------------
# Dynamic Campaigns helpers
# -----------------------------

from __future__ import annotations

import json
import os

DEFAULT_AGENT_CONST = "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS"
DEFAULT_SESSION_CONST = "SESSION_INSTRUCTION"


def _slugify(name: str) -> str:
    base = "".join(ch.lower() if ch.isalnum() else "-" for ch in (name or "").strip())
    while "--" in base:
        base = base.replace("--", "-")
    return base.strip("-") or "campaign"


def _load_campaigns_store() -> List[Dict[str, str]]:
    try:
        if CAMPAIGNS_STORE.exists():
            return json.loads(CAMPAIGNS_STORE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return []


def _save_campaigns_store(items: List[Dict[str, str]]) -> None:
    try:
        CAMPAIGNS_STORE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _generate_prompt_module(module_name: str, agent_text: str, session_text: str) -> Path:
    """Create a python module under campaigns_prompts/ with required constants."""
    p = CAMPAIGNS_DIR / f"{module_name}.py"
    content = (
        "# Auto-generated campaign prompt module\n"
        f"{DEFAULT_AGENT_CONST} = '''\n{agent_text}\n'''.strip()\n\n"
        f"{DEFAULT_SESSION_CONST} = '''\n{session_text}\n'''.strip()\n"
    )
    try:
        if p.exists():
            old = p.read_text(encoding="utf-8")
            if old == content:
                # No change; avoid touching mtime to prevent dev server reload loop
                return p
    except Exception:
        pass
    p.write_text(content, encoding="utf-8")
    return p


def _list_dynamic_campaigns() -> Dict[str, tuple[str, str, str]]:
    """Return mapping like CAMPAIGNS for custom campaigns."""
    items = _load_campaigns_store()
    m: Dict[str, tuple[str, str, str]] = {}
    for it in items:
        name = it.get("name") or ""
        module = it.get("module") or ""
        if name and module:
            # UI label: "CleanName (module)" to be consistent with agent.py keys
            key = f"{name} ({module})"
            m[key] = (f"campaigns_prompts.{module}", DEFAULT_AGENT_CONST, DEFAULT_SESSION_CONST)
    return m


# Optional: Supabase integration for campaigns
_SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
_SUPABASE_SERVICE_ROLE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

def _supabase_client():
    try:
        if not (_SUPABASE_URL and _SUPABASE_SERVICE_ROLE_KEY):
            return None
        from supabase import create_client  # type: ignore
        return create_client(_SUPABASE_URL, _SUPABASE_SERVICE_ROLE_KEY)
    except Exception:
        return None


def _sync_from_supabase_if_available() -> List[Dict[str, str]]:
    """Fetch campaigns from Supabase table 'campaigns' if exists; mirror to local files.
    Table columns expected: name (text), module (text), agent_text (text), session_text (text), created_at (timestamptz default now())
    """
    client = _supabase_client()
    if not client:
        return _load_campaigns_store()
    try:
        resp = client.table("campaigns").select("name,module,agent_text,session_text").execute()
        rows = getattr(resp, "data", []) or []
        items: List[Dict[str, str]] = []
        for r in rows:
            name = (r.get("name") or "").strip()
            module = (r.get("module") or "").strip()
            atext = r.get("agent_text") or ""
            stext = r.get("session_text") or ""
            if not (name and module):
                continue
            # Ensure local prompt module exists and mirrors Supabase content
            try:
                _generate_prompt_module(module, atext, stext)
            except Exception:
                pass
            items.append({"name": name, "module": module})
        # Update local store to reflect remote
        _save_campaigns_store(items)
        return items
    except Exception:
        # Fall back to local store if table missing or any error
        return _load_campaigns_store()

import os
import sys
import csv
import math
import subprocess
from pathlib import Path
from typing import List, Dict, Optional

from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse, Response, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# Use project root as base
BASE_DIR = Path(__file__).resolve().parents[1]
AGENT_PATH = str(BASE_DIR / "agent.py")
LEADS_CSV = os.getenv("LEADS_CSV_PATH", str(BASE_DIR / "leads.csv"))
CSV_DIR = Path(os.getenv("LEADS_CSV_DIR", str(BASE_DIR))).resolve()
CSV_DIR.mkdir(parents=True, exist_ok=True)
_SELECTED_FILE_STORE = BASE_DIR / ".leads_csv"
CAMPAIGNS_DIR = BASE_DIR / "campaigns_prompts"
CAMPAIGNS_DIR.mkdir(parents=True, exist_ok=True)
CAMPAIGNS_STORE = BASE_DIR / "campaigns.json"

# Import campaign mapping and display helper from backend
try:
    sys.path.insert(0, str(BASE_DIR))
    from agent import CAMPAIGNS, _campaign_display_name
except Exception:
    CAMPAIGNS = {
        "Default": ("prompts", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
        "SplashBI": ("prompts2", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
        "KonfHub": ("prompts3", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
        "Zoom Phone": ("prompts4", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
    }
    def _campaign_display_name(name: str) -> str:  # type: ignore
        return name

app = FastAPI(title="AI Calling Agent - Web UI")

# Mount static and templates
STATIC_DIR = Path(__file__).resolve().parent / "static"
TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
TEMPLATES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

PAGE_SIZE = 8

# LiveKit credentials (for token issuance)
LIVEKIT_URL = os.getenv("LIVEKIT_URL", "")
LIVEKIT_API_KEY = os.getenv("LIVEKIT_API_KEY", "")
LIVEKIT_API_SECRET = os.getenv("LIVEKIT_API_SECRET", "")

# We'll sign tokens using PyJWT to avoid extra deps
import time
import jwt  # PyJWT
import httpx

# Cache for vendor script to avoid repeated external fetches
_LK_JS_CACHE: dict[str, bytes] = {}

# Global state for managing a single running console call
from threading import Lock, Thread
import signal

_proc_lock = Lock()
CURRENT_PROC: Optional[subprocess.Popen] = None
CURRENT_STATUS: str = "idle"  # idle | running | stopping
CURRENT_LEAD_INDEX: Optional[int] = None  # 1-based
SELECTED_CAMPAIGN: Optional[str] = None
AUTO_NEXT: bool = False
_WATCHER_STARTED: bool = False

# -----------------------------
# CSV management helpers
# -----------------------------

def _safe_csv_name(name: str) -> str:
    name = (name or "").strip()
    # Strip directories and only allow basic chars
    name = os.path.basename(name)
    # Enforce .csv extension
    if not name.lower().endswith(".csv"):
        name = name + ".csv"
    # Replace unsafe characters
    safe = []
    for ch in name:
        if ch.isalnum() or ch in ("-", "_", "."):
            safe.append(ch)
        else:
            safe.append("_")
    return "".join(safe)


def _persist_selected_csv(path: Path) -> None:
    try:
        _SELECTED_FILE_STORE.write_text(str(path.resolve()), encoding="utf-8")
    except Exception:
        pass


def _load_persisted_selected_csv() -> Optional[Path]:
    try:
        p = _SELECTED_FILE_STORE.read_text(encoding="utf-8").strip()
        candidate = Path(p)
        if candidate.suffix.lower() == ".csv" and candidate.exists():
            return candidate
    except Exception:
        pass
    return None


def read_leads(csv_path: str) -> List[Dict[str, str]]:
    """Read leads with as many useful fields as available."""
    leads: List[Dict[str, str]] = []
    try:
        with open(csv_path, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                leads.append({
                    "prospect_name": (row.get("prospect_name") or "").strip(),
                    "company_name": (row.get("company_name") or "").strip(),
                    "job_title": (row.get("job_title") or "").strip(),
                    "phone": (row.get("phone") or "").strip(),
                    "email": (row.get("email") or "").strip(),
                    "timezone": (row.get("timezone") or "").strip(),
                })
    except FileNotFoundError:
        pass
    return leads


def get_lead_by_index_1based(idx1: int) -> Optional[Dict[str, str]]:
    try:
        leads = read_leads(LEADS_CSV)
        if 1 <= idx1 <= len(leads):
            return leads[idx1 - 1]
    except Exception:
        pass
    return None


# Initialize selected CSV from persisted file if available
persisted = _load_persisted_selected_csv()
if persisted:
    LEADS_CSV = str(persisted)


def spawn_call(lead_index_1based: int, campaign_key: Optional[str]) -> None:
    env = os.environ.copy()
    env["RUN_SINGLE_CALL"] = "1"
    env["LEAD_INDEX"] = str(lead_index_1based)

    # Apply campaign env if provided
    def _all_campaigns_map() -> Dict[str, tuple[str, str, str]]:
        m = dict(CAMPAIGNS)
        try:
            m.update(_list_dynamic_campaigns())
        except Exception:
            pass
        return m

    cmap = _all_campaigns_map()
    if campaign_key and campaign_key in cmap:
        mod, agent_attr, session_attr = cmap[campaign_key]
        env["CAMPAIGN_PROMPT_MODULE"] = mod
        env["CAMPAIGN_AGENT_NAME"] = agent_attr
        env["CAMPAIGN_SESSION_NAME"] = session_attr

    # Launch console subcommand to get audio I/O and track process
    global CURRENT_PROC, CURRENT_STATUS, CURRENT_LEAD_INDEX
    with _proc_lock:
        # If a process is already running, do not start another
        if CURRENT_PROC and CURRENT_PROC.poll() is None:
            return
        creationflags = 0
        if sys.platform == "win32":
            # Create new process group to allow signal/termination management
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        CURRENT_PROC = subprocess.Popen(
            [sys.executable, AGENT_PATH, "console"], env=env, creationflags=creationflags
        )
        CURRENT_STATUS = "running"
        CURRENT_LEAD_INDEX = lead_index_1based


def spawn_agent_connect_room(room_name: str, campaign_key: Optional[str]) -> None:
    """Spawn agent to connect to a specific room so the browser can converse with it."""
    env = os.environ.copy()
    env["RUN_SINGLE_CALL"] = "1"
    if campaign_key and campaign_key in CAMPAIGNS:
        mod, agent_attr, session_attr = CAMPAIGNS[campaign_key]
        env["CAMPAIGN_PROMPT_MODULE"] = mod
        env["CAMPAIGN_AGENT_NAME"] = agent_attr
        env["CAMPAIGN_SESSION_NAME"] = session_attr
    # Use LiveKit CLI subcommand 'connect' with a room name; the Agents CLI will join that room
    subprocess.Popen([sys.executable, AGENT_PATH, "connect", "--room", room_name], env=env)


def _end_current_call() -> bool:
    """Attempt to gracefully stop the current console call. Returns True if a process was signaled/terminated."""
    global CURRENT_PROC, CURRENT_STATUS
    with _proc_lock:
        proc = CURRENT_PROC
        if not proc or proc.poll() is not None:
            CURRENT_PROC = None
            CURRENT_STATUS = "idle"
            return False
        CURRENT_STATUS = "stopping"
        try:
            if sys.platform == "win32":
                # Best-effort terminate on Windows
                proc.terminate()
            else:
                proc.send_signal(signal.SIGINT)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        return True


def _cleanup_if_exited() -> None:
    """Reset globals if the process has exited."""
    global CURRENT_PROC, CURRENT_STATUS
    with _proc_lock:
        if CURRENT_PROC and CURRENT_PROC.poll() is not None:
            CURRENT_PROC = None
            CURRENT_STATUS = "idle"


def _watcher_loop():
    """Background loop to auto-start next call when a call ends and AUTO_NEXT is enabled."""
    last_running = False
    while True:
        try:
            with _proc_lock:
                running = CURRENT_PROC is not None and CURRENT_PROC.poll() is None
                lead_idx = CURRENT_LEAD_INDEX
                campaign = SELECTED_CAMPAIGN
            # Transition: running -> not running
            if last_running and not running:
                # Ensure cleanup
                _cleanup_if_exited()
                if AUTO_NEXT and lead_idx is not None:
                    # Start next automatically
                    try:
                        spawn_call(lead_idx + 1, campaign)
                    except Exception:
                        pass
            last_running = running
        except Exception:
            pass
        time.sleep(1)


@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, page: int = 1, campaign: Optional[str] = None):
    leads = read_leads(LEADS_CSV)
    total = len(leads)
    total_pages = max(1, math.ceil(total / PAGE_SIZE))
    page = max(1, min(page, total_pages))
    start = (page - 1) * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)

    # Merge built-in and dynamic campaigns for dropdown
    all_campaigns = dict(CAMPAIGNS)
    try:
        all_campaigns.update(_list_dynamic_campaigns())
    except Exception:
        pass
    campaign_options = []
    for k in all_campaigns.keys():
        clean = _campaign_display_name(k)
        if clean.lower().startswith("default"):
            continue
        campaign_options.append({"key": k, "label": clean, "selected": (campaign == k)})

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "campaign": campaign,
            "campaign_options": campaign_options,
            "leads": leads[start:end],
            "page": page,
            "total_pages": total_pages,
            "start_index": start,  # zero-based for row numbering
            "active_csv": os.path.basename(LEADS_CSV) if LEADS_CSV else "",
        },
    )


@app.post("/call")
async def call_lead(
    background_tasks: BackgroundTasks,
    lead_global_index: int = Form(...),  # zero-based from page
    campaign: Optional[str] = Form(None),
    page: int = Form(1),
):
    # Convert zero-based to one-based for backend
    lead_index_1based = lead_global_index + 1
    background_tasks.add_task(spawn_call, lead_index_1based, campaign)

    # Redirect back to the current page
    url = f"/?page={page}"
    if campaign:
        url += f"&campaign={campaign}"
    return RedirectResponse(url=url, status_code=303)


# -----------------------------
# CSV Management API
# -----------------------------

@app.get("/api/csv/list")
async def api_csv_list():
    files = []
    try:
        for p in sorted(CSV_DIR.glob("*.csv")):
            try:
                stat = p.stat()
                files.append({
                    "name": p.name,
                    "size": stat.st_size,
                    "mtime": int(stat.st_mtime),
                    "active": str(p.resolve()) == str(Path(LEADS_CSV).resolve()) if LEADS_CSV else False,
                })
            except Exception:
                continue
    except Exception:
        pass
    return JSONResponse({"ok": True, "files": files})


@app.post("/api/csv/upload")
async def api_csv_upload(file: UploadFile = File(...)):
    if not file or not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")
    name = _safe_csv_name(file.filename)
    dest = CSV_DIR / name
    try:
        content = await file.read()
        # Basic size guard (10MB)
        if len(content) > 10 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="File too large (max 10MB)")
        dest.write_bytes(content)
        return JSONResponse({"ok": True, "name": name})
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to save file")


@app.post("/api/csv/select")
async def api_csv_select(name: str = Form(...)):
    global LEADS_CSV
    name = _safe_csv_name(name)
    target = (CSV_DIR / name).resolve()
    if not target.exists() or target.suffix.lower() != ".csv":
        raise HTTPException(status_code=404, detail="CSV not found")
    LEADS_CSV = str(target)
    _persist_selected_csv(target)
    return JSONResponse({"ok": True, "active": name})


@app.delete("/api/csv/{name}")
async def api_csv_delete(name: str):
    name = _safe_csv_name(name)
    target = (CSV_DIR / name).resolve()
    # Prevent deleting active CSV in-use
    if LEADS_CSV and Path(LEADS_CSV).resolve() == target:
        raise HTTPException(status_code=400, detail="Cannot delete the active CSV. Select another file first.")
    if not target.exists() or target.suffix.lower() != ".csv":
        raise HTTPException(status_code=404, detail="CSV not found")
    try:
        target.unlink()
        return JSONResponse({"ok": True})
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to delete file")


@app.get("/api/csv/preview")
async def api_csv_preview(name: str, limit: int = 10):
    name = _safe_csv_name(name)
    target = (CSV_DIR / name).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="CSV not found")
    try:
        rows = []
        headers: List[str] = []
        with open(target, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            headers = list(reader.fieldnames or [])
            for i, row in enumerate(reader):
                if i >= max(1, limit):
                    break
                rows.append({k: (row.get(k) or "") for k in headers})
        return JSONResponse({"ok": True, "headers": headers, "rows": rows})
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read CSV")


@app.get("/api/csv/download/{name}")
async def api_csv_download(name: str):
    name = _safe_csv_name(name)
    target = (CSV_DIR / name).resolve()
    if not target.exists():
        raise HTTPException(status_code=404, detail="CSV not found")
    return FileResponse(str(target), media_type="text/csv", filename=name)


# -----------------------------
# Campaigns Management API
# -----------------------------

@app.get("/api/campaigns/list")
async def api_campaigns_list():
    # If Supabase configured, sync down first
    items = _sync_from_supabase_if_available()
    # add built-ins (read-only)
    builtin = []
    for k in CAMPAIGNS.keys():
        builtin.append({
            "name": _campaign_display_name(k),
            "module": CAMPAIGNS[k][0],
            "builtin": True,
            "key": k,
        })
    return JSONResponse({"ok": True, "builtin": builtin, "custom": items})


@app.post("/api/campaigns/create")
async def api_campaigns_create(name: str = Form(...), agent_text: str = Form(""), session_text: str = Form(""), module: str = Form("") ):
    name = (name or "").strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name required")
    items = _load_campaigns_store()
    # If a module was provided, prefer it; else derive from name
    provided = (module or "").strip()
    slug = _slugify(provided if provided else name)
    # ensure unique slug
    base_slug = slug
    i = 1
    existing = {it.get("module") for it in items}
    while slug in existing:
        slug = f"{base_slug}-{i}"; i += 1
    # write module file locally
    _generate_prompt_module(slug, agent_text or "", session_text or "")
    # try supabase first
    client = _supabase_client()
    supabase_error = None
    if client:
        try:
            client.table("campaigns").insert({
                "name": name,
                "module": slug,
                "agent_text": agent_text or "",
                "session_text": session_text or "",
            }).execute()
        except Exception as e:
            supabase_error = str(e)
    # always update local store as mirror
    items.append({"name": name, "module": slug})
    _save_campaigns_store(items)
    return JSONResponse({"ok": True, "name": name, "module": slug, "supabase_error": supabase_error})


@app.delete("/api/campaigns/{module}")
async def api_campaigns_delete(module: str):
    module = (module or "").strip()
    items = _load_campaigns_store()
    found = None
    for it in items:
        if it.get("module") == module:
            found = it
            break
    if not found:
        raise HTTPException(status_code=404, detail="Campaign not found")
    # remove from supabase first if available
    client = _supabase_client()
    if client:
        try:
            client.table("campaigns").delete().eq("module", module).execute()
        except Exception:
            pass
    # remove local file
    try:
        (CAMPAIGNS_DIR / f"{module}.py").unlink(missing_ok=True)
    except Exception:
        pass
    # save store
    items = [it for it in items if it.get("module") != module]
    _save_campaigns_store(items)
    return JSONResponse({"ok": True})


# Additional Campaigns endpoints: get, update, upload prompts, seed supabase

def _read_prompts_for_module(module: str) -> tuple[str, str]:
    """Import the prompt module and read constants. Falls back to empty strings on error."""
    try:
        import importlib
        mod = importlib.import_module(f"campaigns_prompts.{module}")
        agent_text = getattr(mod, DEFAULT_AGENT_CONST, "")
        session_text = getattr(mod, DEFAULT_SESSION_CONST, "")
        return str(agent_text or ""), str(session_text or "")
    except Exception:
        return "", ""


@app.get("/api/campaigns/get")
async def api_campaigns_get(module: str):
    module = (module or "").strip()
    items = _load_campaigns_store()
    name = next((it.get("name") for it in items if it.get("module") == module), "")
    atext, stext = _read_prompts_for_module(module)
    if not name:
        # If not found locally but module file exists, use module as name
        name = module
    return JSONResponse({"ok": True, "name": name, "module": module, "agent_text": atext, "session_text": stext})


@app.post("/api/campaigns/update")
async def api_campaigns_update(module: str = Form(...), name: str = Form(""), agent_text: str = Form(""), session_text: str = Form("")):
    module = (module or "").strip()
    name = (name or "").strip() or module
    # Update local prompt file
    _generate_prompt_module(module, agent_text or "", session_text or "")
    # Update local store name
    items = _load_campaigns_store()
    found = False
    for it in items:
        if it.get("module") == module:
            it["name"] = name
            found = True
            break
    if not found:
        items.append({"name": name, "module": module})
    _save_campaigns_store(items)
    # Upsert in Supabase if available
    client = _supabase_client()
    if client:
        try:
            client.table("campaigns").upsert({
                "name": name,
                "module": module,
                "agent_text": agent_text or "",
                "session_text": session_text or "",
            }, on_conflict="module").execute()
        except Exception:
            pass
    return JSONResponse({"ok": True})


@app.post("/api/campaigns/upload_prompts")
async def api_campaigns_upload_prompts(which: str = Form(...), file: UploadFile = File(...)):
    which = (which or "").strip().lower()
    if which not in ("agent", "session"):
        raise HTTPException(status_code=400, detail="which must be 'agent' or 'session'")
    try:
        content = (await file.read()).decode("utf-8", errors="ignore")
    except Exception:
        raise HTTPException(status_code=400, detail="Failed to read file")
    return JSONResponse({"ok": True, "which": which, "text": content})


@app.post("/api/campaigns/seed_supabase")
async def api_campaigns_seed_supabase():
    client = _supabase_client()
    if not client:
        raise HTTPException(status_code=400, detail="Supabase not configured")
    items = _load_campaigns_store()
    upserted = 0
    errors: List[str] = []
    for it in items:
        module = it.get("module") or ""
        name = it.get("name") or module
        atext, stext = _read_prompts_for_module(module)
        try:
            client.table("campaigns").upsert({
                "name": name,
                "module": module,
                "agent_text": atext,
                "session_text": stext,
            }, on_conflict="module").execute()
            upserted += 1
        except Exception as e:
            errors.append(f"{module}: {e}")
            continue
    return JSONResponse({"ok": True, "count": upserted, "errors": errors})


@app.get("/api/campaigns/module_file")
async def api_campaigns_module_file(module: str):
    module = (module or "").strip()
    p = CAMPAIGNS_DIR / f"{module}.py"
    if not p.exists():
        raise HTTPException(status_code=404, detail="Module file not found")
    try:
        text = p.read_text(encoding="utf-8")
    except Exception:
        raise HTTPException(status_code=500, detail="Failed to read module file")
    return JSONResponse({"ok": True, "module": module, "path": str(p), "content": text})
# -----------------------------
# JSON APIs for console control
# -----------------------------

@app.post("/api/select_campaign")
async def api_select_campaign(campaign: Optional[str] = Form(None)):
    global SELECTED_CAMPAIGN
    # validate against built-in + dynamic
    valid = set(CAMPAIGNS.keys())
    try:
        valid.update(_list_dynamic_campaigns().keys())
    except Exception:
        pass
    if campaign and campaign not in valid:
        raise HTTPException(status_code=400, detail="Unknown campaign")
    SELECTED_CAMPAIGN = campaign
    label = _campaign_display_name(campaign) if campaign else None
    return JSONResponse({"ok": True, "campaign": campaign, "campaign_label": label})


@app.post("/api/start_call")
async def api_start_call(lead_global_index: int = Form(...), campaign: Optional[str] = Form(None)):
    # Prefer explicit campaign from form; otherwise use last selected
    effective_campaign = campaign if campaign is not None else SELECTED_CAMPAIGN
    idx1 = lead_global_index + 1
    spawn_call(idx1, effective_campaign)
    return JSONResponse({
        "ok": True,
        "status": CURRENT_STATUS,
        "lead_index": CURRENT_LEAD_INDEX,
        "campaign": effective_campaign,
        "campaign_label": _campaign_display_name(effective_campaign) if effective_campaign else None,
    })


@app.post("/api/end_call")
async def api_end_call(auto_next: bool = Form(True)):
    """End current call; optionally start the next call automatically."""
    global CURRENT_LEAD_INDEX
    prev = CURRENT_LEAD_INDEX
    had_proc = _end_current_call()
    # Wait briefly for process to exit
    time.sleep(0.4)
    _cleanup_if_exited()
    started_next = False
    if auto_next and prev is not None:
        next_idx = prev + 1
        spawn_call(next_idx, SELECTED_CAMPAIGN)
        started_next = True
    return JSONResponse({
        "ok": True,
        "had_proc": had_proc,
        "status": CURRENT_STATUS,
        "lead_index": CURRENT_LEAD_INDEX,
        "auto_next_started": started_next,
        "campaign": SELECTED_CAMPAIGN,
        "campaign_label": _campaign_display_name(SELECTED_CAMPAIGN) if SELECTED_CAMPAIGN else None,
    })


@app.get("/api/status")
async def api_status():
    _cleanup_if_exited()
    running = CURRENT_PROC is not None and CURRENT_PROC.poll() is None
    lead_details = get_lead_by_index_1based(CURRENT_LEAD_INDEX) if CURRENT_LEAD_INDEX else None
    return JSONResponse({
        "status": CURRENT_STATUS,
        "running": running,
        "lead_index": CURRENT_LEAD_INDEX,
        "campaign": SELECTED_CAMPAIGN,
        "campaign_label": _campaign_display_name(SELECTED_CAMPAIGN) if SELECTED_CAMPAIGN else None,
        "auto_next": AUTO_NEXT,
        "lead": lead_details or {},
    })


@app.post("/api/auto_next")
async def api_auto_next(enabled: bool = Form(...)):
    global AUTO_NEXT
    AUTO_NEXT = bool(str(enabled).lower() in ["1", "true", "yes", "on"])
    return JSONResponse({"ok": True, "auto_next": AUTO_NEXT})


@app.post("/api/stop_all")
async def api_stop_all():
    """Disable auto-next and end any running call (end whole session)."""
    global AUTO_NEXT
    AUTO_NEXT = False
    _end_current_call()
    time.sleep(0.4)
    _cleanup_if_exited()
    return JSONResponse({"ok": True, "status": CURRENT_STATUS, "auto_next": AUTO_NEXT})


# Start watcher thread once
def _ensure_watcher_started():
    global _WATCHER_STARTED
    if not _WATCHER_STARTED:
        t = Thread(target=_watcher_loop, daemon=True)
        t.start()
        _WATCHER_STARTED = True


_ensure_watcher_started()


@app.get("/vendor/livekit-client.js")
async def vendor_livekit_client():
    """Serve the LiveKit Web SDK via backend to bypass CDN/network blocks.
    Caches the file in memory for subsequent requests.
    """
    cache_key = "livekit-client-2.3.3"
    if cache_key in _LK_JS_CACHE:
        return Response(content=_LK_JS_CACHE[cache_key], media_type="application/javascript")
    cdns = [
        "https://cdn.livekit.io/npm/livekit-client/2.3.3/livekit-client.umd.min.js",
        "https://unpkg.com/livekit-client@2.3.3/dist/livekit-client.umd.min.js",
        "https://cdn.jsdelivr.net/npm/livekit-client@2.3.3/dist/livekit-client.umd.min.js",
    ]
    for url in cdns:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                if r.status_code == 200 and r.content:
                    _LK_JS_CACHE[cache_key] = r.content
                    return Response(content=r.content, media_type="application/javascript")
        except Exception:
            continue
    raise HTTPException(status_code=502, detail="Failed to load LiveKit client script from CDNs")


@app.get("/vendor/livekit-client.esm.js")
async def vendor_livekit_client_esm():
    """Serve the LiveKit Web ESM build via backend to bypass CORS/CDN blocks."""
    cache_key = "livekit-client-esm-2.3.3"
    if cache_key in _LK_JS_CACHE:
        return Response(content=_LK_JS_CACHE[cache_key], media_type="application/javascript")
    cdns = [
        "https://unpkg.com/livekit-client@2.3.3/dist/livekit-client.esm.min.js",
        "https://cdn.jsdelivr.net/npm/livekit-client@2.3.3/dist/livekit-client.esm.min.js",
        "https://unpkg.com/livekit-client/dist/livekit-client.esm.min.js",
    ]
    for url in cdns:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                r = await client.get(url)
                if r.status_code == 200 and r.content:
                    _LK_JS_CACHE[cache_key] = r.content
                    return Response(content=r.content, media_type="application/javascript")
        except Exception:
            continue
    raise HTTPException(status_code=502, detail="Failed to load LiveKit ESM module from CDNs")


@app.post("/browser/start")
async def start_browser_call(
    background_tasks: BackgroundTasks,
    lead_global_index: int = Form(...),
    campaign: Optional[str] = Form(None),
):
    # Create a simple deterministic room name by index (you may swap for UUID)
    room_name = f"room-{lead_global_index+1}"
    background_tasks.add_task(spawn_agent_connect_room, room_name, campaign)
    return RedirectResponse(url=f"/browser/call?room={room_name}{'&campaign='+campaign if campaign else ''}", status_code=303)


@app.get("/browser/call", response_class=HTMLResponse)
async def browser_call(request: Request, room: str, campaign: Optional[str] = None):
    if not LIVEKIT_URL:
        raise HTTPException(status_code=500, detail="LIVEKIT_URL not configured")
    return templates.TemplateResponse(
        "browser_call.html",
        {
            "request": request,
            "room": room,
            "livekit_url": LIVEKIT_URL,
            "campaign": campaign or "",
        },
    )


@app.get("/api/token")
async def issue_token(room: str, identity: str):
    if not (LIVEKIT_API_KEY and LIVEKIT_API_SECRET and LIVEKIT_URL):
        raise HTTPException(status_code=500, detail="LiveKit credentials not configured")
    now = int(time.time())
    payload = {
        "iss": LIVEKIT_API_KEY,
        "sub": LIVEKIT_API_KEY,
        "nbf": now - 10,
        "exp": now + 60 * 10,  # 10 minutes
        "video": {
            "room": room,
            "roomJoin": True,
            "canPublish": True,
            "canSubscribe": True,
        },
        "identity": identity,
        "name": identity,
    }
    token = jwt.encode(payload, LIVEKIT_API_SECRET, algorithm="HS256")
    return JSONResponse({"token": token})


@app.post("/next")
async def call_next(
    background_tasks: BackgroundTasks,
    next_index: int = Form(...),  # zero-based next pointer from UI
    campaign: Optional[str] = Form(None),
    page: int = Form(1),
):
    lead_index_1based = next_index + 1
    background_tasks.add_task(spawn_call, lead_index_1based, campaign)

    url = f"/?page={page}"
    if campaign:
        url += f"&campaign={campaign}"
    return RedirectResponse(url=url, status_code=303)
