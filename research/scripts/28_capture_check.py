"""Vity 체크(/check) 화면을 하나씩 캡처 — 헤드리스 Chrome + DevTools 프로토콜 (docs/app/screens).

    python webapp/server.py                      # 다른 창에서 서버 켜 두기
    pip install websocket-client
    python research/scripts/28_capture_check.py [docs/app/screens] [http://localhost:8000]
카메라는 헤드리스에서 쓸 수 없어 스캔 화면은 MediaPipe 표준 얼굴 메시(모델 파일 안의 468점)를 그려 넣는다.
"""
import base64
import json
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from pathlib import Path

import websocket

REPO = Path(__file__).resolve().parents[2]
OUT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else REPO / "docs/app/screens"
OUT.mkdir(parents=True, exist_ok=True)
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:8000"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
W, H = 390, 844


def post(path, body):
    req = urllib.request.Request(BASE + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    return json.loads(urllib.request.urlopen(req).read())


# 시연 데이터: 이 캡처 전용 사람
post("/api/c/demo", {"member": "cap-demo", "nick": "하린"})

# 표준 얼굴 메시 → 정면 랜드마크
b = zipfile.ZipFile(REPO / "webapp/static/vendor/mediapipe/face_landmarker.task").read("geometry_pipeline_metadata_landmarks.binarypb")
fl = [struct.unpack("<f", b[8 + 5 * k + 1: 8 + 5 * k + 5])[0] for k in range(2340)]
LM = [{"x": round(0.5 + fl[k * 5] * 15 / 640, 5), "y": round(0.47 - fl[k * 5 + 1] * 15 / 480, 5)} for k in range(468)]

prof = tempfile.mkdtemp()
proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={prof}", "--hide-scrollbars",
                         f"--window-size={W},{H}", "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
for _ in range(50):
    try:
        tabs = json.loads(urllib.request.urlopen("http://127.0.0.1:9333/json").read())
        page = next(t for t in tabs if t["type"] == "page")
        break
    except Exception:
        time.sleep(0.2)
ws = websocket.create_connection(page["webSocketDebuggerUrl"], max_size=None, suppress_origin=True)
_id = [0]


def cdp(method, **params):
    _id[0] += 1
    ws.send(json.dumps({"id": _id[0], "method": method, "params": params}))
    while True:
        m = json.loads(ws.recv())
        if m.get("id") == _id[0]:
            if "error" in m:
                raise RuntimeError(method + ": " + str(m["error"]))
            return m.get("result", {})


def size(h=H):
    cdp("Emulation.setDeviceMetricsOverride", width=W, height=int(h), deviceScaleFactor=2, mobile=True)


def ev(js):
    r = cdp("Runtime.evaluate", expression="(async () => { " + js + " })()", awaitPromise=True, returnByValue=True)
    if r.get("exceptionDetails"):
        raise RuntimeError(js[:80] + " → " + json.dumps(r["exceptionDetails"])[:300])
    return r.get("result", {}).get("value")


def nav(url, wait=1.6):
    cdp("Page.navigate", url=url)
    time.sleep(wait)


def shot(name, wait=0.5, full=False):
    time.sleep(wait)
    if full:
        h = ev("return Math.max(document.documentElement.scrollHeight, document.body.scrollHeight);")
        size(max(H, h))
        time.sleep(0.3)
    data = cdp("Page.captureScreenshot", format="png")["data"]
    (OUT / (name + ".png")).write_bytes(base64.b64decode(data))
    if full:
        size()
    print("✓", name)


cdp("Page.enable")
cdp("Runtime.enable")
size()

# ---- 1. 인트로 5단계 (처음 온 사람) ----
nav(BASE + "/check")
ev("localStorage.clear(); localStorage.setItem('vity.mid', 'cap-new-' + Date.now());")
nav(BASE + "/check")
shot("01_intro_1_hello", 1.0)
ev("ME.save('하린'); OB.step = 1; renderOnb();")
shot("02_intro_2_name", 0.9)
ev("OB.step = 2; renderOnb();")
shot("03_intro_3_howto", 0.9)
ev("OB.step = 3; renderOnb();")
shot("04_intro_4_group", 0.9)
ev("OB.step = 4; renderOnb();")
shot("05_intro_5_consent", 0.9)

# ---- 2. 시연 데이터가 있는 사람 ----
ev("localStorage.setItem('vity.mid', 'cap-demo'); localStorage.setItem('vity.nick', '하린');")
nav(BASE + "/check", 2.0)
shot("06_home_today")
shot("07_home_full", full=True)
ev("homeTab = 'week'; renderHome();")
shot("08_home_week")
ev("homeTab = 'base'; renderHome();")
shot("09_home_baseline")
ev("homeTab = 'today'; renderHome(); document.querySelector('.mc [data-tip=stress]').click();")
shot("10_home_help_bubble")
ev("$('tipPop').hidden = true; openPre();")
shot("11_pre_questions")

# ---- 3. 스캔 (표준 메시) ----
ev("$('pre').classList.remove('on'); window.__LM = " + json.dumps(LM) + ";"
   "await FACE.init();"
   "const lm = window.__LM, hull = (ids) => { const p = ids.map(i => [lm[i].x, lm[i].y]); const cx = p.reduce((a, q) => a + q[0], 0) / p.length, cy = p.reduce((a, q) => a + q[1], 0) / p.length;"
   " return p.sort((a, b) => Math.atan2(a[1] - cy, a[0] - cx) - Math.atan2(b[1] - cy, b[0] - cx)); };"
   "window.__P = Object.fromEntries(Object.entries(FACE.ROI).map(([k, v]) => [k, hull(v)]));"
   "$('scan').classList.add('on'); $('camBox').className = 'cam found meshon'; $('video').style.background = '#6b5e55';"
   "stepSet('face', 'ok'); $('hint').textContent = '좋아요, 그대로 있어 주세요';"
   "MESH.draw($('meshc'), {videoWidth: 640, videoHeight: 480}, {lm, tess: FACE.tessellation(), polys: window.__P, scanning: false, pulse: 0, t: 0});")
shot("12_scan_ready", 0.8)
ev("$('camBox').className = 'cam found meshon scanning'; stepSet('pulse', 'ok'); stepSet('hrv', 'doing'); ringP(0.6);"
   "$('liveBpm').textContent = '74'; $('liveUnit').textContent = 'bpm'; $('hint').textContent = '12초'; $('hint2').textContent = '그대로 편하게 숨 쉬세요';"
   "$('startBtn').textContent = '그대로 있어 주세요'; $('startBtn').disabled = true;"
   "MESH.draw($('meshc'), {videoWidth: 640, videoHeight: 480}, {lm: window.__LM, tess: FACE.tessellation(), polys: window.__P, scanning: true, pulse: 0.7, t: 600});")
shot("13_scan_measuring", 0.6)
ev("$('scan').classList.remove('on');")

# ---- 4. 결과 · 호흡 · 비교 · 타이머 · 다시 재기 ----
def result_full(name, js):
    ev(js + "; await new Promise(r => setTimeout(r, 400));")
    shot(name + "_top", 0.5)
    h = ev("const i = $('resIn'); i.style.maxHeight = 'none'; i.style.overflow = 'visible'; return i.scrollHeight + 24;")
    size(max(H, h))
    shot(name + "_full", 0.5)
    size()
    ev("$('resIn').style.maxHeight = ''; $('resIn').style.overflow = ''; $('res').classList.remove('on');")


result_full("14_result", "showResult(S.last)")
ev("const hs = await api('/api/c/history?member=cap-demo'); window.__AB = hs.find(h => h.kind === 'after_breath').id;")
result_full("15_breath_compare", "showResult(await api('/api/c/result?id=' + window.__AB + '&member=cap-demo'))")
ev("startBreath(1);")
shot("16_breathing", 3.2)
ev("cancelAnimationFrame(br.raf); $('breath').classList.remove('on'); startTimer(25, 5);")
shot("17_study_timer", 1.5)
ev("cancelAnimationFrame(TM.raf); $('timer').classList.remove('on'); showRetry('얼굴이 잘 보이지 않았어요.');")
shot("18_retry")
ev("$('res').classList.remove('on');")

# ---- 5. 그룹 ----
ev("go('group');")
shot("19_group_list", full=True)
ev("gSel = GS[0].code; gView = 'detail'; renderGroup();")
shot("20_group_detail", full=True)
ev("gView = 'list'; WZ = {step: 1, name: '기말 기상 인증방', icon: 'sleep', start: '07:00', end: '09:00', rule: ''}; renderGroup();")
shot("21_group_make_1_name")
ev("WZ.step = 2; renderGroup();")
shot("22_group_make_2_time")
ev("WZ.step = 3; WZ.rule = '벌금 1,000원 (앱 밖에서)'; renderGroup();")
shot("23_group_make_3_rule")
ev("WZ.step = 4; WZ.created = {name: '기말 기상 인증방', start: '07:00', end: '09:00', rule: '벌금 1,000원 (앱 밖에서)', code: 'K7Q2MX'}; renderGroup();")
shot("24_group_make_done")
ev("WZ = null;")

# ---- 6. 기록 · 내 정보 ----
ev("go('log'); await new Promise(r => setTimeout(r, 500));")
shot("25_records", full=True)
ev("go('me');")
shot("26_my_info", full=True)

ws.close()
proc.terminate()
print("저장:", OUT)
