import json
import time

import pytest

from stockanalysis.push import Pusher, build_request, service_for

NOTE = {"title": "ACME: CEO bought $1.0M", "body": "Ana Rivera bought 20,000 shares.", "tone": "bullish",
        "kind": "insider_buy", "link": "https://www.sec.gov/x-index.htm"}


def test_service_detection():
    assert service_for("https://ntfy.sh/my-topic") == "ntfy"
    assert service_for("https://discord.com/api/webhooks/1/abc") == "discord"
    assert service_for("https://hooks.slack.com/services/T/B/x") == "slack"
    assert service_for("https://push.example.org/alerts") == "ntfy"


def test_ntfy_request_uses_json_publish():
    req = build_request("https://ntfy.sh/stock-alerts-123", NOTE)
    assert req.full_url == "https://ntfy.sh/" and req.get_method() == "POST"
    payload = json.loads(req.data)
    assert payload["topic"] == "stock-alerts-123" and payload["title"] == NOTE["title"]
    assert payload["priority"] == 4 and payload["click"] == NOTE["link"]
    assert payload["tags"] == ["chart_with_upwards_trend"]
    with pytest.raises(ValueError):
        build_request("https://ntfy.sh/", NOTE)


def test_discord_and_slack_payloads():
    discord = json.loads(build_request("https://discord.com/api/webhooks/1/abc", NOTE).data)
    assert discord["content"].startswith("**ACME: CEO bought $1.0M**") and NOTE["link"] in discord["content"]
    slack = json.loads(build_request("https://hooks.slack.com/services/T/B/x", NOTE).data)
    assert slack["text"].startswith("*ACME: CEO bought $1.0M*")


class Recorder:
    def __init__(self):
        self.sent = []

    def __call__(self, request, timeout=None):
        self.sent.append(request)

        class R:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                pass

            def read(self):
                return b"{}"
        return R()


def wait_for(predicate, seconds=3.0):
    end = time.time() + seconds
    while time.time() < end and not predicate():
        time.sleep(0.02)
    return predicate()


def test_pusher_respects_scope_and_url():
    settings = {"push_url": "", "push_scope": "insider"}
    rec = Recorder()
    pusher = Pusher(lambda: settings, opener=rec)
    pusher(NOTE)
    time.sleep(0.1)
    assert rec.sent == []                                     # no URL set
    settings["push_url"] = "https://ntfy.sh/t"
    pusher({**NOTE, "kind": "signal"})
    pusher(NOTE)
    assert wait_for(lambda: len(rec.sent) == 1)               # only the insider alert
    settings["push_scope"] = "all"
    pusher({**NOTE, "kind": "signal"})
    assert wait_for(lambda: len(rec.sent) == 2) and pusher.status["sent"] == 2


def test_database_listener_pushes_new_notifications_once():
    from stockanalysis.db import Database
    db = Database(":memory:", seed_watchlist=False)
    db.update_settings({"push_url": "https://ntfy.sh/t"})
    rec = Recorder()
    db.on_notification(Pusher(db.get_settings, opener=rec))
    for _ in range(2):
        db.add_notification(symbol="ACME", kind="insider_buy", tone="bullish", title="t", body="b", dedup_key="k")
    assert wait_for(lambda: len(rec.sent) == 1)
    time.sleep(0.1)
    assert len(rec.sent) == 1
