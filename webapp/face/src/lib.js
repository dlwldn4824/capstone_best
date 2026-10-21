// /check 가 쓰는 공개 진입점. 이 파일만 라이브러리로 빌드해 webapp/static/vity-face.js 로 내보낸다
// (vite.lib.config.js). check.html 은 이것을 <script type="module"> 로 불러 face 와 같은 계산 · 같은 판정을 쓴다.
//
// 복사본을 만들지 않는 것이 요점이다. 두 벌이 갈라지면 한쪽만 고쳐져 데모가 거짓말을 하게 된다
// (watch/web/README.md 가 같은 이유로 경고한다).
export { loadFaceMesh, detect, TESSELATION, MP_VERSION } from './capture/facemesh.js';
export { openCamera, closeCamera, tryLockExposure } from './capture/camera.js';
export { RoiSampler } from './capture/roi.js';
export { framingIssue, measureFraming } from './capture/framing.js';
export { analyze, liveEstimate, stableEnough, quickBpm, EARLY_STOP, WINDOW, HRV_GATE, ROIS } from './pipeline/index.js';
export { assessQuality, QUALITY, ROBUST, REASON_TEXT } from './pipeline/quality.js';
export { baselineOf, deviationOf, unexplained, BASELINE, WHY, WHY_LABEL } from './pipeline/baseline.js';
export { toMetrics, stressScore, stressZone, signalOf, SI_LO, SI_HI } from './pipeline/metrics.js';
export { faceState } from './pipeline/face.js';
export { resultView, SIGNAL_GOOD_DB } from './ui/view.js';
export { createOverlay } from './ui/overlay.js';
export { EVIDENCE } from './ui/evidence.js';
export { synthSamples } from './debug/synth.js';
