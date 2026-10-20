// 개발 서버 · 빌드 전에 저장소에 넣지 않는 파일을 채운다 (npm 의 predev · prebuild).
//
//   shared-assets/{characters,fonts}/   ← ../../assets (저장소 공용 에셋 사본, git 제외)
//   public/mediapipe/*.js|*.wasm        ← node_modules/@mediapipe/tasks-vision/wasm
//   public/mediapipe/face_landmarker.task
//       ← ../static/vendor/mediapipe/ (python webapp/fetch_vendor.py 로 받은 같은 모델) 이 있으면 복사,
//         없으면 MODEL_URL 에서 한 번 받는다. 받는 건 빌드할 때뿐이고, 앱은 실행 중에 같은 서버에서만 받는다.
//
// 주소: 앱은 캐릭터 · 글꼴을 base(/face/) 밖의 /assets/… 로 부른다. /check 와 같은 주소 · 같은 파일이다.
//   python webapp/server.py  → 저장소 assets/ 를 /assets/… 로 내보낸다 (STATIC_ROOTS). dist 에는 들어가지 않는다
//   단독 nginx (Dockerfile)  → 이 사본(shared-assets/)을 /assets/… 에 둔다
//   vite dev · preview       → vite.config.js 의 미들웨어가 이 사본을 /assets/… 로 내보낸다
// public/ 이나 assets/ 에 두지 않는 까닭: vite 가 그 파일을 찾으면 주소를 /face/assets/… 로 바꿔 버린다.
// 찾지 못하면 /assets/… 를 그대로 둔다 (빌드 경고 한 줄은 정상).
// 단독 Docker 빌드에는 ../../assets 가 없으므로, 업로드된 shared-assets/ 사본을 그대로 쓴다.
import { copyFileSync, cpSync, existsSync, mkdirSync, readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const ROOT = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const PUB = join(ROOT, 'public');
const REPO_ASSETS = resolve(ROOT, '../../assets');
const VENDOR_MODEL = resolve(ROOT, '../static/vendor/mediapipe/face_landmarker.task');
const WASM_DIR = join(ROOT, 'node_modules/@mediapipe/tasks-vision/wasm');
const MODEL_URL = 'https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task';
const MODEL_SHA256 = '64184e229b263107bc2b804c6625db1341ff2bb731874b0bcc2fe6544e0bc9ff';   // float16 v1

const sha256 = buf => createHash('sha256').update(buf).digest('hex');
const fail = msg => { console.error(`sync-assets: ${msg}`); process.exit(1); };

// 1. 캐릭터 · 글꼴
const assetsOut = join(ROOT, 'shared-assets');
if (existsSync(REPO_ASSETS)) {
  for (const sub of ['characters', 'fonts']) cpSync(join(REPO_ASSETS, sub), join(assetsOut, sub), { recursive: true });
  console.log('sync-assets: assets ← ../../assets');
} else if (!existsSync(join(assetsOut, 'fonts/PretendardVariable.woff2'))) {
  fail('../../assets 도 shared-assets/ 사본도 없어요. 저장소 안(webapp/face)에서 npm run build 를 먼저 한 번 실행해 주세요.');
}

// 2. MediaPipe wasm (package.json 의 @mediapipe/tasks-vision 버전과 항상 같다)
const mpOut = join(PUB, 'mediapipe');
mkdirSync(mpOut, { recursive: true });
if (!existsSync(WASM_DIR)) fail('node_modules/@mediapipe/tasks-vision 이 없어요. npm ci 를 먼저 실행해 주세요.');
for (const f of readdirSync(WASM_DIR)) copyFileSync(join(WASM_DIR, f), join(mpOut, f));

// 3. 얼굴 모델
const modelOut = join(mpOut, 'face_landmarker.task');
const okModel = p => existsSync(p) && sha256(readFileSync(p)) === MODEL_SHA256;
if (okModel(modelOut)) {
  console.log('sync-assets: face_landmarker.task 있음');
} else if (okModel(VENDOR_MODEL)) {
  copyFileSync(VENDOR_MODEL, modelOut);
  console.log('sync-assets: face_landmarker.task ← ../static/vendor/mediapipe');
} else {
  console.log(`sync-assets: face_landmarker.task 받는 중 (${MODEL_URL})`);
  const res = await fetch(MODEL_URL);
  if (!res.ok) fail(`모델을 받지 못했어요 (HTTP ${res.status})`);
  const buf = Buffer.from(await res.arrayBuffer());
  if (sha256(buf) !== MODEL_SHA256) fail('받은 모델의 SHA-256 이 기대값과 달라요.');
  writeFileSync(modelOut, buf);
  console.log(`sync-assets: face_landmarker.task 받음 (${buf.length} bytes)`);
}
