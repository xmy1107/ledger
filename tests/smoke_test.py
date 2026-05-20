from __future__ import annotations

import json
import os
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT))

os.environ["LEDGER_DB_PATH"] = str(Path(tempfile.gettempdir()) / "ledger_of_us_smoke.db")

from backend.server import LedgerHandler


def request_json(url: str, payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="GET" if payload is None else "POST",
    )
    with urllib.request.urlopen(request, timeout=10) as response:
        return json.loads(response.read().decode("utf-8"))


def main() -> None:
    db_path = Path(os.environ["LEDGER_DB_PATH"])
    if db_path.exists():
        db_path.unlink()

    server = ThreadingHTTPServer(("127.0.0.1", 0), LedgerHandler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    time.sleep(0.1)

    try:
        created = request_json(
            f"http://127.0.0.1:{port}/api/events",
            {
                "content": "今天因为晚饭花钱和承诺产生争执，希望能拆开事实和感受，我转了88.8元。",
            },
        )
        assert created["event"]["id"] == 1
        assert created["event"]["analysis"]["provider"] in {"ollama", "local-rules"}

        events = request_json(f"http://127.0.0.1:{port}/api/events")
        assert len(events["events"]) == 1

        stats = request_json(f"http://127.0.0.1:{port}/api/stats")
        assert stats["event_count"] == 1
        assert stats["totals"][0]["amount"] == 88.8

        print("smoke test passed")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
