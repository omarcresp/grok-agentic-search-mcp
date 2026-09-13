"""Bounded, private local checkpoints. Each write is atomic; IDs cannot be paths."""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from .models import RunRecord, now


class ResearchStore:
    def __init__(self, directory: Path | None = None):
        self.directory = directory or Path(
            os.getenv("GROK_SEARCH_DATA_DIR", str(Path.home() / ".cache" / "grok-search-mcp"))
        )
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)

    def path(self, research_id: str) -> Path:
        try:
            if str(UUID(research_id)) != research_id:
                raise ValueError
        except ValueError as exc:
            raise ValueError("Invalid research ID") from exc
        return self.directory / f"{research_id}.json"

    def save(self, record: RunRecord) -> None:
        record.updated_at = now()
        target = self.path(record.output.research_id)
        fd, name = tempfile.mkstemp(dir=self.directory, suffix=".tmp")
        try:
            with os.fdopen(fd, "w") as handle:
                handle.write(record.model_dump_json())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    def load(self, research_id: str) -> RunRecord:
        path = self.path(research_id)
        if not path.exists():
            raise ValueError("Research not found or expired")
        record = RunRecord.model_validate_json(path.read_text())
        active = record.output.status in ("running", "queued") and owner_alive(record)
        if not active and datetime.fromisoformat(record.updated_at) < datetime.now(
            timezone.utc
        ) - timedelta(days=7):
            path.unlink(missing_ok=True)
            raise ValueError("Research not found or expired")
        return record

    def prune(self, retention_days: int = 7) -> None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        for path in self.directory.glob("*.json"):
            try:
                record = RunRecord.model_validate_json(path.read_text())
                active = record.output.status in ("running", "queued") and owner_alive(record)
                if not active and datetime.fromisoformat(record.updated_at) < cutoff:
                    path.unlink()
            except (ValueError, OSError, json.JSONDecodeError):
                continue


def owner_alive(record: RunRecord) -> bool:
    if record.owner_pid <= 0:
        return False
    try:
        os.kill(record.owner_pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
