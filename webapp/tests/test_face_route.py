"""/face — 서버가 webapp/face 빌드 결과를 내보내고, /check 는 그대로인가."""
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server as S  # noqa: E402


@pytest.fixture()
def base():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), S.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield "http://127.0.0.1:{}".format(httpd.server_address[1])
    httpd.shutdown()
    httpd.server_close()


def get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", ""), e.read()


def test_face_without_build_says_how(base, monkeypatch, tmp_path):
    monkeypatch.setattr(S, "FACE_DIST", tmp_path / "dist")
    code, ctype, body = get(base + "/face/")
    assert code == 503
    assert "npm run build" in body.decode("utf-8")


def test_face_serves_build(base, monkeypatch, tmp_path):
    # 실제 빌드 없이도 돌도록 빌드 결과 모양만 갖춘 폴더를 쓴다 (CI 의 python job 은 face 를 빌드하지 않는다)
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text('<!doctype html><script type="module" src="/face/assets/app.js"></script>', encoding="utf-8")
    (dist / "manifest.webmanifest").write_text('{"name": "Vity"}', encoding="utf-8")
    monkeypatch.setattr(S, "FACE_DIST", dist)
    code, ctype, body = get(base + "/face/")
    assert code == 200 and ctype.startswith("text/html")
    assert b"/face/" in body
    code, ctype, _ = get(base + "/face/log")                  # 앱 안 주소 → index.html
    assert code == 200 and ctype.startswith("text/html")
    code, _, _ = get(base + "/face/nope.js")                   # 없는 파일은 404
    assert code == 404
    code, ctype, _ = get(base + "/face/manifest.webmanifest")
    assert code == 200 and ctype.startswith("application/manifest+json")


def test_face_redirect_and_check_unchanged(base):
    req = urllib.request.Request(base + "/face")
    opener = urllib.request.build_opener(type("NoRedirect", (urllib.request.HTTPRedirectHandler,),
                                              {"redirect_request": lambda *a, **k: None}))
    try:
        opener.open(req, timeout=5)
        raise AssertionError("redirect expected")
    except urllib.error.HTTPError as e:
        assert e.code == 301 and e.headers["Location"] == "/face/"
    code, ctype, body = get(base + "/check")
    assert code == 200 and ctype.startswith("text/html")
    code, ctype, _ = get(base + "/assets/characters/coffee.png")
    assert code == 200 and ctype == "image/png"
