"""카메라 프레임이 브라우저 밖으로 나갈 길을 코드에서 막는다.

절대 규칙: 카메라 프레임 · 얼굴 영역 픽셀 · 얼굴 랜드마크는 메모리에서만 쓰고, 저장하거나 서버로 보내지 않는다.
프레임을 파일 · 스트림 · 네트워크로 내보낼 수 있는 API 가 코드에 들어오면 실패한다.
주석까지 그대로 검사한다. 주석을 정규식으로 걷어 내면 문자열 속 `/*` 같은 것에 실제 코드가 가려진다.
정말 필요하면 이 파일의 허용 목록을 고치고 PR 본문에 이유를 쓴다.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FACE_SRC = ROOT / "webapp" / "face" / "src"
STATIC = ROOT / "webapp" / "static"

# 프레임 · 캔버스 · 카메라 스트림을 파일이나 다른 곳으로 옮기는 API. 측정 엔진과 화면 어디에도 들어오면 안 된다.
FRAME_EXPORT = [
    r"\.toDataURL\s*\(",
    r"\.toBlob\s*\(",
    r"\.convertToBlob\s*\(",
    r"\bMediaRecorder\b",
    r"\bImageCapture\b",
    r"\.captureStream\s*\(",
    r"\bVideoEncoder\b",
    r"\bnew\s+VideoFrame\s*\(",
    r"\bcreateImageBitmap\s*\(",
    r"\.readPixels\s*\(",
    r"\bsendBeacon\s*\(",
    r"\bWebSocket\b",
    r"\bRTCPeerConnection\b",
]

# 측정 엔진(webapp/face/src)은 네트워크를 쓰지 않는다. 결과 숫자를 서버로 보내는 일은 /check 화면이 한다.
NETWORK = [
    r"\bfetch\s*\(",
    r"\bXMLHttpRequest\b",
    r"\bEventSource\b",
    r"\bimportScripts\s*\(",
    r"\bnew\s+Image\s*\(",
]

# 픽셀을 읽어도 되는 파일. 측정 엔진은 얼굴 영역 평균 색을 내는 roi.js 한 곳,
# 화면 쪽은 거울 기록(/)의 자체 엔진뿐이다. /check 는 측정 엔진을 불러 쓰므로 직접 읽지 않는다.
PIXEL_READ = r"\.getImageData\s*\("
PIXEL_READ_ALLOWED = {
    FACE_SRC / "capture" / "roi.js",
    STATIC / "facemesh.js",
    STATIC / "mirror.html",
}


def _name(f):
    return str(f.relative_to(ROOT)) if f.is_relative_to(ROOT) else f.name


def _hits(files, patterns):
    found = []
    for f in files:
        text = f.read_text(encoding="utf-8")
        found += [f"{_name(f)}: {p}" for p in patterns if re.search(p, text)]
    return found


def _face_files():
    files = sorted(FACE_SRC.rglob("*.js"))
    assert files, f"{FACE_SRC} 에 측정 코드가 없다"
    return files


def _static_files():
    # vity-face.js 는 webapp/face/src 를 빌드한 결과라 소스 쪽에서 검사한다. vendor/ 는 외부 라이브러리 사본
    files = sorted(
        f for f in list(STATIC.glob("*.js")) + list(STATIC.glob("*.html"))
        if not f.name.startswith("vity-face.js")
    )
    assert any(f.name == "check.html" for f in files)
    return files


def test_face_engine_has_no_frame_export():
    assert _hits(_face_files(), FRAME_EXPORT) == []


def test_face_engine_has_no_network():
    assert _hits(_face_files(), NETWORK) == []


def test_pages_have_no_frame_export():
    assert _hits(_static_files(), FRAME_EXPORT) == []


def test_pixels_are_read_only_where_allowed():
    readers = {f for f in _face_files() + _static_files() if re.search(PIXEL_READ, f.read_text(encoding="utf-8"))}
    assert sorted(_name(f) for f in readers - PIXEL_READ_ALLOWED) == []


def test_guard_sees_calls_next_to_comment_like_text(tmp_path):
    planted = tmp_path / "leak.js"
    planted.write_text(
        'input.accept = "image/*";\n'
        "const parts = path.split(/\\//);\n"
        "const url = `${p}//${h}`;\n"
        "canvas.toBlob(cb); // */\n",
        encoding="utf-8",
    )
    assert _hits([planted], FRAME_EXPORT) == [r"leak.js: \.toBlob\s*\("]
