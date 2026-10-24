from unittest.mock import Mock

import pytest

from auto_apply.challenge_handler import detect_challenge, handle_challenge

TURNSTILE = "div[class*='cf-turnstile'], iframe[src*='challenges.cloudflare.com']"

def _page(active=None, hidden=False, token=""):
    page = Mock()
    page.title.return_value = "Normal job page"
    def locate(selector):
        locator = Mock()
        present = selector == active or (selector == "input[name='cf-turnstile-response']" and bool(token))
        locator.count.return_value = 1 if present else 0
        locator.nth.return_value = locator
        locator.is_visible.return_value = present and not hidden
        locator.input_value.return_value = token
        return locator
    page.locator.side_effect = locate
    return page

@pytest.mark.parametrize("selector", [
    "#challenge-running", "iframe[src*='recaptcha/api2/bframe']",
    "text='Please verify you are a human'", TURNSTILE,
])
def test_detect_active_challenge(selector):
    assert detect_challenge(_page(selector)) is True

def test_detect_challenge_harmless_script():
    page = _page()
    page.content.return_value = '<script src="https://www.google.com/recaptcha/api.js"></script>'
    assert detect_challenge(page) is False

def test_detect_challenge_just_a_moment():
    page = _page()
    page.title.return_value = "Just a moment..."
    assert detect_challenge(page) is True

def test_detect_challenge_hidden_widget():
    assert detect_challenge(_page(TURNSTILE, hidden=True)) is False

def test_resolved_turnstile_token_is_not_a_blocker():
    assert detect_challenge(_page(TURNSTILE, token="human-completed-token")) is False

def test_handle_challenge_unattended():
    assert handle_challenge(_page(TURNSTILE), unattended=True) == "paused"

def test_handle_challenge_interactive_skip(monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt: "skip")
    assert handle_challenge(_page(TURNSTILE), unattended=False) == "skipped"

def test_handle_challenge_interactive_success(monkeypatch):
    page = _page()
    widget = Mock()
    widget.count.return_value = 1
    widget.nth.return_value = widget
    widget.is_visible.side_effect = [True, True, False]
    default = page.locator.side_effect
    page.locator.side_effect = lambda selector: widget if selector == TURNSTILE else default(selector)
    inputs = []
    monkeypatch.setattr("builtins.input", lambda prompt: inputs.append(prompt) or "")
    assert handle_challenge(page, unattended=False) is None
    assert len(inputs) == 1


@pytest.mark.parametrize("selector", ["iframe[src*='recaptcha/enterprise/bframe']", "#email-verification"])
def test_modern_challenge_pauses_and_hidden_challenge_does_not(selector):
    assert handle_challenge(_page(selector), unattended=True) == "paused"
    assert detect_challenge(_page(selector, hidden=True)) is False
