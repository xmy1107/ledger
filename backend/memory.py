from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass
class MemoryResult:
    provider: str
    summary: str
    metadata: dict[str, Any]


class RelationshipMemory:
    """Small adapter around mem0 with a SQLite fallback for local-first use."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn
        self.provider = "sqlite"
        self._mem0 = None

        if os.environ.get("LEDGER_USE_MEM0") == "1":
            try:
                from mem0 import Memory  # type: ignore

                config = {
                    "llm": {
                        "provider": "ollama",
                        "config": {
                            "model": os.environ.get("OLLAMA_MODEL", "deepseek-r1"),
                            "ollama_base_url": os.environ.get(
                                "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
                            ),
                        },
                    },
                    "embedder": {
                        "provider": "ollama",
                        "config": {
                            "model": os.environ.get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
                            "ollama_base_url": os.environ.get(
                                "OLLAMA_BASE_URL", "http://127.0.0.1:11434"
                            ),
                        },
                    },
                }
                self._mem0 = Memory.from_config(config)
                self.provider = "mem0"
            except Exception:
                self._mem0 = None
                self.provider = "sqlite"

    def remember_event(self, event: dict[str, Any], analysis: dict[str, Any]) -> MemoryResult:
        summary = self._build_summary(event, analysis)
        metadata = {
            "event_id": event["id"],
            "narrator": event["narrator"],
            "occurred_on": event["occurred_on"],
            "tags": event.get("tags", []),
        }

        if self._mem0 is not None:
            self._mem0.add(summary, user_id="relationship", metadata=metadata)

        self.conn.execute(
            """
            INSERT INTO memories (event_id, scope, summary, metadata_json)
            VALUES (?, ?, ?, ?)
            """,
            (event["id"], "relationship", summary, json.dumps(metadata, ensure_ascii=False)),
        )
        self.conn.commit()

        return MemoryResult(provider=self.provider, summary=summary, metadata=metadata)

    def recent_context(self, limit: int = 8) -> list[str]:
        rows = self.conn.execute(
            """
            SELECT summary FROM memories
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [row["summary"] for row in rows]

    def _build_summary(self, event: dict[str, Any], analysis: dict[str, Any]) -> str:
        amount = event.get("amount", 0)
        score = analysis.get("fairness_score", 50)
        core = analysis.get("core_issue", "未形成明确核心议题")
        return (
            f"{event['occurred_on']}，{event['narrator_label']}记录：{event['title']}。"
            f"金额 {amount:.2f} {event.get('currency', 'CNY')}，情绪强度 {event.get('emotion_score', 0)}。"
            f"核心议题：{core}。暂定公平倾向分 {score}/100。"
        )

