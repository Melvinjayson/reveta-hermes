"""Aura Projects: named groups of conversations, stored in the profile's projects.db.

The project rows are Hermes's own (hermes_cli/projects_db.py), so Desktop sees the same
projects. Which conversations belong to a project is Aura's addition: one membership
table in the same database, created here without touching the core schema. A
conversation belongs to at most one Aura project. Deleting a project never deletes
its conversations.
"""

from __future__ import annotations

import sqlite3
import time

MEMBERSHIP_SQL = """
CREATE TABLE IF NOT EXISTS aura_project_sessions (
    session_id  TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    added_at    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_aura_project_sessions_project ON aura_project_sessions(project_id);
"""

MAX_NAME = 80
MAX_DESCRIPTION = 2000


def _connect() -> sqlite3.Connection:
    from hermes_cli.projects_db import connect

    conn = connect()
    conn.executescript(MEMBERSHIP_SQL)
    return conn


def _clean_name(name: str) -> str:
    text = " ".join(str(name or "").split())
    if not text:
        raise ValueError("A project needs a name.")
    if len(text) > MAX_NAME:
        raise ValueError(f"Project names are limited to {MAX_NAME} characters.")
    return text


def _clean_description(description: str | None) -> str | None:
    text = str(description or "").strip()
    if len(text) > MAX_DESCRIPTION:
        raise ValueError(f"Descriptions are limited to {MAX_DESCRIPTION} characters.")
    return text or None


def _payload(conn: sqlite3.Connection) -> dict:
    from hermes_cli.projects_db import list_projects

    members: dict[str, list[str]] = {}
    for row in conn.execute("SELECT project_id, session_id FROM aura_project_sessions ORDER BY added_at DESC"):
        members.setdefault(row["project_id"], []).append(row["session_id"])
    return {
        "projects": [
            {"id": p.id, "slug": p.slug, "name": p.name, "description": p.description or "",
             "created_at": p.created_at, "session_ids": members.get(p.id, [])}
            for p in list_projects(conn)
        ]
    }


def _require(conn: sqlite3.Connection, project_id: str):
    from hermes_cli.projects_db import get_project

    project = get_project(conn, project_id)
    if project is None or project.archived:
        raise LookupError("Project not found.")
    return project


def _with_conn(action):
    conn = _connect()
    try:
        return action(conn)
    finally:
        conn.close()


def list_all() -> dict:
    return _with_conn(_payload)


def create(name: str, description: str | None = None) -> dict:
    from hermes_cli.projects_db import create_project

    def run(conn):
        create_project(conn, name=_clean_name(name), description=_clean_description(description))
        return _payload(conn)

    return _with_conn(run)


def update(project_id: str, name: str | None = None, description: str | None = None) -> dict:
    from hermes_cli.projects_db import update_project

    def run(conn):
        _require(conn, project_id)
        update_project(conn, project_id,
                       name=_clean_name(name) if name is not None else None,
                       description=(_clean_description(description) or "") if description is not None else None)
        return _payload(conn)

    return _with_conn(run)


def remove(project_id: str) -> dict:
    """Delete the project and its memberships; its conversations stay in history."""
    from hermes_cli.projects_db import delete_project
    from hermes_cli.sqlite_util import write_txn

    def run(conn):
        _require(conn, project_id)
        with write_txn(conn):
            conn.execute("DELETE FROM aura_project_sessions WHERE project_id = ?", (project_id,))
        delete_project(conn, project_id)
        return _payload(conn)

    return _with_conn(run)


def assign(session_id: str, project_id: str | None) -> dict:
    """Put a conversation in a project (moving it from any other), or take it out with None."""
    from hermes_cli.sqlite_util import write_txn

    session = str(session_id or "").strip()
    if not session or len(session) > 200:
        raise ValueError("A conversation id is required.")

    def run(conn):
        if project_id is not None:
            _require(conn, project_id)
        with write_txn(conn):
            conn.execute("DELETE FROM aura_project_sessions WHERE session_id = ?", (session,))
            if project_id is not None:
                conn.execute(
                    "INSERT INTO aura_project_sessions (session_id, project_id, added_at) VALUES (?, ?, ?)",
                    (session, project_id, int(time.time())),
                )
        return _payload(conn)

    return _with_conn(run)
