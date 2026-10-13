"""AM-004: the map viewer is a locked-down static shell over the authenticated API."""

import re
import shutil
import subprocess
from pathlib import Path

import pytest

UI = Path(__file__).resolve().parents[1] / "src" / "active_memory" / "ui"


def test_ui_shell_is_served_with_strict_headers_and_no_data(app):
    from fastapi.testclient import TestClient

    with TestClient(app) as anonymous:  # the shell needs no token: it carries no memory data
        for path, kind in (
            ("/ui", "text/html"),
            ("/ui/app.js", "javascript"),
            ("/ui/logic.js", "javascript"),
            ("/ui/app.css", "text/css"),
        ):
            response = anonymous.get(path)
            assert response.status_code == 200 and kind in response.headers["content-type"]
            csp = response.headers["content-security-policy"]
            assert "default-src 'none'" in csp and "script-src 'self'" in csp
            assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
            assert "frame-ancestors 'none'" in csp
            assert response.headers["x-content-type-options"] == "nosniff"
            assert response.headers["cache-control"] == "no-store"
        # Data stays behind auth; the shell never embeds any.
        assert anonymous.get("/v1/map").status_code == 401
        assert "nodes" not in anonymous.get("/ui").text.lower().replace("uzlů", "")
        for path in (
            "/ui/../pyproject.toml",
            "/ui/secret.txt",
            "/ui/%2e%2e/api.py",
            "/ui/__init__.py",
        ):
            assert anonymous.get(path).status_code == 404


def test_ui_has_no_inline_scripts_external_resources_or_html_injection_sinks():
    html = (UI / "index.html").read_text(encoding="utf-8")
    assert not re.search(r"<script(?![^>]*\bsrc=)", html) and "onclick=" not in html
    assert not re.search(r"(?:src|href)=[\"']https?:", html)
    code = (UI / "app.js").read_text(encoding="utf-8") + (UI / "logic.js").read_text(
        encoding="utf-8"
    )
    for sink in (
        "innerHTML",
        "outerHTML",
        "insertAdjacentHTML",
        "document.write",
        "eval(",
        "new Function",
        "localStorage",
    ):
        assert sink not in code, sink
    assert "https://" not in code and "http://" not in code


def test_ui_marks_candidates_and_never_auto_confirms():
    code = (UI / "app.js").read_text(encoding="utf-8")
    assert "Kandidát: strojový návrh" in code and "badge(node.status)" in code
    # The only writes are explicit reviews/proposal generation issued from button clicks.
    assert set(re.findall(r'call\("(POST|DELETE|PUT|PATCH)"', code)) == {"POST"}
    assert (
        code.count('call("POST"') == 2 and "/review" in code and "/v1/maintenance/propose" in code
    )
    css = (UI / "app.css").read_text(encoding="utf-8")
    assert ".candidate" in css and "dashed" in css


@pytest.mark.skipif(shutil.which("node") is None, reason="node is needed for the UI logic tests")
def test_ui_logic_unit_tests_pass():
    root = Path(__file__).resolve().parent
    result = subprocess.run(
        ["node", "--test", str(root / "ui" / "logic.test.js")],
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-1000:]
