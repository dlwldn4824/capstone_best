// MediaPipe Tasks Vision FaceLandmarker (478 랜드마크 + 블렌드셰이프).
// wasm과 모델은 앱과 같은 서버(public/mediapipe/ → /face/mediapipe/)에서 받는다. 외부 요청이 없고, 카메라 프레임은 이 기기 밖으로 나가지 않는다.
import { FaceLandmarker, FilesetResolver } from '@mediapipe/tasks-vision';

export const MP_VERSION = '0.10.14';
const BASE = import.meta.env?.BASE_URL ?? '/';                    // vite base ('/face/'). 테스트(node)에서는 '/'
export const WASM_URL = BASE + 'mediapipe';                        // node_modules/@mediapipe/tasks-vision/wasm 복사본 (scripts/sync-assets.mjs)
export const MODEL_URL = BASE + 'mediapipe/face_landmarker.task';  // face_landmarker float16 v1

let landmarker = null;
// 화면에 그릴 메시 선 [시작, 끝] (계산에는 쓰지 않는다)
export const TESSELATION = (FaceLandmarker.FACE_LANDMARKS_TESSELATION || []).map(c => [c.start, c.end]);

export async function loadFaceMesh(onProgress) {
  if (landmarker) return landmarker;
  onProgress?.('wasm 불러오는 중');
  const vision = await FilesetResolver.forVisionTasks(WASM_URL);
  onProgress?.('얼굴 모델 불러오는 중');
  let last;
  for (const delegate of ['GPU', 'CPU']) {   // 일부 iOS에서 GPU 위임이 실패하면 CPU로
    try {
      landmarker = await FaceLandmarker.createFromOptions(vision, {
        baseOptions: { modelAssetPath: MODEL_URL, delegate },
        runningMode: 'VIDEO',
        numFaces: 1,
        outputFaceBlendshapes: true,
        outputFacialTransformationMatrixes: true,   // 머리 회전 각도 (정면 안내용)
      });
      break;
    } catch (e) { last = e; }
  }
  if (!landmarker) throw last;
  onProgress?.('준비 완료');
  return landmarker;
}

// 4×4 변환 행렬(열 우선) → 회전 각도(도). 단일 축 회전이면 행 · 열 순서가 바뀌어도 크기는 같다. 안내에는 절댓값만 쓴다.
export function poseFromMatrix(m) {
  if (!m || m.length < 16) return null;
  const R00 = m[0], R10 = m[1], R20 = m[2], R21 = m[6], R22 = m[10];
  const deg = 180 / Math.PI;
  return {
    pitch: Math.atan2(R21, R22) * deg,                   // 위아래 끄덕임
    yaw: Math.atan2(-R20, Math.hypot(R21, R22)) * deg,   // 좌우 돌림
    roll: Math.atan2(R10, R00) * deg,                    // 갸웃
  };
}

// 반환: { landmarks: [{x,y,z}...478] (0–1 정규화), blink: 0–1, mouthOpen: 0–1, pose: {pitch,yaw,roll}|null } 또는 null
export function detect(videoEl, tMs) {
  if (!landmarker) return null;
  const res = landmarker.detectForVideo(videoEl, tMs);
  if (!res.faceLandmarks || !res.faceLandmarks.length) return null;
  const lm = res.faceLandmarks[0];
  let blink = 0, mouthOpen = 0;
  const bs = res.faceBlendshapes?.[0]?.categories;
  if (bs) {
    const get = n => bs.find(c => c.categoryName === n)?.score ?? 0;
    blink = Math.max(get('eyeBlinkLeft'), get('eyeBlinkRight'));
    mouthOpen = get('jawOpen');
  }
  return { landmarks: lm, blink, mouthOpen, pose: poseFromMatrix(res.facialTransformationMatrixes?.[0]?.data) };
}
