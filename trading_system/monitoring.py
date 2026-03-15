from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import requests


class Monitor(object):
    def __init__(self, heartbeat_path, dashboard_path, alerts_path, alert_webhook_url=""):
        self.heartbeat_path = Path(heartbeat_path)
        self.dashboard_path = Path(dashboard_path)
        self.alerts_path = Path(alerts_path)
        self.alert_webhook_url = alert_webhook_url
        for path in (self.heartbeat_path, self.dashboard_path, self.alerts_path):
            path.parent.mkdir(parents=True, exist_ok=True)

    def heartbeat(self, status, details):
        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "status": status,
            "details": details,
        }
        self.heartbeat_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def dashboard(self, payload):
        body = dict(payload)
        body["timestamp"] = datetime.utcnow().isoformat()
        self.dashboard_path.write_text(json.dumps(body, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    def alert(self, event_type, payload):
        line = "%s %s %s\n" % (datetime.utcnow().isoformat(), event_type, json.dumps(payload, sort_keys=True))
        with self.alerts_path.open("a", encoding="utf-8") as handle:
            handle.write(line)
        if not self.alert_webhook_url:
            return
        try:
            requests.post(self.alert_webhook_url, json={"event_type": event_type, "payload": payload}, timeout=5)
        except Exception:
            pass
