from __future__ import annotations

import smtplib
import time
from email.message import EmailMessage

from trading_system.config.settings import Settings


class AlertManager:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self._last_sent: dict[str, float] = {}

    def __repr__(self) -> str:
        return f"AlertManager(email_to={self.settings.alert_email_to!r})"

    def send_alert(self, alert_type: str, subject: str, body: str) -> bool:
        now = time.time()
        if now - self._last_sent.get(alert_type, 0.0) < 300:
            return False
        self._last_sent[alert_type] = now
        if not (self.settings.alert_email_to and self.settings.alert_email_from and self.settings.alert_smtp_host):
            return False
        message = EmailMessage()
        message["To"] = self.settings.alert_email_to
        message["From"] = self.settings.alert_email_from
        message["Subject"] = subject
        message.set_content(body)
        try:
            with smtplib.SMTP(self.settings.alert_smtp_host, self.settings.alert_smtp_port, timeout=20) as server:
                server.starttls()
                if self.settings.alert_smtp_username:
                    server.login(self.settings.alert_smtp_username, self.settings.alert_smtp_password)
                server.send_message(message)
            return True
        except Exception:
            return False

