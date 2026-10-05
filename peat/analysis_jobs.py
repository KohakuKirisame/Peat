"""User-owned background analysis jobs, independent of browser connections."""

import asyncio
import json
import uuid

from fastapi import HTTPException

from .brokers import ProviderError
from .db import Database, now
from .followups import Followups

ACTIVE = ("queued", "running", "cancelling")


class AnalysisJobs:
    def __init__(self, db: Database, intelligence):
        self.db, self.intelligence = db, intelligence
        self.followups = Followups(db, intelligence)
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
                "kind",
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
            "holding_horizon": settings.get("holding_horizon"),
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

    def start(self, uid, followup=None):
        settings = self.db.settings(uid)
        kind, report_id, turn_id = "analysis", None, None
        if followup:
            report = self.followups.report(uid, followup["analysis_id"])
            kind, report_id = "followup", report["id"]
            settings |= {
                "ai_provider": followup.get("provider") or report["provider"],
                "ai_model": followup.get("model") if followup.get("model") is not None else report["model"],
                "reasoning_effort": followup.get("reasoning_effort") or report["reasoning_effort"],
                "style": report["style"],
                "holding_horizon": report["holding_horizon"],
            }
            if not followup["question"].strip():
                raise HTTPException(422, "question_required")
        if not settings["ai_model"]:
            raise ProviderError("model_required")
        if self.stopping:
            raise HTTPException(503, "server_stopping")
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if followup:
                previous = conn.execute(
                    "SELECT j.*,f.question FROM analysis_followups f JOIN analysis_jobs j ON j.id=f.job_id "
                    "WHERE f.analysis_id=? AND f.request_key=? AND j.user_id=?",
                    (report_id, followup["request_id"], uid),
                ).fetchone()
                if previous:
                    saved = json.loads(previous["settings"])
                    if previous["question"] != followup["question"].strip() or any(
                        saved[key] != settings[key] for key in ("ai_provider", "ai_model", "reasoning_effort")
                    ):
                        raise HTTPException(409, "followup_request_conflict")
                    return self.public(dict(previous))
            active = conn.execute(
                "SELECT * FROM analysis_jobs WHERE user_id=? AND status IN ('queued','running','cancelling')",
                (uid,),
            ).fetchone()
            if active:
                if kind == "followup" or active["kind"] == "followup":
                    raise HTTPException(409, "analysis_running")
                return self.public(dict(active))
            job_id, created = uuid.uuid4().hex, now()
            conn.execute(
                "INSERT INTO analysis_jobs(id,user_id,status,phase,settings,created_at,updated_at,kind,analysis_id) "
                "VALUES(?,?,'queued','queued',?,?,?,?,?)",
                (job_id, uid, json.dumps(settings), created, created, kind, report_id),
            )
            if followup:
                turn_id = conn.execute(
                    "INSERT INTO analysis_followups(analysis_id,job_id,request_key,question,created_at) VALUES(?,?,?,?,?)",
                    (report_id, job_id, followup["request_id"], followup["question"].strip(), created),
                ).lastrowid
        task = asyncio.create_task(self._work(uid, job_id, settings, turn_id), name=f"peat-analysis-{job_id}")
        self.tasks[job_id] = task
        task.add_done_callback(lambda _: self.tasks.pop(job_id, None))
        return self.get(uid, job_id)

    async def _work(self, uid, job_id, settings, turn_id=None):
        def phase(value):
            self.db.execute(
                "UPDATE analysis_jobs SET status='running',phase=?,updated_at=? WHERE id=? AND status IN ('queued','running')",
                (value, now(), job_id),
            )

        try:
            phase("preparing")
            result = (
                await self.followups.answer(uid, turn_id, settings, progress=phase)
                if turn_id
                else await self.intelligence.analyze(uid, settings=settings, progress=phase)
            )
            with self.db.connect() as conn:
                if turn_id:
                    conn.execute(
                        "UPDATE analysis_followups SET answer=?,answered_at=? WHERE id=?",
                        (result["content"], now(), turn_id),
                    )
                conn.execute(
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
