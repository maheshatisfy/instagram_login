"""Saved Unified Login tokens. The browser session only remembers which account is open."""

import json
import os
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "connections.sqlite")


def _connect():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS accounts (
            ig_id TEXT PRIMARY KEY,
            username TEXT,
            access_token TEXT NOT NULL,
            client_business_id TEXT,
            profile_json TEXT,
            media_json TEXT,
            media_after TEXT,
            media_error TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )
    return connection


def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def save_login(accounts, access_token, client_business_id):
    saved_at = _now()
    with _connect() as connection:
        for account in accounts:
            connection.execute(
                """
                INSERT INTO accounts (
                    ig_id, username, access_token, client_business_id, updated_at
                )
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(ig_id) DO UPDATE SET
                    username = excluded.username,
                    access_token = excluded.access_token,
                    client_business_id = excluded.client_business_id,
                    updated_at = excluded.updated_at
                """,
                (
                    account["id"],
                    account.get("username") or "",
                    access_token,
                    client_business_id,
                    saved_at,
                ),
            )


def list_accounts():
    with _connect() as connection:
        rows = connection.execute(
            """
            SELECT ig_id, username, updated_at
            FROM accounts
            ORDER BY updated_at DESC
            """
        ).fetchall()
    return [dict(row) for row in rows]


def get_account(ig_id):
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM accounts WHERE ig_id = ?",
            (ig_id, ),
        ).fetchone()
    if not row:
        return None
    account = dict(row)
    account["profile"] = json.loads(account["profile_json"] or "null")
    account["media"] = json.loads(account["media_json"] or "null")
    return account


def save_snapshot(ig_id, profile, media, media_after, media_error):
    username = ""
    if isinstance(profile, dict):
        username = profile.get("username") or ""
    with _connect() as connection:
        connection.execute(
            """
            UPDATE accounts
            SET username = COALESCE(NULLIF(?, ''), username),
                profile_json = ?,
                media_json = ?,
                media_after = ?,
                media_error = ?,
                updated_at = ?
            WHERE ig_id = ?
            """,
            (
                username,
                json.dumps(profile),
                json.dumps(media),
                media_after,
                media_error,
                _now(),
                ig_id,
            ),
        )


def delete_account(ig_id):
    with _connect() as connection:
        connection.execute("DELETE FROM accounts WHERE ig_id = ?", (ig_id, ))
