"""얼굴 메시(MediaPipe Face Landmarker)를 로컬에 받아둔다 — 발표장에 인터넷이 없어도 돌게.

    python webapp/fetch_vendor.py

받는 것 (약 30 MB, git 제외 — webapp/static/vendor/):
    @mediapipe/tasks-vision  (Apache-2.0)  vision_bundle.mjs + wasm
    face_landmarker.task     (Apache-2.0)  얼굴 메시 478점 + 표정 계수 52종 + 머리 자세
없으면 앱이 같은 파일을 jsdelivr / Google 저장소에서 바로 불러온다.
"""
import urllib.request
from pathlib import Path

VERSION = "1.1.1"
NPM = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{VERSION}/"
MODEL = "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
OUT = Path(__file__).resolve().parent / "static" / "vendor" / "mediapipe"
FILES = ["vision_bundle.mjs", "wasm/vision_wasm_internal.js", "wasm/vision_wasm_internal.wasm",
         "wasm/vision_wasm_nosimd_internal.js", "wasm/vision_wasm_nosimd_internal.wasm"]


def get(url, dest):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if dest.exists() and dest.stat().st_size > 0:
        print("  있음", dest.name)
        return
    with urllib.request.urlopen(url, timeout=120) as r, open(dest, "wb") as f:
        f.write(r.read())
    print("  받음", dest.name, dest.stat().st_size // 1024, "KB")


def main():
    for f in FILES:
        get(NPM + f, OUT / f)
    get(MODEL, OUT / "face_landmarker.task")
    (OUT / "VERSION").write_text(VERSION, encoding="utf-8")
    print("완료:", OUT)


if __name__ == "__main__":
    main()
