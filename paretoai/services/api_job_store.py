"""
API 任务队列（极简版）

- 仅用于展示“后台异步提交”的 API 任务状态（例如 edit-and-regenerate）
- 进程内内存存储：重启后清空
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from threading import Lock
from typing import Dict, List, Optional
import uuid


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ApiJob:
    id: str
    table_id: str
    kind: str  # e.g. edit_and_regenerate
    status: str  # queued | running | succeeded | failed
    created_at: str
    updated_at: str
    record_id: Optional[str] = None
    project_id: Optional[str] = None
    segment_index: Optional[int] = None
    message: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict:
        return asdict(self)


class ApiJobStore:
    def __init__(self, max_items: int = 200):
        self._lock = Lock()
        self._jobs: Dict[str, ApiJob] = {}
        self._order: List[str] = []  # newest first
        self._max_items = max_items

    def create_job(
        self,
        *,
        table_id: str,
        kind: str,
        record_id: Optional[str] = None,
        project_id: Optional[str] = None,
        segment_index: Optional[int] = None,
        message: Optional[str] = None,
    ) -> ApiJob:
        job_id = uuid.uuid4().hex
        now = _now_iso()
        job = ApiJob(
            id=job_id,
            table_id=table_id,
            kind=kind,
            status="queued",
            created_at=now,
            updated_at=now,
            record_id=record_id,
            project_id=project_id,
            segment_index=segment_index,
            message=message,
        )

        with self._lock:
            self._jobs[job_id] = job
            self._order.insert(0, job_id)
            # prune
            if len(self._order) > self._max_items:
                for old_id in self._order[self._max_items :]:
                    self._jobs.pop(old_id, None)
                self._order = self._order[: self._max_items]
        return job

    def update_job(
        self,
        job_id: str,
        *,
        status: Optional[str] = None,
        message: Optional[str] = None,
        error: Optional[str] = None,
    ) -> Optional[ApiJob]:
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return None
            if status is not None:
                job.status = status
            if message is not None:
                job.message = message
            if error is not None:
                job.error = error
            job.updated_at = _now_iso()
            return job

    def list_jobs(self, *, table_id: str, limit: int = 50) -> List[Dict]:
        with self._lock:
            out: List[Dict] = []
            for job_id in self._order:
                job = self._jobs.get(job_id)
                if not job or job.table_id != table_id:
                    continue
                out.append(job.to_dict())
                if len(out) >= max(1, min(limit, 200)):
                    break
            return out


_global_store: Optional[ApiJobStore] = None


def get_api_job_store() -> ApiJobStore:
    global _global_store
    if _global_store is None:
        _global_store = ApiJobStore()
    return _global_store

