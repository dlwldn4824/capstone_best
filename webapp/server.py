"""Vity 웹앱 서버: 거울 기록(/) · 대학생 헬스체크(/check) · Vity 얼굴 체크(/face/).

    python webapp/server.py                 # http://localhost:8000
    python webapp/server.py --https         # 폰에서 카메라를 쓰려면 (아래 참고)

표준 라이브러리 http.server + sqlite3 로 돈다. check.py · mirror.py 가 numpy 를 쓰므로
저장소 루트의 requirements.txt 를 먼저 설치한다.
워치 버전(/v1 · /watch)은 legacy/webapp_v1 에 보관만 하고 내보내지 않는다.

**왜 --https 인가.** 브라우저는 카메라(getUserMedia)를 보안 컨텍스트(https 또는
localhost)에서만 허용한다. 폰이 노트북 IP(http://192.168.x.x)로 접속하면 막힌다.
--https 는 openssl 로 자체 서명 인증서를 만들어 쓴다 (Git for Windows 에 openssl 이
들어 있다). 폰에서 처음 열 때 경고가 뜨면 '계속'.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT_DIR = Path(__file__).resolve().parents[1]
import mirror as MI
import check as CK

STATIC = Path(__file__).resolve().parent / "static"
# 화면 파일을 찾는 순서: 지금 웹 → 공용 에셋(캐릭터 · 글꼴)
# (주소 앞부분, 폴더, 허용 하위 폴더): /assets/characters/… → assets/characters/… 처럼 주소와 폴더가 같다
STATIC_ROOTS = [("", STATIC, ""),
                ("assets/", ROOT_DIR / "assets", ("characters/", "fonts/"))]
# /face (Vity 얼굴 체크): webapp/face 를 npm run build 한 결과. git 에는 없다
FACE_DIST = Path(__file__).resolve().parent / "face" / "dist"
FACE_MISSING = ("/face 는 아직 빌드되지 않았어요.\n"
                "cd webapp/face && npm ci && npm run build 를 실행한 뒤 서버를 다시 켜 주세요.\n")
CERT_DIR = Path(__file__).resolve().parent / "data"
LOCK = threading.Lock()
CCON = None                                         # 대학생 헬스체크 (check.py)
MCON = None                                         # 거울 기록 (mirror.py) — 보고서 설계

# / 는 보고서 설계(카메라 하나). 워치 버전(/v1 · /watch)은 legacy/webapp_v1 에 보관만 한다.
ROUTES = {"/": "mirror.html", "/check": "check.html"}
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")
mimetypes.add_type("text/javascript", ".mjs")
mimetypes.add_type("application/wasm", ".wasm")
mimetypes.add_type("application/octet-stream", ".task")


def dumps(obj):
    return json.dumps(obj, ensure_ascii=False, default=str)


class Handler(BaseHTTPRequestHandler):
    server_version = "Vity"

    def log_message(self, fmt, *args):  # 조용히 — 오류만 보인다
        pass

    # --- 공통 ---
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _json(self, obj, code=200):
        self._send(code, dumps(obj))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # --- GET ---
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/m/state":
            with LOCK:
                return self._json(MI.state(MCON))
        if path == "/api/m/records":
            with LOCK:
                return self._json(MI.records(MCON))
        if path == "/api/m/report":
            with LOCK:
                return self._json(MI.report(MCON))
        if path == "/api/c/state":
            q = parse_qs(urlparse(self.path).query)
            with LOCK:
                return self._json(CK.state(CCON, mid=(q.get("member") or [None])[0]))
        if path == "/api/c/result":
            q = parse_qs(urlparse(self.path).query)
            try:
                with LOCK:
                    return self._json(CK.result(CCON, int(q["id"][0]), mid=(q.get("member") or [None])[0]))
            except (KeyError, ValueError):
                return self._json({"error": "없는 측정"}, 404)
        if path == "/api/c/groups":
            q = parse_qs(urlparse(self.path).query)
            with LOCK:
                return self._json({"groups": CK.groups_state(CCON, (q.get("member") or [""])[0])})
        if path == "/api/c/history":
            q = parse_qs(urlparse(self.path).query)
            with LOCK:
                return self._json(CK.history(CCON, mid=(q.get("member") or [None])[0]))
        if path == "/api/m/schedule.ics":
            with LOCK:
                sched = MI.settings(MCON)["schedule"]
            origin = "{}://{}".format("https" if isinstance(self.connection, ssl.SSLSocket) else "http",
                                      self.headers.get("Host", "localhost"))
            return self._send(200, MI.schedule_ics(sched, origin), "text/calendar; charset=utf-8")
        if path == "/face":
            self.send_response(301)
            self.send_header("Location", "/face/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if path.startswith("/face/"):
            return self._face(path[len("/face/"):])
        name = ROUTES.get(path, path.lstrip("/"))
        f = None
        for prefix, root, only in STATIC_ROOTS:
            if not name.startswith(prefix):
                continue
            sub = name[len(prefix):]
            if only and not sub.startswith(only):              # 에셋 폴더는 캐릭터 · 글꼴만 내보낸다
                continue
            c = (root / sub).resolve()
            dirs = [(root / o).resolve() for o in only] if only else [root.resolve()]
            if any(d in c.parents for d in dirs) and c.is_file():
                f = c
                break
        if f is None:
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    def _face(self, sub):
        """/face/… → webapp/face/dist/…. 파일이 아닌 앱 안 주소는 index.html 로 돌린다 (SPA)."""
        root = FACE_DIST.resolve()
        if not (root / "index.html").is_file():
            return self._send(503, FACE_MISSING, "text/plain; charset=utf-8")
        f = (root / sub).resolve()
        if not (root in f.parents and f.is_file()):
            if "." in sub.rsplit("/", 1)[-1]:                  # 없는 파일(.js · .png …)은 404
                return self._send(404, "not found", "text/plain; charset=utf-8")
            f = root / "index.html"
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    # --- POST ---
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            b = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "JSON 이 아니다"}, 400)
        if path.startswith("/api/m/"):
            return self._mirror(path, b)
        if path.startswith("/api/c/"):
            return self._check(path, b)
        return self._json({"error": "없는 경로"}, 404)


    def _check(self, path, b):
        """헬스체크 API. 받는 것은 브라우저가 계산한 지표 숫자와 세 가지 답뿐이다."""
        try:
            with LOCK:
                if path == "/api/c/scan":
                    num = lambda k, f=float: None if b.get(k) is None else f(b[k])  # noqa: E731
                    out = CK.add_scan(CCON, b.get("metrics") or {}, num("sleep_h"), num("caffeine", int), num("mood", int),
                                      b.get("kind") or "normal", num("pair", int), member=b.get("member"))
                elif path == "/api/c/profile":
                    CK.set_profile(CCON, b.get("member"), **{k: b[k] for k in ("height", "weight", "birth_year", "consent") if k in b})
                    out = CK.state(CCON, mid=b.get("member"))
                elif path == "/api/c/demo":
                    CK.seed_demo(CCON, mid=b.get("member"))
                    if b.get("member"):
                        CK.seed_group_demo(CCON, b["member"], b.get("nick") or "나")
                    out = CK.state(CCON, mid=b.get("member"))
                elif path == "/api/c/group/create":
                    out = {"group": CK.create_group(CCON, b["member"], b.get("nick"), b.get("name"), b.get("start") or "07:00",
                                                    b.get("end") or "09:00", b.get("rule") or "", icon=b.get("icon") or "sleep")}
                elif path == "/api/c/group/join":
                    out = {"group": CK.join_group(CCON, b["member"], b.get("nick"), b.get("code"))}
                elif path == "/api/c/group/leave":
                    out = {"group": CK.leave_group(CCON, b["member"], b.get("code"))}
                elif path == "/api/c/reset":
                    CK.reset(CCON, b.get("member"))
                    out = CK.state(CCON, mid=b.get("member"))
                else:
                    return self._json({"error": "없는 경로"}, 404)
        except KeyError as e:
            return self._json({"error": "빠진 값: {}".format(e)}, 400)
        except (ValueError, TypeError) as e:
            return self._json({"error": str(e)}, 400)
        if path.startswith("/api/c/group/") and b.get("member"):
            with LOCK:
                out["groups"] = CK.groups_state(CCON, b["member"])
        return self._json(out)

    def _mirror(self, path, b):
        """거울 기록 API. 받는 것은 얼굴에서 뽑은 숫자뿐이다 (영상 · 사진 없음)."""
        try:
            with LOCK:
                if path == "/api/m/record":
                    out = MI.add_record(MCON, b.get("bpm"), b.get("snr"), b.get("bright"), b.get("motion"),
                                        b.get("quality_ok"), b.get("a_rel"), b.get("a_cheek"),
                                        bool(b.get("makeup")), b.get("routine"), None, b.get("trigger"),
                                        int(b.get("retry") or 0))
                elif path == "/api/m/answer":
                    out = MI.answer(MCON, int(b["id"]), b["reason"], b.get("sub"))
                elif path == "/api/m/routine":
                    out = MI.set_routine(MCON, int(b["id"]), b["routine"])
                elif path == "/api/m/settings":
                    if "schedule" in b:
                        MI.set_setting(MCON, "schedule", MI.clean_schedule(b["schedule"]))
                    for k in ("consent", "k", "exam_start", "exam_end"):
                        if k in b:
                            v = b[k]
                            if k == "k" and float(v) not in MI.K_CHOICES:
                                raise ValueError("k 는 2, 2.5, 3 중 하나")
                            MI.set_setting(MCON, k, float(v) if k == "k" else v)
                    out = MI.state(MCON)
                elif path == "/api/m/demo":
                    MI.seed_demo(MCON)
                    out = MI.state(MCON)
                elif path == "/api/m/reset":
                    MI.reset(MCON)
                    out = MI.state(MCON)
                else:
                    return self._json({"error": "없는 경로"}, 404)
        except KeyError as e:
            return self._json({"error": "빠진 값: {}".format(e)}, 400)
        except ValueError as e:
            return self._json({"error": str(e)}, 400)
        return self._json(out)


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(ip):
    CERT_DIR.mkdir(parents=True, exist_ok=True)
    crt, key = CERT_DIR / "dev.crt", CERT_DIR / "dev.key"
    if crt.exists() and key.exists():
        return crt, key
    cmd = ["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "365",
           "-keyout", str(key), "-out", str(crt), "-subj", "/CN=excuse-gauge-dev",
           "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:{}".format(ip)]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit("openssl 로 인증서를 못 만들었다 ({}). Git Bash 에서 실행하거나 "
                         "openssl 을 설치할 것.".format(e))
    return crt, key


def main():
    import sys
    sys.stdout.reconfigure(line_buffering=True)      # 안내 문구가 바로 보이게
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--https", action="store_true", help="폰에서 카메라를 쓰려면")
    args = ap.parse_args()

    global MCON, CCON
    MCON = MI.connect()
    CCON = CK.connect()

    httpd = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    httpd.daemon_threads = True
    ip = lan_ip()
    scheme = "http"
    if args.https:
        crt, key = ensure_cert(ip)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(str(crt), str(key))
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)
        scheme = "https"

    print("Vity 서버")
    print("  이 컴퓨터   {}://localhost:{}/        (거울 기록 · 보고서 설계)".format(scheme, args.port))
    print("             {}://localhost:{}/check   (대학생 헬스체크)".format(scheme, args.port))
    print("             {}://localhost:{}/face/   (Vity 얼굴 체크{})".format(
        scheme, args.port, "" if (FACE_DIST / "index.html").is_file() else " — 빌드 필요: cd webapp/face && npm ci && npm run build"))
    print("  같은 와이파이의 폰에서")
    print("             {}://{}:{}/".format(scheme, ip, args.port))
    if not args.https:
        print("  * 폰에서 카메라를 쓰려면 --https 로 다시 켤 것")
    print("  종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
