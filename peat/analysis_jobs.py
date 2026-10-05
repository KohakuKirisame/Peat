"""User-owned background analysis jobs, independent of browser connections."""

import asyncio
import json
import uuid

from fastapi import HTTPException

from .brokers import ProviderError
from .db import Database, now

ACTIVE = ("queued", "running", "cancelling")


class AnalysisJobs:
    def __init__(self, db: Database, intelligence):
        self.db, self.intelligence = db, intelligence
        self.tasks: dict[str, asyncio.Task] = {}
        self.stopping = False

    def recover(self):
        self.db.execute(
            "UPDATE analysis_jobs SET status='interrupted',phase='finished',error='analysis_interrupted',"
            "updated_at=?,finished_at=? WHERE status IN ('queued','running','cancelling')",
            (now(), now()),
        )

    @staticmethod
    def public(row):
        if not row:
            return None
        settings = json.loads(row["settings"])
        return {
            key: row[key]
            for key in (
                "id",
                "status",
                "phase",
                "error",
                "analysis_id",
                "created_at",
                "updated_at",
                "finished_at",
            )
        } | {
            "provider": settings["ai_provider"],
            "model": settings["ai_model"],
            "reasoning_effort": settings["reasoning_effort"],
            "style": settings["style"],
        }

    def get(self, uid, job_id):
        row = self.db.one("SELECT * FROM analysis_jobs WHERE id=? AND user_id=?", (job_id, uid))
        if not row:
            raise HTTPException(404, "analysis_job_not_found")
        return self.public(row)

    def current(self, uid):
        return self.public(
            self.db.one(
                "SELECT * FROM analysis_jobs WHERE user_id=? "
                "ORDER BY (status IN ('queued','running','cancelling')) DESC,rowid DESC LIMIT 1",
                (uid,),
            )
        )

    def start(self, uid):
        settings = self.db.settings(uid)
        if not settings["ai_model"]:
            raise ProviderError("model_required")
        if self.stopping:
            raise HTTPException(503, "server_stopping")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            active = conn.execute(
                "SELECT * FROM analysis_jobs WHERE user_id=? AND status IN ('queued','running','cancelling')",
                (uid,),
            ).fetchone()
            if active:
                return self.public(dict(active))
            job_id, created = uuid.uuid4().hex, now()
            conn.execute(
                "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,created_at,updated_at) "
                "VALUES(?,?,'queued','queued',?,?,?)",
                (job_id, uid, json.dumps(settings), created, created),
            )
        task = asyncio.create_task(self._work(uid, job_id, settings), name=f"peat-analysis-{job_id}")
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))
        return self.get(uid, job_id)

    async def _work(self, uid, job_id, settings):
        def phase(value):
            self.db.execute(
                "UPDATE analysis_jobs SET status='running',phase=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
                (value, now(), job_id),
            )

        try:
            phase("preparing")
            result = await self.intelligence.analyze(uid, settings=settings, progress=phase)
            self.db.execute(
                "UPDATE analysis_jobs SET status='completed',phase='finished',analysis_id=?,updated_at=?,finished_at=? WHERE id=?",
                (result["id"], now(), now(), job_id),
            )
        except asyncio.CancelledError:
            status = "interrupted" if self.stopping else "cancelled"
            self.db.execute(
                "UPDATE analysis_jobs SET status=?,phase='finished',error=?,updated_at=?,finished_at=? WHERE id=?",
                (status, "analysis_interrupted" if self.stopping else None, now(), now(), job_id),
            )
        except Exception as exc:
            # Persist only controlled error codes, never upstream responses or credentials.
            code = (
                exc.code
                if isinstance(exc, ProviderError)
                else (
                    exc.detail
                    if isinstance(exc, HTTPException) and isinstance(exc.detail, str)
                    else "analysis_failed"
                )
            )
            self.db.execute(
                "UPDATE analysis_jobs SET status='failed',phase='finished',error=?,updated_at=?,finished_at=? WHERE id=?",
                (code, now(), now(), job_id),
            )

    def cancel(self, uid, job_id):
        job = self.get(uid, job_id)
        if job["status"] not in ACTIVE or job["status"] == "cancelling":
            return job
        task = self.tasks.get(job_id)
        if not task:
            self.db.execute(
                "UPDATE analysis_jobs SET status='interrupted',phase='finished',error='analysis_interrupted',"
                "updated_at=?,finished_at=? WHERE id=?",
                (now(), now(), job_id),
            )
        elif job["status"] == "queued":
            # A task cancelled before its coroutine starts cannot run its cleanup handler.
            self.db.execute(
                "UPDATE analysis_jobs SET status='cancelled',phase='finished',updated_at=?,finished_at=? WHERE id=?",
                (now(), now(), job_id),
            )
            task.cancel()
        else:
            self.db.execute(
                "UPDATE analysis_jobs SET status='cancelling',updated_at=? WHERE id=?", (now(), job_id)
            )
            task.cancel()
        return self.get(uid, job_id)

    async def shutdown(self):
        self.stopping = True
        tasks = list(self.tasks.values())
        for task in tasks:
            if not task.cancelling():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        self.recover()
