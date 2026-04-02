"""FastAPI application entry point for WorldSense Web UI."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, BackgroundTasks, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from worldsense.core.engine import ResearchEngine
from worldsense.core.settings import (
    SystemSettings, GeneralSettings, LLMSettings, AdvancedSettings, LLMProfile,
    load_settings, save_settings, invalidate_cache, get_active_profile,
)
from worldsense.llm.vision_probe import probe_vision
from worldsense.core.task import ResearchTask, TaskStatus
from worldsense.llm import get_backend
from worldsense.persona.epsilon import generate_epsilon
from worldsense.persona.generator import PersonaGenerator, MARKET_COUNTRIES, DimensionConfig

# ---------------------------------------------------------------------------
# App instance
# ---------------------------------------------------------------------------
app = FastAPI(
    title="WorldSense",
    description="AI-powered large-scale user research simulation platform",
    version="0.1.0",
    root_path="/worldsense",
)

# ---------------------------------------------------------------------------
# Upload directory
# ---------------------------------------------------------------------------
UPLOAD_DIR = Path(os.path.expanduser("~/projects/worldsense/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

ALLOWED_EXTENSIONS = {
    ".pdf", ".jpg", ".jpeg", ".png", ".webp", ".gif",
    ".txt", ".md", ".docx", ".doc", ".mp4",
}
MAX_UPLOAD_MB = 50

# ---------------------------------------------------------------------------
# In-memory task registry
# ---------------------------------------------------------------------------
_tasks: dict[str, ResearchTask] = {}

OUTPUT_DIR = Path(os.path.expanduser("~/.worldsense/results"))
STALE_TASK_MINUTES = 30


def _cleanup_stale_tasks() -> None:
    """Mark running tasks that started >30 min ago as failed (zombie cleanup)."""
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    for p in OUTPUT_DIR.glob("*.json"):
        try:
            data = json.loads(p.read_text())
            task_data = data.get("task", data)
            if task_data.get("status") != "running":
                continue
            started_at_raw = task_data.get("started_at")
            if not started_at_raw:
                continue
            # Parse ISO datetime (may or may not have timezone info)
            started_at = datetime.fromisoformat(started_at_raw.replace("Z", "+00:00"))
            if started_at.tzinfo is None:
                started_at = started_at.replace(tzinfo=timezone.utc)
            elapsed_minutes = (now - started_at).total_seconds() / 60
            if elapsed_minutes > STALE_TASK_MINUTES:
                task_data["status"] = "failed"
                task_data["error"] = "Stale task (server restarted)"
                data["task"] = task_data
                p.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        except Exception:
            pass


def _load_persisted_tasks() -> None:
    for task_data in ResearchEngine.list_tasks():
        try:
            t = ResearchTask.model_validate(task_data)
            _tasks[t.task_id] = t
        except Exception:
            pass


@app.on_event("startup")
async def startup_event() -> None:
    _cleanup_stale_tasks()
    _load_persisted_tasks()


# ---------------------------------------------------------------------------
# Schemas (JSON endpoints)
# ---------------------------------------------------------------------------

class DimensionConfigSchema(BaseModel):
    nationality_weights: Optional[dict[str, float]] = None
    age_weights: Optional[dict[str, float]] = None
    gender_weights: Optional[dict[str, float]] = None
    income_weights: Optional[dict[str, float]] = None
    occupation_ids: Optional[list[str]] = None
    personality_traits: Optional[list[str]] = None


class PersonaPreviewRequest(BaseModel):
    count: int = 5
    market: str = "global"
    dimensions: Optional[DimensionConfigSchema] = None


# ---------------------------------------------------------------------------
# Background runner
# ---------------------------------------------------------------------------

async def _run_task_bg(task: ResearchTask) -> None:
    try:
        engine = ResearchEngine(task)
        await engine.run()
    except Exception as e:
        task.status = TaskStatus.FAILED
        task.error = str(e)


# ---------------------------------------------------------------------------
# GLM-4.6V image description
# ---------------------------------------------------------------------------

async def _describe_image_glm(image_path: str) -> str:
    """Call GLM-4.6V to get a text description of an image. Returns description or empty string."""
    api_key = os.getenv("WS_API_KEY", "")
    base_url = os.getenv("WS_API_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4").rstrip("/")

    try:
        img_bytes = Path(image_path).read_bytes()
        b64_data = base64.b64encode(img_bytes).decode("utf-8")
        suffix = Path(image_path).suffix.lower().lstrip(".")
        mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                    "webp": "image/webp", "gif": "image/gif"}
        mime_type = mime_map.get(suffix, "image/jpeg")

        payload = {
            "model": "glm-4.6v",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mime_type};base64,{b64_data}"}
                        },
                        {
                            "type": "text",
                            "text": "请详细描述这张图片的内容，包括画面中的人物、物体、文字、布局、色彩风格等关键信息，用中文回答，2-4句话。"
                        }
                    ]
                }
            ],
            "max_tokens": 512,
        }

        async with httpx.AsyncClient(timeout=60.0) as client:
            resp = await client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "").strip()
            return content

    except Exception as e:
        # Graceful degradation — image description failure doesn't block the task
        return ""


# ---------------------------------------------------------------------------
# File parsing helpers
# ---------------------------------------------------------------------------

def _extract_text_from_file(path: Path, suffix: str) -> str:
    """Extract text content from a file. Returns extracted text or empty string."""
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="replace")

        if suffix == ".pdf":
            try:
                import fitz  # PyMuPDF
                doc = fitz.open(str(path))
                parts = []
                for page in doc:
                    parts.append(page.get_text())
                doc.close()
                return "\n".join(parts)
            except ImportError:
                return f"[PDF: {path.name} — PyMuPDF not installed, cannot extract text]"

        if suffix in {".docx", ".doc"}:
            try:
                from docx import Document
                doc = Document(str(path))
                return "\n".join(p.text for p in doc.paragraphs if p.text.strip())
            except ImportError:
                return f"[Word: {path.name} — python-docx not installed, cannot extract text]"

    except Exception as e:
        return f"[Error extracting text from {path.name}: {e}]"

    # Images / video: no text extraction this version
    return ""


# ---------------------------------------------------------------------------
# Helper: save uploaded file, return metadata dict
# ---------------------------------------------------------------------------

def _save_upload(file: UploadFile, task_id: str) -> dict:
    """Persist an uploaded file under uploads/<task_id>/ and return metadata dict."""
    original_name = file.filename or "upload"
    suffix = Path(original_name).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}",
        )

    # Per-task subdirectory
    task_upload_dir = UPLOAD_DIR / task_id
    task_upload_dir.mkdir(parents=True, exist_ok=True)

    # Unique filename
    saved_name = f"{uuid.uuid4().hex}{suffix}"
    dest = task_upload_dir / saved_name

    file.file.seek(0, 2)  # seek to end
    size_bytes = file.file.tell()
    if size_bytes > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File too large (max {MAX_UPLOAD_MB} MB)")
    file.file.seek(0)

    with dest.open("wb") as f:
        shutil.copyfileobj(file.file, f)

    file_type = (
        "image" if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif"} else
        "pdf"   if suffix == ".pdf" else
        "word"  if suffix in {".docx", ".doc"} else
        "text"  if suffix in {".txt", ".md"} else
        "video"
    )

    # Extract text for text-based files
    extracted_text = ""
    parse_status = "skipped"
    if file_type in {"pdf", "word", "text"}:
        extracted_text = _extract_text_from_file(dest, suffix)
        parse_status = "ok" if extracted_text and not extracted_text.startswith("[") else "error"

    return {
        "original_name": original_name,
        "saved_name": saved_name,
        "path": str(dest),
        "size_bytes": size_bytes,
        "file_type": file_type,
        "suffix": suffix,
        "parse_status": parse_status,
        "extracted_text": extracted_text,
    }


# ---------------------------------------------------------------------------
# Evaluation criteria label map
# ---------------------------------------------------------------------------

EVAL_CRITERIA_LABELS: dict[str, str] = {
    "follow_subscribe":   "Would you follow/subscribe after reading this?",
    "pay_willingness":    "Would you pay for this? What price range is acceptable?",
    "share_willingness":  "Would you share this with friends?",
    "overall_impression": "Rate 1-10. What impressed you most and least?",
    "goal_match":         "What problem does this solve for you?",
    "purchase_decision":  "Would you buy this? What factors drive your decision?",
}


def _build_eval_instructions(
    evaluation_criteria: list[str],
    custom_instructions: str,
) -> str:
    """Combine selected criteria + custom instructions into an evaluation directive."""
    parts = []

    criteria_questions = [
        EVAL_CRITERIA_LABELS[c]
        for c in evaluation_criteria
        if c in EVAL_CRITERIA_LABELS
    ]
    if criteria_questions:
        parts.append("In your evaluation, specifically address the following questions:")
        for q in criteria_questions:
            parts.append(f"  - {q}")

    if custom_instructions.strip():
        parts.append("Additional evaluation instructions:")
        parts.append(f"  {custom_instructions.strip()}")

    return "\n".join(parts)


# ---------------------------------------------------------------------------
# API: POST /api/run  (multipart/form-data)
# ---------------------------------------------------------------------------

@app.post("/api/run")
async def create_run(
    background_tasks: BackgroundTasks,
    # Text fields as Form params
    content: Annotated[str, Form()] = "",
    scenario_context: Annotated[str, Form()] = "",
    personas_count: Annotated[int, Form()] = 20,
    market: Annotated[str, Form()] = "global",
    backend: Annotated[str, Form()] = "",  # empty = use settings.llm.provider
    concurrency: Annotated[int, Form()] = 10,
    # dimensions as JSON string (multipart can't send nested objects natively)
    dimensions_json: Annotated[Optional[str], Form()] = None,
    # Evaluation criteria (JSON array of criterion IDs)
    evaluation_criteria_json: Annotated[Optional[str], Form()] = None,
    # Custom evaluation instructions
    custom_instructions: Annotated[str, Form()] = "",
    # Output language for simulation (affects verbatim + key fields)
    language: Annotated[str, Form()] = "English",
    # Research type / evaluation preset ID (affects intent field values)
    research_type: Annotated[str, Form()] = "product_purchase",
    # Max retries for exponential backoff (-1 = use settings)
    max_retries: Annotated[int, Form()] = -1,
    # LLM profile to use (empty = use default active profile)
    profile_name: Annotated[str, Form()] = "",
    # Vision mode: "summary" (default, one-time system description) or "per_persona" (each persona sees images)
    vision_mode: Annotated[str, Form()] = "summary",
    # Optional file attachments
    files: Annotated[list[UploadFile], File()] = [],
):
    """Submit a new research task (multipart form — supports file attachments)."""
    if vision_mode not in ("summary", "per_persona"):
        raise HTTPException(status_code=400, detail="vision_mode must be 'summary' or 'per_persona'")
    if market not in MARKET_COUNTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown market '{market}'. Available: {sorted(MARKET_COUNTRIES.keys())}",
        )

    # Parse dimensions JSON if provided
    dimension_dict = None
    if dimensions_json:
        try:
            dimension_dict = json.loads(dimensions_json)
        except json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="Invalid dimensions_json — must be valid JSON")

    # Parse evaluation criteria
    evaluation_criteria: list[str] = []
    if evaluation_criteria_json:
        try:
            evaluation_criteria = json.loads(evaluation_criteria_json)
            if not isinstance(evaluation_criteria, list):
                evaluation_criteria = []
        except json.JSONDecodeError:
            pass

    # Generate a stable task_id early so file uploads go into the right folder
    task_id_prefix = uuid.uuid4().hex[:8]

    # Save uploaded files
    saved_files = []
    for f in files:
        if f.filename:  # skip empty slots
            saved_files.append(_save_upload(f, task_id_prefix))

    # Build effective content string
    effective_content = content.strip()

    # --- Process image files ---
    image_descriptions = []
    image_data_urls = []  # for per_persona vision mode

    for sf in saved_files:
        if sf.get("file_type") == "image":
            if vision_mode == "per_persona":
                # Store base64 data URL for per-persona vision (each LLM call gets the image)
                img_bytes = Path(sf["path"]).read_bytes()
                b64 = base64.b64encode(img_bytes).decode("utf-8")
                suffix = Path(sf["path"]).suffix.lower().lstrip(".")
                mime_map = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                            "webp": "image/webp", "gif": "image/gif"}
                mime = mime_map.get(suffix, "image/jpeg")
                image_data_urls.append(f"data:{mime};base64,{b64}")
            else:
                # Summary mode: one-time system description via GLM-4.6V
                desc = await _describe_image_glm(sf["path"])
                if desc:
                    image_descriptions.append(
                        f"[Image Description — {sf['original_name']}] {desc}"
                    )
                sf["image_description"] = desc

    # Append extracted file text to content
    extracted_texts = []
    for sf in saved_files:
        if sf.get("extracted_text"):
            extracted_texts.append(
                f"--- {sf['original_name']} ---\n{sf['extracted_text']}"
            )

    if image_descriptions:
        extracted_texts.extend(image_descriptions)

    if extracted_texts:
        if effective_content:
            effective_content += "\n\n[Attached file content:]\n" + "\n\n".join(extracted_texts)
        else:
            effective_content = "[Attached file content:]\n" + "\n\n".join(extracted_texts)

    if not effective_content and saved_files:
        names = ", ".join(f["original_name"] for f in saved_files)
        effective_content = f"[Uploaded files: {names}]"

    if not effective_content:
        raise HTTPException(status_code=400, detail="Provide content text or at least one file")

    # Append evaluation instructions to content if criteria are specified
    eval_instructions = _build_eval_instructions(evaluation_criteria, custom_instructions)
    if eval_instructions:
        effective_content += f"\n\n---\nEVALUATION FOCUS:\n{eval_instructions}"

    # Build metadata
    metadata: dict = {}
    if vision_mode == "per_persona" and image_data_urls:
        metadata["vision_mode"] = "per_persona"
        metadata["image_data_urls"] = image_data_urls
    if dimension_dict:
        metadata["dimensions"] = dimension_dict
    if saved_files:
        metadata["attachments"] = [
            {k: v for k, v in sf.items() if k not in ("extracted_text",)}
            for sf in saved_files
        ]
    if evaluation_criteria:
        metadata["evaluation_criteria"] = evaluation_criteria
    if custom_instructions:
        metadata["custom_instructions"] = custom_instructions
    if language and language.strip():
        metadata["language"] = language.strip()

    # Resolve max_retries: use arg if explicit, else fall back to settings
    settings = load_settings()
    resolved_retries = max_retries if max_retries >= 0 else settings.llm.max_retries
    # Use settings concurrency if not explicitly overridden (default form value is 10)
    resolved_concurrency = concurrency if concurrency != 10 else settings.llm.concurrency_limit

    # Resolve LLM profile: use specified profile_name or fall back to active default
    chosen_profile = None
    if profile_name.strip():
        for prof in settings.llm_profiles:
            if prof.name == profile_name.strip():
                chosen_profile = prof
                break
        if chosen_profile is None:
            raise HTTPException(status_code=400, detail=f"LLM profile '{profile_name}' not found")
    if chosen_profile is None:
        chosen_profile = get_active_profile(settings)

    # Vision capability check: block image tasks if profile doesn't support vision
    has_images = any(sf.get("file_type") == "image" for sf in saved_files)
    if has_images and chosen_profile.supports_vision is False:
        raise HTTPException(
            status_code=400,
            detail=(
                "Selected model does not support image understanding. "
                "Please choose a vision-capable model or remove images from the task."
            ),
        )

    # Use settings LLM provider when frontend doesn't specify backend
    resolved_backend = backend.strip() if backend.strip() else chosen_profile.provider

    # Store active profile credentials in metadata so engine can pick them up
    # (engine reads them via task.metadata["llm_profile"])
    if chosen_profile.model or chosen_profile.api_key or chosen_profile.endpoint:
        metadata["llm_profile"] = {
            "name": chosen_profile.name,
            "model": chosen_profile.model,
            "api_key": chosen_profile.api_key,
            "endpoint": chosen_profile.endpoint,
            "provider": chosen_profile.provider,
            "supports_vision": chosen_profile.supports_vision,
        }

    task = ResearchTask(
        task_id=task_id_prefix,
        content=effective_content,
        scenario_context=scenario_context.strip(),
        persona_count=personas_count,
        market=market,
        backend=resolved_backend,
        concurrency=resolved_concurrency,
        max_retries=resolved_retries,
        language=language.strip() or "English",
        research_type=research_type.strip() or "product_purchase",
        metadata=metadata,
    )
    _tasks[task.task_id] = task
    background_tasks.add_task(_run_task_bg, task)

    return {
        "task_id": task.task_id,
        "status": task.status,
        "message": "Task queued",
        "attachments": [
            {k: v for k, v in sf.items() if k not in ("extracted_text",)}
            for sf in saved_files
        ],
    }


# ---------------------------------------------------------------------------
# API: GET /api/tasks, GET /api/tasks/{id}
# ---------------------------------------------------------------------------

@app.get("/api/tasks")
async def list_tasks():
    persisted = {d["task_id"]: d for d in ResearchEngine.list_tasks()}
    result = []
    seen = set()
    for task_id, task in _tasks.items():
        seen.add(task_id)
        result.append(task.model_dump(mode="json"))
    for task_id, d in persisted.items():
        if task_id not in seen:
            result.append(d)
    result.sort(key=lambda x: x.get("created_at", ""), reverse=True)
    return result


@app.get("/api/tasks/{task_id}/persona-states")
async def get_persona_states(task_id: str):
    """Return per-persona execution states + persona summaries for dot-matrix visualization."""
    states = ResearchEngine.load_persona_states(task_id)

    # Enrich states with persona_summary from persisted results (if available)
    result_data = ResearchEngine.load_results(task_id)
    persona_map: dict = {}
    if result_data:
        for r in result_data.get("results", []):
            ps = r.get("persona_summary", {})
            pid = r.get("persona_id") or ps.get("persona_id")
            if pid:
                persona_map[pid] = {**ps,
                    "purchase_intent": r.get("purchase_intent"),
                    "nps_score": r.get("nps_score"),
                    "sentiment_score": r.get("sentiment_score"),
                    "verbatim": r.get("verbatim", ""),
                }

    # Attach persona summary to each state
    for s in states:
        pid = s.get("persona_id")
        if pid and pid in persona_map:
            s["persona"] = persona_map[pid]

    return states


@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    task = _tasks.get(task_id)
    if task is None:
        data = ResearchEngine.load_results(task_id)
        if data is None:
            raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")
        return data

    result: dict = {"task": task.model_dump(mode="json")}
    if task.status == TaskStatus.COMPLETED:
        # Always try to load summary for completed tasks (handles output_path=None edge case)
        persisted = ResearchEngine.load_results(task_id)
        if persisted and persisted.get("summary"):
            result["summary"] = persisted.get("summary", {})
    return result


# ---------------------------------------------------------------------------
# API: POST /api/extract-url
# ---------------------------------------------------------------------------

import re as _re
import socket as _socket
import subprocess as _subprocess
import tempfile as _tempfile

_URL_PATTERN = _re.compile(r'https?://\S+')
_VIDEO_PATTERN = _re.compile(
    r'(youtube\.com/watch|youtu\.be/|youtube\.com/shorts/'
    r'|bilibili\.com/video|b23\.tv/'
    r'|tiktok\.com/|douyin\.com/'
    r'|vimeo\.com/|dailymotion\.com/'
    r'|twitter\.com/.*/status|x\.com/.*/status'
    r'|weibo\.com/.*video)',
    _re.IGNORECASE,
)
_BLOCKED_HOSTS = _re.compile(
    r'^(localhost|127\.|10\.|172\.(1[6-9]|2\d|3[01])\.|192\.168\.|169\.254\.|0\.|::1|\[::1\])',
    _re.IGNORECASE,
)


def _validate_url_safe(url: str) -> None:
    """Block SSRF: reject private/loopback/link-local URLs."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if _BLOCKED_HOSTS.search(host):
        raise HTTPException(status_code=400, detail="URLs pointing to internal/private networks are not allowed")
    # Resolve DNS and check IP
    try:
        ip = _socket.gethostbyname(host)
        import ipaddress
        addr = ipaddress.ip_address(ip)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise HTTPException(status_code=400, detail="URL resolves to a private/reserved IP address")
    except _socket.gaierror:
        raise HTTPException(status_code=400, detail=f"Cannot resolve hostname: {host}")


class ExtractUrlRequest(BaseModel):
    url: str


def _is_video_platform(url: str) -> bool:
    return bool(_VIDEO_PATTERN.search(url))


_WHISPER_BIN = "/Users/claire/projects/podcast/cosyvoice-env/bin/whisper"


def _transcribe_video_audio(url: str, tmpdir: str, meta: dict) -> tuple[str, dict]:
    """Download audio via yt-dlp, transcribe via whisper. Returns (text, meta)."""
    import shutil as _shutil2
    audio_path = os.path.join(tmpdir, "audio.m4a")
    try:
        # Download audio only (best audio, m4a format)
        dl_result = _subprocess.run(
            ["yt-dlp", "-x", "--audio-format", "m4a", "-o", audio_path, url],
            capture_output=True, text=True, timeout=300,
        )
        # yt-dlp may rename the file — find whatever audio file was created
        import glob
        audio_files = glob.glob(os.path.join(tmpdir, "audio.*"))
        if not audio_files:
            return "", {**meta, "error": "Failed to download audio"}
        actual_audio = audio_files[0]

        # Transcribe with whisper
        whisper_result = _subprocess.run(
            [_WHISPER_BIN, actual_audio,
             "--model", "medium",
             "--output_format", "txt",
             "--output_dir", tmpdir],
            capture_output=True, text=True, timeout=600,
        )

        # Find output txt file
        txt_files = glob.glob(os.path.join(tmpdir, "*.txt"))
        if not txt_files:
            return "", {**meta, "error": f"Whisper produced no output. stderr: {whisper_result.stderr[:200]}"}

        text = Path(txt_files[0]).read_text(errors="replace").strip()
        meta["transcribed"] = True
        meta["char_count"] = len(text)
        return text, meta

    except FileNotFoundError as e:
        return "", {**meta, "error": f"Missing tool: {e}"}
    except _subprocess.TimeoutExpired:
        return "", {**meta, "error": "Audio transcription timed out (>10min)"}
    except Exception as e:
        return "", {**meta, "error": f"Transcription error: {e}"}


def _extract_video_content(url: str) -> tuple[str, dict]:
    """Extract subtitles (or fallback to title+description) from video via yt-dlp."""
    import glob
    meta = {"source": "video", "url": url}
    tmpdir = _tempfile.mkdtemp(prefix="ws-yt-")
    try:
        # First get video info
        info_result = _subprocess.run(
            ["yt-dlp", "--dump-json", "--no-download", url],
            capture_output=True, text=True, timeout=30,
        )
        if info_result.returncode == 0:
            info = json.loads(info_result.stdout)
            meta["title"] = info.get("title", "")
            meta["duration"] = info.get("duration")
            meta["channel"] = info.get("channel", "")

        # Try to get subtitles: prefer manual subs, fall back to auto-generated
        out_tmpl = os.path.join(tmpdir, "%(id)s")
        for fmt in ("vtt", "srt"):
            _subprocess.run(
                ["yt-dlp", "--write-subs", "--write-auto-subs", "--sub-langs", "zh,en,ja,ko",
                 "--sub-format", fmt, "--skip-download", "-o", out_tmpl, url],
                capture_output=True, text=True, timeout=60,
            )
            sub_files = glob.glob(os.path.join(tmpdir, f"*.{fmt}"))
            if sub_files:
                break
        else:
            sub_files = []

        if not sub_files:
            # No subtitles — fallback to audio download + whisper transcription
            text, meta = _transcribe_video_audio(url, tmpdir, meta)
            if text:
                return text, meta
            return "", {**meta, "error": "No subtitles available and audio transcription failed"}

        # Parse subtitle file — strip timestamps, deduplicate lines
        raw = Path(sub_files[0]).read_text(errors="replace")
        lines = []
        seen = set()
        for line in raw.split("\n"):
            line = line.strip()
            if not line or "-->" in line or line.startswith("WEBVTT") or line.startswith("Kind:") or line.startswith("Language:"):
                continue
            if line.isdigit():
                continue
            clean = _re.sub(r'<[^>]+>', '', line)
            if clean and clean not in seen:
                seen.add(clean)
                lines.append(clean)

        text = " ".join(lines)
        meta["subtitle_lines"] = len(lines)
        return text, meta

    except FileNotFoundError:
        return "", {**meta, "error": "yt-dlp is not installed (required for YouTube extraction)"}
    except _subprocess.TimeoutExpired:
        return "", {**meta, "error": "yt-dlp timed out"}
    except Exception as e:
        return "", {**meta, "error": str(e)}
    finally:
        # Always clean up temp directory
        import shutil as _shutil
        _shutil.rmtree(tmpdir, ignore_errors=True)


def _extract_web_article(url: str) -> tuple[str, dict]:
    """Extract main text content from a web page via trafilatura."""
    meta = {"source": "web", "url": url}
    try:
        import trafilatura
        from trafilatura import bare_extraction
        downloaded = trafilatura.fetch_url(url)
        if not downloaded:
            return "", {**meta, "error": "Failed to fetch URL"}

        result = bare_extraction(downloaded, include_comments=False, include_tables=True)
        if not result or not getattr(result, "text", None):
            return "", {**meta, "error": "No readable content extracted"}

        text = result.text
        meta["title"] = getattr(result, "title", "") or ""
        meta["author"] = getattr(result, "author", "") or ""
        meta["hostname"] = getattr(result, "sitename", "") or ""
        meta["char_count"] = len(text)
        return text, meta

    except ImportError:
        return "", {**meta, "error": "trafilatura is not installed"}
    except Exception as e:
        return "", {**meta, "error": str(e)}


@app.post("/api/extract-url")
async def extract_url(req: ExtractUrlRequest):
    """Extract text content from a URL (web article or YouTube video)."""
    url = req.url.strip()
    if not _URL_PATTERN.match(url):
        raise HTTPException(status_code=400, detail="Invalid URL")

    # SSRF protection: block private/internal URLs
    _validate_url_safe(url)

    import asyncio
    loop = asyncio.get_event_loop()

    if _is_video_platform(url):
        text, meta = await loop.run_in_executor(None, _extract_video_content, url)
    else:
        text, meta = await loop.run_in_executor(None, _extract_web_article, url)

    if not text:
        raise HTTPException(status_code=422, detail=meta.get("error", "Could not extract content"))

    return {"text": text, "metadata": meta}


# ---------------------------------------------------------------------------
# API: POST /api/personas  (still JSON)
# ---------------------------------------------------------------------------

@app.post("/api/personas")
async def preview_personas(req: PersonaPreviewRequest):
    if req.market not in MARKET_COUNTRIES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown market '{req.market}'. Available: {sorted(MARKET_COUNTRIES.keys())}",
        )
    dim_config = None
    if req.dimensions:
        dim_config = DimensionConfig.from_dict(req.dimensions.model_dump())
    gen = PersonaGenerator(market=req.market, dimensions=dim_config)
    personas = gen.generate(min(req.count, 20))

    # Layer 2.5: generate epsilon for preview personas (best-effort, concurrent)
    try:
        backend_name = os.getenv("WS_BACKEND", "openai")
        backend = get_backend(backend_name)
        epsilon_semaphore = asyncio.Semaphore(10)

        async def _gen_epsilon(p):
            async with epsilon_semaphore:
                eps = await generate_epsilon(p.to_dict_summary(), backend)
                p.epsilon = eps

        await asyncio.gather(*[_gen_epsilon(p) for p in personas], return_exceptions=True)
        await backend.close()
    except Exception:
        pass  # epsilon failure never blocks preview

    return [p.to_dict_summary() for p in personas]


# ---------------------------------------------------------------------------
# API: POST /api/prompt-preview
# ---------------------------------------------------------------------------

class PromptPreviewRequest(BaseModel):
    content: str = ""
    scenario_context: str = ""
    market: str = "global"
    research_type: str = "product_purchase"
    language: str = "English"

@app.post("/api/prompt-preview")
async def prompt_preview(req: PromptPreviewRequest):
    """Return the full merged prompt that would be sent to the LLM, using a sample persona."""
    from worldsense.pipeline.output import build_merged_prompt, MERGED_SYSTEM_PROMPT

    if req.market not in MARKET_COUNTRIES:
        raise HTTPException(status_code=400, detail=f"Unknown market '{req.market}'")

    gen = PersonaGenerator(market=req.market, seed=0)
    sample = gen.generate(1)[0]
    summary = {
        **sample.to_dict_summary(),
        "price_sensitivity": sample.cognitive.price_sensitivity,
        "risk_appetite": sample.cognitive.risk_appetite,
        "novelty_seeking": sample.cognitive.novelty_seeking,
        "emotional_reactivity": sample.cognitive.emotional_reactivity,
        "wtp_multiplier": sample.cognitive.wtp_multiplier,
        "personality_type": sample.personality_type,
        "income_bracket": sample.income_bracket,
    }

    user_prompt = build_merged_prompt(
        persona_summary=summary,
        content=req.content or "(no content provided)",
        scenario_context=req.scenario_context,
        language=req.language,
        research_type=req.research_type,
    )

    return {
        "system_prompt": MERGED_SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "sample_persona": {
            "name": sample.name,
            "flag": sample.flag,
            "nationality": sample.nationality,
            "age": sample.age,
            "gender": sample.gender,
            "mbti": sample.mbti,
            "occupation_title": sample.occupation_title,
        },
    }


@app.get("/api/markets")
async def list_markets():
    return sorted(MARKET_COUNTRIES.keys())


@app.get("/api/locations")
async def list_locations(market: str = "global"):
    """
    Return location options for a given market.
    If the market has a single country with city_tiers, returns those tiers.
    Otherwise returns the default urban/suburban/rural fallback.
    """
    from pathlib import Path as _Path
    import json as _json

    data_dir = _Path(__file__).parent.parent.parent / "data"
    cp_path = data_dir / "country_profiles.json"
    country_profiles = _json.loads(cp_path.read_text()) if cp_path.exists() else {}

    market_key = market.lower()
    allowed = MARKET_COUNTRIES.get(market_key)

    DEFAULT_LOCATIONS = [
        {"id": "urban",    "label_en": "Urban",    "weight": 55},
        {"id": "suburban", "label_en": "Suburban",  "weight": 30},
        {"id": "rural",    "label_en": "Rural",     "weight": 15},
    ]

    # Single-country markets get country-specific tiers
    if allowed and len(allowed) == 1:
        country_code = allowed[0]
        cp = country_profiles.get(country_code, {})
        city_tiers = cp.get("city_tiers", [])
        if city_tiers:
            return {
                "market": market_key,
                "country": country_code,
                "has_city_tiers": True,
                "locations": city_tiers,
            }

    # Multi-country or global: return default
    return {
        "market": market_key,
        "country": None,
        "has_city_tiers": False,
        "locations": DEFAULT_LOCATIONS,
    }


@app.get("/api/occupations")
async def list_occupations():
    """Return occupations grouped by category for the UI selector."""
    import json as _json
    from pathlib import Path as _Path

    data_dir = _Path(__file__).parent.parent.parent / "data"
    occ_path = data_dir / "occupations.json"
    if not occ_path.exists():
        return []

    raw = _json.loads(occ_path.read_text())
    if isinstance(raw, list):
        occupations = raw
    elif isinstance(raw, dict) and "occupations" in raw:
        occupations = raw["occupations"]
    else:
        return []

    # Load title translations (contains CN/JP/etc. local names)
    tt_path = data_dir / "title_translations.json"
    title_translations: dict = _json.loads(tt_path.read_text()) if tt_path.exists() else {}

    # Group by category
    groups: dict[str, list] = {}
    for occ in occupations:
        cat = occ.get("category", "other")
        if cat not in groups:
            groups[cat] = []
        occ_id = occ["id"]
        # Merge title_local from translations file (occupations.json has no title_local)
        title_local = {**occ.get("title_local", {}), **title_translations.get(occ_id, {})}
        groups[cat].append({
            "id": occ_id,
            "title": occ.get("title", occ_id),
            "title_local": title_local,
            "category": cat,
            "median_pay_annual_usd": occ.get("median_pay_annual_usd", 0),
        })

    # Return as sorted list of {category, label, items}
    CATEGORY_LABELS = {
        "management": "Management",
        "business-and-financial": "Business & Finance",
        "computer-and-information-technology": "Tech & IT",
        "architecture-and-engineering": "Architecture & Engineering",
        "arts-and-design": "Arts & Design",
        "community-and-social-service": "Community & Social Service",
        "education-training-and-library": "Education & Library",
        "entertainment-and-sports": "Entertainment & Sports",
        "farming-fishing-and-forestry": "Farming & Forestry",
        "food-preparation-and-serving": "Food & Serving",
        "healthcare-practitioners": "Healthcare",
        "healthcare-support": "Healthcare Support",
        "installation-maintenance-and-repair": "Installation & Repair",
        "legal": "Legal",
        "life-physical-and-social-science": "Science",
        "math": "Math & Statistics",
        "media-and-communication": "Media & Communication",
        "production": "Production",
        "protective-service": "Protective Services",
        "sales": "Sales",
        "transportation-and-material-moving": "Transportation",
        "construction-and-extraction": "Construction",
        "government": "Government",
        "other": "Other",
    }

    result = []
    for cat in sorted(groups.keys()):
        result.append({
            "category": cat,
            "label": CATEGORY_LABELS.get(cat, cat.replace("-", " ").title()),
            "items": sorted(groups[cat], key=lambda x: x["title"]),
        })

    return result


# ---------------------------------------------------------------------------
# Settings API
# ---------------------------------------------------------------------------

def _mask_api_key(key: str) -> str:
    """Mask API key for display — show only last 4 chars."""
    if not key:
        return key
    if len(key) > 4:
        return "•" * (len(key) - 4) + key[-4:]
    return key


@app.get("/api/settings")
async def get_settings():
    """Return current system settings (env-var fallbacks shown when settings are empty)."""
    s = load_settings()
    data = s.model_dump()

    llm = data.setdefault("llm", {})

    # Fill empty fields from env vars so the UI reflects what's actually active.
    if not llm.get("model"):
        llm["model"] = os.getenv("WS_MODEL", "")
    if not llm.get("endpoint"):
        llm["endpoint"] = os.getenv("WS_API_BASE_URL", "")
    if not llm.get("api_key"):
        env_key = os.getenv("WS_API_KEY", "")
        llm["api_key"] = _mask_api_key(env_key)
    else:
        llm["api_key"] = _mask_api_key(llm.get("api_key", ""))

    # Mask API keys in profiles for display
    masked_profiles = []
    for p in s.llm_profiles:
        pd = p.model_dump()
        pd["api_key"] = _mask_api_key(pd.get("api_key", ""))
        pd.setdefault("supports_vision", None)
        masked_profiles.append(pd)
    data["llm_profiles"] = masked_profiles

    # Also return active profile details (with masking) for convenience
    active = get_active_profile(s)
    data["active_profile_data"] = {
        "name": active.name,
        "provider": active.provider,
        "model": active.model or os.getenv("WS_MODEL", ""),
        "endpoint": active.endpoint or os.getenv("WS_API_BASE_URL", ""),
        "api_key": _mask_api_key(active.api_key) if active.api_key else _mask_api_key(os.getenv("WS_API_KEY", "")),
        "supports_vision": active.supports_vision,
    }

    return data


class SettingsUpdateRequest(BaseModel):
    general: Optional[dict] = None
    llm: Optional[dict] = None
    advanced: Optional[dict] = None


@app.put("/api/settings")
async def update_settings(req: SettingsUpdateRequest):
    """Update system settings (partial update — only provided sections are changed)."""
    current = load_settings()

    if req.general is not None:
        merged = {**current.general.model_dump(), **req.general}
        current = current.model_copy(update={"general": GeneralSettings.model_validate(merged)})

    if req.llm is not None:
        merged = {**current.llm.model_dump(), **req.llm}
        if merged.get("api_key", "").startswith("•"):
            merged["api_key"] = current.llm.api_key
        current = current.model_copy(update={"llm": LLMSettings.model_validate(merged)})

    if req.advanced is not None:
        merged = {**current.advanced.model_dump(), **req.advanced}
        current = current.model_copy(update={"advanced": AdvancedSettings.model_validate(merged)})

    save_settings(current)
    invalidate_cache()
    return {"ok": True}


# ---------------------------------------------------------------------------
# LLM Profile API
# ---------------------------------------------------------------------------

class ProfileCreateRequest(BaseModel):
    name: str
    provider: str = "openai"
    model: str = ""
    api_key: str = ""
    endpoint: str = ""
    activate: bool = False   # if True, set this as the active profile


class ProfileUpdateRequest(BaseModel):
    name: Optional[str] = None          # rename
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None
    endpoint: Optional[str] = None


@app.get("/api/llm-profiles")
async def list_profiles():
    """List all LLM profiles (API keys masked, supports_vision included)."""
    s = load_settings()
    result = []
    for p in s.llm_profiles:
        pd = p.model_dump()
        pd["api_key"] = _mask_api_key(pd.get("api_key", ""))
        pd["is_active"] = (p.name == s.active_profile) or (
            not s.active_profile and p == s.llm_profiles[0]
        )
        # supports_vision: None = not probed, True/False = probed result
        pd.setdefault("supports_vision", None)
        result.append(pd)
    return {
        "profiles": result,
        "active_profile": s.active_profile or (s.llm_profiles[0].name if s.llm_profiles else ""),
    }


@app.post("/api/llm-profiles")
async def create_profile(req: ProfileCreateRequest):
    """Create a new LLM profile (runs vision probe automatically)."""
    s = load_settings()
    # Name uniqueness check
    if any(p.name == req.name for p in s.llm_profiles):
        raise HTTPException(status_code=409, detail=f"Profile '{req.name}' already exists")

    # Run vision probe (best-effort; never blocks profile creation)
    supports_vision: bool | None = None
    if req.model and req.provider != "mock":
        try:
            supports_vision = await probe_vision(
                provider=req.provider,
                api_key=req.api_key,
                endpoint=req.endpoint,
                model=req.model,
            )
        except Exception:
            supports_vision = None

    new_profile = LLMProfile(
        name=req.name,
        provider=req.provider,
        model=req.model,
        api_key=req.api_key,
        endpoint=req.endpoint,
        supports_vision=supports_vision,
    )
    profiles = list(s.llm_profiles) + [new_profile]
    active = req.name if req.activate or not s.llm_profiles else s.active_profile

    updated = s.model_copy(update={"llm_profiles": profiles, "active_profile": active})
    save_settings(updated)
    invalidate_cache()
    return {"ok": True, "name": req.name, "active_profile": active, "supports_vision": supports_vision}


@app.put("/api/llm-profiles/{profile_name}")
async def update_profile(profile_name: str, req: ProfileUpdateRequest):
    """Update an existing LLM profile (partial update). Re-probes vision if config changes."""
    s = load_settings()
    profiles = list(s.llm_profiles)
    idx = next((i for i, p in enumerate(profiles) if p.name == profile_name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

    p = profiles[idx]
    updates: dict = {}

    new_name = req.name if req.name is not None else p.name
    # Name collision check (if renaming)
    if req.name is not None and req.name != profile_name:
        if any(x.name == req.name for x in profiles):
            raise HTTPException(status_code=409, detail=f"Profile '{req.name}' already exists")
        updates["name"] = req.name

    if req.provider is not None:
        updates["provider"] = req.provider
    if req.model is not None:
        updates["model"] = req.model
    if req.api_key is not None:
        # If masked value sent back, keep original
        if req.api_key.startswith("•"):
            updates["api_key"] = p.api_key
        else:
            updates["api_key"] = req.api_key
    if req.endpoint is not None:
        updates["endpoint"] = req.endpoint

    # Re-run vision probe if any connection-related field changed
    _vision_fields = {"provider", "model", "api_key", "endpoint"}
    should_probe = bool(_vision_fields & set(updates.keys()))
    if should_probe:
        effective_provider = updates.get("provider", p.provider)
        effective_model = updates.get("model", p.model)
        effective_api_key = updates.get("api_key", p.api_key)
        effective_endpoint = updates.get("endpoint", p.endpoint)
        if effective_model and effective_provider != "mock":
            try:
                supports_vision = await probe_vision(
                    provider=effective_provider,
                    api_key=effective_api_key,
                    endpoint=effective_endpoint,
                    model=effective_model,
                )
                updates["supports_vision"] = supports_vision
            except Exception:
                pass  # keep existing supports_vision if probe fails

    profiles[idx] = p.model_copy(update=updates)

    # If renamed, update active_profile reference
    active = s.active_profile
    if req.name is not None and s.active_profile == profile_name:
        active = req.name

    updated = s.model_copy(update={"llm_profiles": profiles, "active_profile": active})
    save_settings(updated)
    invalidate_cache()

    supports_vision = profiles[idx].supports_vision
    return {"ok": True, "supports_vision": supports_vision}


@app.delete("/api/llm-profiles/{profile_name}")
async def delete_profile(profile_name: str):
    """Delete an LLM profile."""
    s = load_settings()
    profiles = [p for p in s.llm_profiles if p.name != profile_name]
    if len(profiles) == len(s.llm_profiles):
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

    # If active profile was deleted, fall back to first remaining
    active = s.active_profile
    if active == profile_name:
        active = profiles[0].name if profiles else ""

    updated = s.model_copy(update={"llm_profiles": profiles, "active_profile": active})
    save_settings(updated)
    invalidate_cache()
    return {"ok": True, "active_profile": active}


@app.post("/api/llm-profiles/{profile_name}/probe-vision")
async def probe_profile_vision(profile_name: str):
    """Manually trigger vision probe for a profile and persist the result."""
    s = load_settings()
    profiles = list(s.llm_profiles)
    idx = next((i for i, p in enumerate(profiles) if p.name == profile_name), None)
    if idx is None:
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")

    p = profiles[idx]
    try:
        supports_vision = await probe_vision(
            provider=p.provider,
            api_key=p.api_key,
            endpoint=p.endpoint,
            model=p.model,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Vision probe failed: {e}")

    profiles[idx] = p.model_copy(update={"supports_vision": supports_vision})
    updated = s.model_copy(update={"llm_profiles": profiles})
    save_settings(updated)
    invalidate_cache()
    return {"ok": True, "supports_vision": supports_vision}


@app.post("/api/llm-profiles/{profile_name}/activate")
async def activate_profile(profile_name: str):
    """Set the active LLM profile."""
    s = load_settings()
    if not any(p.name == profile_name for p in s.llm_profiles):
        raise HTTPException(status_code=404, detail=f"Profile '{profile_name}' not found")
    updated = s.model_copy(update={"active_profile": profile_name})
    save_settings(updated)
    invalidate_cache()
    return {"ok": True, "active_profile": profile_name}


# ---------------------------------------------------------------------------
# Uploaded file serving (for Task Detail inline images / PDF viewer)
# ---------------------------------------------------------------------------

@app.get("/api/uploads/{task_id}/{filename}")
async def serve_upload(task_id: str, filename: str):
    """Serve an uploaded file for a given task."""
    # Sanitize to prevent path traversal
    if ".." in task_id or ".." in filename or "/" in task_id or "/" in filename:
        raise HTTPException(status_code=400, detail="Invalid path")
    path = UPLOAD_DIR / task_id / filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File not found")
    return FileResponse(str(path))


# ---------------------------------------------------------------------------
# Static files
# ---------------------------------------------------------------------------

STATIC_DIR = Path(__file__).parent.parent / "static"
STATIC_DIR.mkdir(exist_ok=True)

app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
