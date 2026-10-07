"""Owner-scoped report deletion and retention, including discussion evidence."""

import json

from fastapi import HTTPException

from .db import now

ACTIVE = ("queued", "running", "cancelling")
DELETED_SETTINGS = json.dumps(
    {"ai_provider": "", "ai_model": "", "reasoning_effort": "auto", "style": "", "holding_horizon": None}
)


class Reports:
    def __init__(self, db):
        self.db = db

    def create(self, uid, provider, model, style, content, evidence, created):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            maximum = conn.execute(
                "SELECT MAX(COALESCE((SELECT MAX(id) FROM analyses),0),value) AS n FROM counters WHERE name='analyses'"
            ).fetchone()["n"]
            report_id = maximum + 1
            conn.execute("UPDATE counters SET value=? WHERE name='analyses'", (report_id,))
            conn.execute(
                "INSERT INTO analyses(id,user_id,provider,model,style,content,evidence,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                (report_id, uid, provider, model, style, content, json.dumps(evidence), created, created),
            )
            return report_id

    def storage(self, uid):
        return {
            "count": self.db.one("SELECT COUNT(*) AS n FROM analyses WHERE user_id=?", (uid,))["n"],
            "limit": self.db.settings(uid)["analysis_limit"],
        }

    @staticmethod
    def _remove(conn, uid, ids):
        if not ids:
            return
        placeholders = ",".join("?" for _ in ids)
        conn.execute(
            "UPDATE counters SET value=MAX(value,COALESCE((SELECT MAX(id) FROM analyses),0)) WHERE name='analyses'"
        )
        # A minimal tombstone prevents an older completed task from resurfacing in the global banner.
        # Prompts/settings and all report/discussion content are removed.
        conn.execute(
            f"UPDATE analysis_jobs SET status='deleted',phase='finished',settings=?,error=NULL,updated_at=? "
            f"WHERE user_id=? AND analysis_id IN ({placeholders})",
            (DELETED_SETTINGS, now(), uid, *ids),
        )
        conn.execute(f"DELETE FROM analyses WHERE user_id=? AND id IN ({placeholders})", (uid, *ids))

    def delete(self, uid, report_id):
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not conn.execute(
                "SELECT id FROM analyses WHERE id=? AND user_id=?", (report_id, uid)
            ).fetchone():
                raise HTTPException(404, "analysis_not_found")
            if conn.execute(
                "SELECT id FROM analysis_jobs WHERE user_id=? AND analysis_id=? AND status IN ('queued','running','cancelling')",
                (uid, report_id),
            ).fetchone():
                raise HTTPException(409, "report_in_use")
            self._remove(conn, uid, [report_id])

    def prune(self, uid, *, limit=None, conn=None, protected=()):
        limit = self.db.settings(uid)["analysis_limit"] if limit is None else limit
        if not limit:
            return 0
        if conn is None:
            with self.db.connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                return self.prune(uid, limit=limit, conn=connection, protected=protected)
        active = {
            row["analysis_id"]
            for row in conn.execute(
                "SELECT analysis_id FROM analysis_jobs WHERE user_id=? AND status IN ('queued','running','cancelling') AND analysis_id IS NOT NULL",
                (uid,),
            )
        }
        keep = set(protected) | active
        rows = conn.execute(
            "SELECT id FROM analyses WHERE user_id=? ORDER BY COALESCE(updated_at,created_at) DESC,id DESC",
            (uid,),
        ).fetchall()
        ordered = [row["id"] for row in rows if row["id"] in keep] + [
            row["id"] for row in rows if row["id"] not in keep
        ]
        remove = ordered[max(limit, len(keep)) :]
        self._remove(conn, uid, remove)
        return len(remove)
