import hashlib
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5


class Conflict(Exception):
    pass


class Journal:
    """SQLite holds raw evidence, a durable queue and audit, never semantic/vector memory."""

    def __init__(self, directory: Path, scope: str):
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "journal.sqlite3"
        self.scope = scope
        with self.db() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS episodes(
                  id TEXT PRIMARY KEY, payload TEXT NOT NULL, fingerprint TEXT NOT NULL,
                  deleted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS jobs(
                  episode_id TEXT PRIMARY KEY, status TEXT NOT NULL DEFAULT 'pending',
                  attempts INTEGER NOT NULL DEFAULT 0, available REAL NOT NULL DEFAULT 0,
                  lease REAL NOT NULL DEFAULT 0, error TEXT);
                CREATE TABLE IF NOT EXISTS audit(
                  id INTEGER PRIMARY KEY, time REAL NOT NULL, actor TEXT NOT NULL,
                  action TEXT NOT NULL, target TEXT NOT NULL);
            """)
            row = db.execute("SELECT value FROM metadata WHERE key='scope'").fetchone()
            if row and row[0] != scope:
                raise ValueError("data directory belongs to a different memory scope")
            db.execute("INSERT OR IGNORE INTO metadata VALUES('scope',?)", (scope,))

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=30)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def ingest(self, message, actor):
        payload = message.model_dump(mode="json")
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(encoded.encode()).hexdigest()
        identity = json.dumps(
            [
                self.scope,
                payload["source_system"],
                payload["conversation_id"],
                payload["message_id"],
            ]
        )
        episode_id = str(uuid5(NAMESPACE_URL, identity))
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM episodes WHERE id=?", (episode_id,)).fetchone()
            if row:
                if row["deleted"]:
                    raise Conflict("source was deleted; use a new source message_id to reimport")
                if row["fingerprint"] != fingerprint:
                    raise Conflict("same source message_id has different payload")
                return episode_id, True
            db.execute(
                "INSERT INTO episodes(id,payload,fingerprint) VALUES(?,?,?)",
                (episode_id, encoded, fingerprint),
            )
            db.execute("INSERT INTO jobs(episode_id) VALUES(?)", (episode_id,))
            self.audit(actor, "ingest", episode_id, db)
        return episode_id, False

    def get(self, episode_id):
        with self.db() as db:
            row = db.execute(
                "SELECT * FROM episodes WHERE id=? AND deleted=0", (episode_id,)
            ).fetchone()
        return json.loads(row["payload"]) if row else None

    def claim(self):
        now = time.time()
        with self.db() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                """SELECT * FROM jobs WHERE
              (status='pending' AND available<=?) OR (status='running' AND lease<?)
              ORDER BY available, rowid LIMIT 1""",
                (now, now),
            ).fetchone()
            if not row:
                return None
            db.execute(
                "UPDATE jobs SET status='running', attempts=attempts+1, lease=? WHERE episode_id=?",
                (now + 1800, row["episode_id"]),
            )
        return row["episode_id"]

    def finish(self, episode_id, error=None):
        with self.db() as db:
            row = db.execute(
                "SELECT attempts FROM jobs WHERE episode_id=?", (episode_id,)
            ).fetchone()
            attempts = row[0]
            status = "done" if error is None else "failed" if attempts >= 3 else "pending"
            db.execute(
                "UPDATE jobs SET status=?,error=?,available=?,lease=0 WHERE episode_id=?",
                (status, error, time.time() + 2**attempts, episode_id),
            )

    def jobs(self):
        with self.db() as db:
            return [dict(r) for r in db.execute("SELECT * FROM jobs ORDER BY rowid DESC LIMIT 100")]

    def live_episodes(self):
        with self.db() as db:
            return [
                (r["id"], json.loads(r["payload"]))
                for r in db.execute("SELECT * FROM episodes WHERE deleted=0 ORDER BY rowid")
            ]

    def retry(self, episode_id, actor):
        with self.db() as db:
            count = db.execute(
                "UPDATE jobs SET status='pending',attempts=0,available=0,error=NULL "
                "WHERE episode_id=? AND status='failed'",
                (episode_id,),
            ).rowcount
            if count:
                self.audit(actor, "retry", episode_id, db)
        return bool(count)

    def erase(self, episode_id, actor):
        with self.db() as db:
            db.execute("PRAGMA secure_delete=ON")
            db.execute("UPDATE episodes SET deleted=1,payload='{}' WHERE id=?", (episode_id,))
            db.execute("DELETE FROM jobs WHERE episode_id=?", (episode_id,))
            self.audit(actor, "erase", episode_id, db)
        # Online copies/backups must be handled by the runbook; this is logical live deletion.

    def audit(self, actor, action, target, db=None):
        if db is not None:
            db.execute(
                "INSERT INTO audit(time,actor,action,target) VALUES(?,?,?,?)",
                (time.time(), actor, action, target),
            )
        else:
            with self.db() as connection:
                self.audit(actor, action, target, connection)
