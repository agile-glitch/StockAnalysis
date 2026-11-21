"""Send alerts to a phone or chat app.

One URL setting covers three services:

  https://ntfy.sh/<your-topic>               free phone push: install the ntfy app
                                             and subscribe to the same topic
  https://discord.com/api/webhooks/...       a Discord channel webhook
  https://hooks.slack.com/services/...       a Slack incoming webhook

Anything else is treated as an ntfy server (ntfy can be self-hosted).
Pushes go out on a background thread so a slow service never delays alerts.
"""

from __future__ import annotations

import json
import logging
import queue
import threading
import time
import urllib.request
from urllib.parse import urlsplit

log = logging.getLogger("stockanalysis.push")

INSIDER_KINDS = {"insider_buy", "insider_buy_market", "insider_sell", "insider_cluster", "tradingview"}
# Rare (a few a year) and actionable, so they go to the phone with the default scope too.
TREND_KINDS = {"market_trend", "trend_portfolio", "market_regime"}
TONE_TAGS = {"bullish": "chart_with_upwards_trend", "bearish": "chart_with_downwards_trend",
             "warning": "warning", "neutral": "bell", "info": "bell"}


def service_for(url: str) -> str:
    host = urlsplit(url).netloc.lower()
    if host.endswith("discord.com") or host.endswith("discordapp.com"):
        return "discord"
    if host == "hooks.slack.com":
        return "slack"
    return "ntfy"


def build_request(url: str, note: dict) -> urllib.request.Request:
    """The HTTP request that delivers one notification to `url`."""
    title, body, link = note["title"], note["body"], note.get("link")
    kind = service_for(url)
    if kind == "discord":
        content = f"**{title}**\n{body}" + (f"\n<{link}>" if link else "")
        payload = {"content": content[:1990]}
    elif kind == "slack":
        payload = {"text": f"*{title}*\n{body}" + (f"\n<{link}|SEC filing>" if link else "")}
    else:
        parts = urlsplit(url)
        topic = parts.path.strip("/")
        if not topic or "/" in topic:
            raise ValueError("An ntfy URL must look like https://ntfy.sh/your-topic")
        url = f"{parts.scheme}://{parts.netloc}/"
        payload = {
            "topic": topic,
            "title": title[:250],
            "message": body[:3500],
            "tags": [TONE_TAGS.get(note.get("tone"), "bell")],
            "priority": 4 if note.get("kind") in INSIDER_KINDS else 3,
        }
        if link:
            payload["click"] = link
    return urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"),
                                  headers={"Content-Type": "application/json",
                                           "User-Agent": "StockAnalysis"}, method="POST")


class Pusher:
    def __init__(self, settings_fn, opener=None):
        self._settings_fn = settings_fn
        self._opener = opener or urllib.request.urlopen
        self._queue: queue.Queue = queue.Queue(maxsize=200)
        self.status = {"last_sent": None, "last_error": None, "sent": 0}
        self._thread = threading.Thread(target=self._run, daemon=True, name="stockanalysis-push")
        self._thread.start()

    def wants(self, note: dict) -> bool:
        settings = self._settings_fn()
        if not settings.get("push_url"):
            return False
        return settings.get("push_scope") == "all" or note.get("kind") in INSIDER_KINDS | TREND_KINDS

    def __call__(self, note: dict):
        """Database listener: queue a push for each new notification."""
        if self.wants(note):
            try:
                self._queue.put_nowait(note)
            except queue.Full:
                self.status["last_error"] = "Too many alerts queued; some pushes were dropped."

    def send_now(self, note: dict, url: str | None = None):
        """Deliver synchronously (used by the 'Send test' button). Raises on failure."""
        url = url or self._settings_fn().get("push_url")
        if not url:
            raise ValueError("No push URL set.")
        with self._opener(build_request(url, note), timeout=15) as response:
            response.read()
        self.status.update({"last_sent": time.time(), "last_error": None})
        self.status["sent"] += 1

    def _run(self):
        while True:
            note = self._queue.get()
            for attempt in range(3):
                try:
                    self.send_now(note)
                    break
                except Exception as exc:
                    self.status["last_error"] = f"Push failed: {exc}"
                    log.warning("Push failed (attempt %s): %s", attempt + 1, exc)
                    time.sleep(2 ** attempt)
