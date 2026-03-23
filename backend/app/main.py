import sys
from pathlib import Path

# Bootstrap project root onto sys.path so `rag` package is always importable
# regardless of whether PYTHONPATH was set before launching uvicorn.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from fastapi import FastAPI, Query, HTTPException
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
from datetime import datetime, timezone, timedelta
from typing import Any

from app.conversation_engine import ConversationEngine
from app.db.models import init_db
from app.utils.tool_formatter import _sanitize_json

app = FastAPI(title="FilmDB Demo")
engine = ConversationEngine()

_LOG_DIR = Path(__file__).resolve().parent.parent.parent / "logs"
_LLM_REPORT_V1 = _LOG_DIR / "llm_report.md"
_LLM_REPORT_V2 = _LOG_DIR / "llm_report_v2.md"
_TOKEN_REPORT  = _LOG_DIR / "token_usage_report.md"


class ChatRequest(BaseModel):
    session_id: str
    user_id: str
    message: str


@app.on_event("startup")
def startup() -> None:
    import os, logging, threading
    log = logging.getLogger(__name__)
    log.info("="*60)
    log.info(" FilmDB Backend starting — PID %s", os.getpid())
    log.info("="*60)
    init_db()
    
    def _eager_load_task():
        log.info("Eager-loading heavy models in BACKGROUND thread (PID %s) ...", os.getpid())
        try:
            from rag.engine.filmdb_query_engine import FilmDBQueryEngine
            FilmDBQueryEngine.get_instance()
            log.info("  FilmDBQueryEngine background load complete.")

            from app.services.rag.embedding_service import EmbeddingService
            from app.intent.domain_classifier import DomainClassifier

            log.info("  Eager-loading EmbeddingService (BGE-base) in background …")
            EmbeddingService.get_instance().model

            log.info("  Eager-loading DomainClassifier centroids in background …")
            DomainClassifier.get_instance()

            log.info("  All heavy models loaded (PID %s).", os.getpid())
        except Exception:
            log.exception("Background eager-load failed")

    # Launch model loading in background so server starts instantly
    threading.Thread(target=_eager_load_task, daemon=True).start()
    log.info("Startup complete (models loading in background). READY in <1s.")


@app.get("/health")
def health():
    """Health check — also shows whether heavy singletons are loaded."""
    from app.services.rag.embedding_service import EmbeddingService
    from app.intent.domain_classifier import DomainClassifier
    import os
    emb = EmbeddingService._instance
    dc  = DomainClassifier._instance
    return {
        "status": "ok",
        "pid": os.getpid(),
        "embedding_model_loaded": emb is not None and emb._model is not None,
        "domain_classifier_loaded": dc is not None,
        "embedding_model_name": EmbeddingService.MODEL_NAME,
    }


@app.post("/chat")
async def chat(request: ChatRequest):
    result = await engine.run(request.session_id, request.user_id, request.message)
    return _sanitize_json(result)


# ── Log Retrieval Endpoints ────────────────────────────────────────────────


def _parse_llm_report(days: int) -> list[dict[str, Any]]:
    """Parse llm_report.md and llm_report_v2.md and return entries from the last N days as structured dicts."""
    content = ""
    if _LLM_REPORT_V1.exists():
        content += _LLM_REPORT_V1.read_text(encoding="utf-8") + "\n"
    if _LLM_REPORT_V2.exists():
        content += _LLM_REPORT_V2.read_text(encoding="utf-8") + "\n"

    if not content.strip():
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    blocks = content.split("## Run - ")

    entries: list[dict[str, Any]] = []
    for block in blocks[1:]:
        lines = block.strip().splitlines()
        header = lines[0].strip()
        try:
            ts = datetime.strptime(header, "%Y-%m-%d %H:%M:%S UTC").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if ts < cutoff:
            continue

        # Parse key fields from the markdown block
        entry: dict[str, Any] = {"timestamp": header, "raw": "## Run - " + block}
        for line in lines[1:]:
            line = line.strip()
            if line.startswith("- **Query**:"):
                entry["query"] = line.split("**Query**:")[-1].strip().strip('"')
            elif line.startswith("- **Total Time**:"):
                entry["total_time_ms"] = line.split("**Total Time**:")[-1].strip()
            elif line.startswith("- **Total LLM Calls**:"):
                entry["llm_calls"] = line.split("**Total LLM Calls**:")[-1].strip()
            elif line.startswith("- **Primary**:"):
                entry["intent"] = line.split("**Primary**:")[-1].strip()
            elif line.startswith("- **Entities**:"):
                entry["entities"] = line.split("**Entities**:")[-1].strip()
            elif line.startswith("- **Domain/Category**:"):
                entry["domain"] = line.split("**Domain/Category**:")[-1].strip()
            elif line.startswith("- Prompt (Reading):"):
                entry["prompt_tokens"] = line.split("Prompt (Reading):")[-1].strip()
            elif line.startswith("- Completion (Writing):"):
                entry["completion_tokens"] = line.split("Completion (Writing):")[-1].strip()
            elif line.startswith("Response Mode:"):
                entry["response_mode"] = line.split("Response Mode:")[-1].strip()

        entries.append(entry)

    return entries


@app.get("/logs/llm-report")
def get_llm_report(
    days: int = Query(default=3, ge=1, le=30, description="Number of days to look back"),
    raw: bool = Query(default=False, description="Return raw markdown instead of JSON"),
):
    """
    Retrieve LLM report entries from the last N days.

    - **days**: look-back window (1–30, default 3)
    - **raw**: if true, returns the matched blocks as plain markdown text
    """
    if not _LLM_REPORT_V1.exists() and not _LLM_REPORT_V2.exists():
        raise HTTPException(status_code=404, detail="No LLM reports found.")

    entries = _parse_llm_report(days)

    if raw:
        md = f"# LLM Report — Last {days} Days\n\nEntries: {len(entries)}\n\n"
        md += "\n---\n".join(e["raw"] for e in entries)
        return PlainTextResponse(content=md, media_type="text/markdown")

    return {
        "days": days,
        "entry_count": len(entries),
        "cutoff": (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S UTC"),
        "entries": [{k: v for k, v in e.items() if k != "raw"} for e in entries],
    }


@app.get("/logs/token-usage", response_class=PlainTextResponse)
def get_token_usage():
    """Return the current token usage report as markdown."""
    if not _TOKEN_REPORT.exists():
        raise HTTPException(status_code=404, detail="token_usage_report.md not found")
    return PlainTextResponse(
        content=_TOKEN_REPORT.read_text(encoding="utf-8"),
        media_type="text/markdown",
    )
