"""핑계 게이지 웹앱 서버 — 폰(/)과 워치(/watch)가 같은 판정을 실시간으로 본다.

    python webapp/server.py                 # http://localhost:8000
    python webapp/server.py --https         # 폰에서 카메라·블루투스를 쓰려면 (아래 참고)

설치할 것 없음 — 표준 라이브러리 http.server + sqlite3. 판정은 webapp/engine.py
(= src/nesy 연구 코드)가 한다.

**왜 --https 인가.** 브라우저는 카메라(getUserMedia)와 Web Bluetooth 를 보안
컨텍스트(https 또는 localhost)에서만 허용한다. 폰이 노트북 IP(http://192.168.x.x)로
접속하면 둘 다 막힌다. --https 는 openssl 로 자체 서명 인증서를 만들어 쓴다
(Git for Windows 에 openssl 이 들어 있다). 폰에서 처음 열 때 경고가 뜨면 '계속'.

동기화: 서버가 Server-Sent Events(/api/events)로 상태가 바뀔 때마다 밀어준다.
워치에서 '술' 을 누르면 폰 화면이 바로 바뀐다. 블루투스 심박도 같은 길로 워치에 간다.
"""
from __future__ import annotations

import argparse
import json
import mimetypes
import queue
import socket
import ssl
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import engine as E

STATIC = Path(__file__).resolve().parent / "static"
CERT_DIR = E.ROOT / "data" / "app"
LOCK = threading.Lock()
CON = None
SUBSCRIBERS: list[queue.Queue] = []
LIVE = {"bpm": None, "rr": None, "at": None, "device": None}
PRESENCE = {"phone": 0, "watch": 0}                 # 지금 붙어 있는 화면 수

ROUTES = {"/": "phone.html", "/watch": "watch.html", "/sw.js": "sw.js"}
mimetypes.add_type("application/manifest+json", ".webmanifest")
mimetypes.add_type("text/javascript", ".js")


def broadcast(kind, payload):
    msg = "event: {}\ndata: {}\n\n".format(kind, E.dumps(payload)).encode("utf-8")
    for q in list(SUBSCRIBERS):
        try:
            q.put_nowait(msg)
        except queue.Full:
            pass


def state():
    with LOCK:
        s = E.compute(CON)
    s["live"] = LIVE
    return s


def push_state():
    s = state()
    broadcast("state", s)
    with LOCK:
        n = E.maybe_notify(CON, s)
    if n:
        broadcast("notify", n)


def push_presence():
    broadcast("presence", dict(PRESENCE))


class Handler(BaseHTTPRequestHandler):
    server_version = "ExcuseGauge/0.1"

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
        self._send(code, E.dumps(obj))

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n).decode("utf-8"))

    # --- GET ---
    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            return self._json(state())
        if path == "/api/events":
            return self._events()
        name = ROUTES.get(path, path.lstrip("/"))
        f = (STATIC / name).resolve()
        if STATIC not in f.parents or not f.is_file():
            return self._send(404, "not found", "text/plain; charset=utf-8")
        ctype = mimetypes.guess_type(str(f))[0] or "application/octet-stream"
        if ctype.startswith("text/") or ctype.endswith("javascript"):
            ctype += "; charset=utf-8"
        self._send(200, f.read_bytes(), ctype)

    def _events(self):
        role = parse_qs(urlparse(self.path).query).get("role", ["phone"])[0]
        role = role if role in PRESENCE else "phone"
        q: queue.Queue = queue.Queue(maxsize=50)
        SUBSCRIBERS.append(q)
        PRESENCE[role] += 1
        push_presence()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Connection", "keep-alive")
        self.end_headers()
        try:
            self.wfile.write("event: state\ndata: {}\n\n".format(E.dumps(state())).encode("utf-8"))
            self.wfile.flush()
            while True:
                try:
                    msg = q.get(timeout=15)
                except queue.Empty:
                    msg = b": ping\n\n"          # 연결 유지
                self.wfile.write(msg)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, ssl.SSLError, OSError):
            pass
        finally:
            if q in SUBSCRIBERS:
                SUBSCRIBERS.remove(q)
            PRESENCE[role] = max(0, PRESENCE[role] - 1)
            push_presence()

    # --- POST ---
    def do_POST(self):
        path = urlparse(self.path).path
        try:
            b = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._json({"error": "JSON 이 아니다"}, 400)
        day = b.get("day") or E.today()
        try:
            with LOCK:
                if path == "/api/night":
                    E.put_night(CON, day, b["night_hr"], b.get("night_min", 0),
                                b.get("very_active_min"), b.get("asleep_min"),
                                b.get("source", "manual"))
                elif path == "/api/context":
                    E.put_context(CON, day, **{k: b[k] for k in
                                               ("alcohol", "sleep", "exercise", "tense", "nothing")
                                               if k in b})
                elif path == "/api/face":
                    E.put_face(CON, day, b.get("face_hr"), b.get("quality"),
                               b.get("L"), b.get("a"), b.get("b"))
                elif path == "/api/demo/seed":
                    E.seed_demo(CON)
                elif path == "/api/demo/night":
                    E.demo_night(CON, b.get("kind", "calm"))
                elif path == "/api/reset":
                    E.reset(CON)
                elif path == "/api/notify/ack":
                    E.ack_notice(CON, int(b["id"]))
                elif path == "/api/notify/test":
                    n = E.add_notice(CON, day, "TEST", "알림 시험",
                                     "폰과 워치에 이 팝업이 같이 떴다면 연결이 잘 된 거예요.")
                elif path == "/api/live":
                    LIVE.update(bpm=b.get("bpm"), rr=b.get("rr"), at=b.get("at"),
                                device=b.get("device"))
                else:
                    return self._json({"error": "없는 경로"}, 404)
        except KeyError as e:
            return self._json({"error": "빠진 값: {}".format(e)}, 400)
        if path == "/api/live":
            broadcast("live", LIVE)
            return self._json({"ok": True})
        if path == "/api/notify/ack":
            broadcast("dismiss", {"id": int(b["id"])})
            return self._json({"ok": True})
        if path == "/api/notify/test":
            broadcast("notify", n)
            return self._json({"ok": True})
        push_state()
        return self._json(state())


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
    global CON
    import sys
    sys.stdout.reconfigure(line_buffering=True)      # 안내 문구가 바로 보이게
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--https", action="store_true", help="폰에서 카메라·블루투스를 쓰려면")
    ap.add_argument("--demo", action="store_true", help="기록이 비어 있으면 시연용 지난 기록을 채운다")
    args = ap.parse_args()

    CON = E.connect()
    if args.demo and CON.execute("SELECT COUNT(*) FROM nights").fetchone()[0] == 0:
        E.seed_demo(CON)

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

    print("핑계 게이지 서버")
    print("  이 컴퓨터   {}://localhost:{}/        (폰 화면)".format(scheme, args.port))
    print("             {}://localhost:{}/watch   (워치 화면)".format(scheme, args.port))
    print("  같은 와이파이의 폰·워치에서")
    print("             {}://{}:{}/".format(scheme, ip, args.port))
    print("             {}://{}:{}/watch".format(scheme, ip, args.port))
    if not args.https:
        print("  * 폰에서 카메라·블루투스를 쓰려면 --https 로 다시 켤 것")
    print("  종료: Ctrl+C")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
