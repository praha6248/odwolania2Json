"""Update check: the GitHub Pages mirror first, the GitHub API as a fallback."""

import io
import json
import urllib.request

from odwolania2json import update_check


def fake_urlopen(answers):
    """urlopen replacement returning JSON for known URLs and failing for others."""
    calls = []

    def opener(request, timeout=None):
        calls.append(request.full_url)
        if request.full_url not in answers:
            raise OSError("rate limit")
        return io.BytesIO(json.dumps(answers[request.full_url]).encode())

    return opener, calls


def test_mirror_is_used_first(monkeypatch):
    """With the mirror available the API is not called."""
    monkeypatch.delenv("O2J_NO_UPDATE_CHECK", raising=False)
    opener, calls = fake_urlopen({update_check.MIRROR_URL: {"tag_name": "v9.0.0", "assets": []}})
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    result = update_check.check_for_update("0.1.0")
    assert result["available"] and result["latest"] == "9.0.0"
    assert calls == [update_check.MIRROR_URL]


def test_api_is_the_fallback_and_failures_mean_no_update(monkeypatch):
    """When the mirror fails the API answers; when both fail no update is reported."""
    monkeypatch.delenv("O2J_NO_UPDATE_CHECK", raising=False)
    opener, _ = fake_urlopen({update_check.API_URL: {"tag_name": "v0.1.0", "assets": []}})
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    assert update_check.check_for_update("0.1.0")["available"] is False
    opener, _ = fake_urlopen({})
    monkeypatch.setattr(urllib.request, "urlopen", opener)
    assert update_check.check_for_update("0.1.0") == {"available": False, "current": "0.1.0"}
