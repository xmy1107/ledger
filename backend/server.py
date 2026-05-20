from __future__ import annotations

import json
import mimetypes
import os
import sqlite3
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ai import NARRATOR_LABELS, analyze_event, enrich_from_text
from memory import RelationshipMemory

ROOT = Path(__file__).resolve().parents[1]
STATIC_DIR = ROOT / "frontend"
DATA_DIR = Path(os.environ.get("LEDGER_DATA_DIR", ROOT / "data"))
DB_PATH = Path(os.environ.get("LEDGER_DB_PATH", DATA_DIR / "ledger.db"))
SCHEMA_PATH = ROOT / "backend" / "schema.sql"


def get_conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    with SCHEMA_PATH.open("r", encoding="utf-8") as schema:
        conn.executescript(schema.read())
    return conn


def row_to_event(row: sqlite3.Row, edges: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    amount_cents = int(row["amount_cents"])
    tags = json.loads(row["tags"] or "[]")
    analysis = json.loads(row["analysis_json"]) if row["analysis_json"] else None
    return {
        "id": row["id"],
        "occurred_on": row["occurred_on"],
        "narrator": row["narrator"],
        "narrator_label": NARRATOR_LABELS.get(row["narrator"], "未知"),
        "title": row["title"],
        "amount": amount_cents / 100,
        "amount_cents": amount_cents,
        "currency": row["currency"],
        "emotion_score": row["emotion_score"],
        "content": row["content"],
        "tags": tags,
        "analysis": analysis,
        "edges": edges or [],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def auto_related_event_ids(
    conn: sqlite3.Connection, relation_keywords: list[str], title: str, content: str, limit: int = 5
) -> list[int]:
    rows = conn.execute(
        "SELECT id, title, content, tags FROM events ORDER BY occurred_on DESC, id DESC LIMIT 80"
    ).fetchall()
    keywords = [x.lower() for x in relation_keywords if x]
    if not keywords:
        keywords = [x.lower() for x in title.split()[:3] if x]
    scored: list[tuple[int, int]] = []
    for row in rows:
        hay = " ".join([str(row["title"]), str(row["content"]), str(row["tags"])]).lower()
        score = 0
        for kw in keywords:
            if kw and kw in hay:
                score += 1
        if score > 0:
            scored.append((int(row["id"]), score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return [item[0] for item in scored[:limit]]


class LedgerHandler(BaseHTTPRequestHandler):
    server_version = "LedgerOfUs/0.2"

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/events":
            self.handle_list_events(parsed.query)
            return
        if parsed.path == "/api/stats":
            self.handle_stats()
            return
        if parsed.path.startswith("/api/events/"):
            self.handle_get_event(parsed.path)
            return
        self.serve_static(parsed.path)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/events":
            self.handle_create_event()
            return
        if parsed.path.startswith("/api/events/") and parsed.path.endswith("/analyze"):
            self.handle_analyze_event(parsed.path)
            return
        self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)

    def do_OPTIONS(self) -> None:
        self.send_response(HTTPStatus.NO_CONTENT)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET,POST,OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def handle_list_events(self, query: str) -> None:
        params = parse_qs(query)
        limit = min(100, int(params.get("limit", ["30"])[0]))
        conn = get_conn()
        rows = conn.execute(
            "SELECT * FROM events ORDER BY occurred_on DESC, id DESC LIMIT ?", (limit,)
        ).fetchall()
        events = [row_to_event(row) for row in rows]
        edge_rows = conn.execute(
            "SELECT source_event_id, target_event_id, relation_type, note FROM event_edges ORDER BY id"
        ).fetchall()
        self.send_json({"events": events, "edges": [dict(row) for row in edge_rows]})

    def handle_get_event(self, path: str) -> None:
        event_id = parse_event_id(path)
        if event_id is None:
            self.send_json({"error": "Invalid event id"}, HTTPStatus.BAD_REQUEST)
            return
        conn = get_conn()
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            self.send_json({"error": "Event not found"}, HTTPStatus.NOT_FOUND)
            return
        edges = conn.execute(
            """
            SELECT source_event_id, target_event_id, relation_type, note
            FROM event_edges
            WHERE source_event_id = ? OR target_event_id = ?
            ORDER BY id
            """,
            (event_id, event_id),
        ).fetchall()
        self.send_json({"event": row_to_event(row, [dict(edge) for edge in edges])})

    def handle_stats(self) -> None:
        conn = get_conn()
        totals = conn.execute(
            """
            SELECT narrator, COUNT(*) AS count, SUM(amount_cents) AS cents, AVG(emotion_score) AS avg_emotion
            FROM events
            GROUP BY narrator
            """
        ).fetchall()
        event_count = conn.execute("SELECT COUNT(*) AS count FROM events").fetchone()["count"]
        edge_count = conn.execute("SELECT COUNT(*) AS count FROM event_edges").fetchone()["count"]
        self.send_json(
            {
                "event_count": event_count,
                "edge_count": edge_count,
                "totals": [
                    {
                        "narrator": row["narrator"],
                        "narrator_label": NARRATOR_LABELS.get(row["narrator"], "未知"),
                        "count": row["count"],
                        "amount": (row["cents"] or 0) / 100,
                        "avg_emotion": round(row["avg_emotion"] or 0, 1),
                    }
                    for row in totals
                ],
            }
        )

    def handle_create_event(self) -> None:
        payload = self.read_json()
        content = str(payload.get("content", "")).strip()
        if not content:
            self.send_json({"error": "请输入事件文本"}, HTTPStatus.BAD_REQUEST)
            return

        conn = get_conn()
        memory = RelationshipMemory(conn)
        enrich = enrich_from_text(content, memory.recent_context())
        amount_cents = int(round(float(enrich["amount"]) * 100))
        related_ids = auto_related_event_ids(
            conn, enrich["relation_keywords"], enrich["title"], content
        )

        cursor = conn.execute(
            """
            INSERT INTO events
              (occurred_on, narrator, title, amount_cents, currency, emotion_score, content, tags)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                enrich["occurred_on"],
                enrich["narrator"],
                enrich["title"],
                amount_cents,
                enrich["currency"],
                enrich["emotion_score"],
                content,
                json.dumps(enrich["tags"], ensure_ascii=False),
            ),
        )
        event_id = int(cursor.lastrowid)
        for target_id in related_ids:
            if target_id == event_id:
                continue
            conn.execute(
                """
                INSERT OR IGNORE INTO event_edges
                  (source_event_id, target_event_id, relation_type, note)
                VALUES (?, ?, ?, ?)
                """,
                (event_id, target_id, "auto-related", "agent 自动关联"),
            )
        conn.commit()

        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        event = row_to_event(row)
        analysis = analyze_event(event, memory.recent_context())
        conn.execute(
            "UPDATE events SET analysis_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(analysis, ensure_ascii=False), event_id),
        )
        conn.commit()
        event["analysis"] = analysis
        memory_result = memory.remember_event(event, analysis)
        self.send_json(
            {
                "event": event,
                "memory": {"provider": memory_result.provider, "summary": memory_result.summary},
                "enrichment_provider": enrich.get("enrichment_provider", "local-rules"),
            },
            HTTPStatus.CREATED,
        )

    def handle_analyze_event(self, path: str) -> None:
        event_id = parse_event_id(path)
        if event_id is None:
            self.send_json({"error": "Invalid event id"}, HTTPStatus.BAD_REQUEST)
            return
        conn = get_conn()
        row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
        if row is None:
            self.send_json({"error": "Event not found"}, HTTPStatus.NOT_FOUND)
            return
        event = row_to_event(row)
        memory = RelationshipMemory(conn)
        analysis = analyze_event(event, memory.recent_context())
        conn.execute(
            "UPDATE events SET analysis_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
            (json.dumps(analysis, ensure_ascii=False), event_id),
        )
        conn.commit()
        self.send_json({"event": {**event, "analysis": analysis}})

    def serve_static(self, path: str) -> None:
        file_path = STATIC_DIR / "index.html" if path in {"", "/"} else (STATIC_DIR / path.lstrip("/")).resolve()
        if not str(file_path).startswith(str(STATIC_DIR.resolve())):
            self.send_json({"error": "Invalid path"}, HTTPStatus.BAD_REQUEST)
            return
        if not file_path.exists() or not file_path.is_file():
            self.send_json({"error": "Not found"}, HTTPStatus.NOT_FOUND)
            return
        content_type = mimetypes.guess_type(str(file_path))[0] or "application/octet-stream"
        body = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        data = self.rfile.read(length).decode("utf-8")
        return json.loads(data)

    def send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[server] {self.address_string()} - {format % args}")


def parse_event_id(path: str) -> int | None:
    parts = [part for part in path.split("/") if part]
    if len(parts) < 3:
        return None
    try:
        return int(parts[2])
    except ValueError:
        return None


def main() -> None:
    host = os.environ.get("LEDGER_HOST", "127.0.0.1")
    port = int(os.environ.get("LEDGER_PORT", "8765"))
    get_conn().close()
    httpd = ThreadingHTTPServer((host, port), LedgerHandler)
    print(f"Ledger of Us running at http://{host}:{port}")
    httpd.serve_forever()


if __name__ == "__main__":
    main()

