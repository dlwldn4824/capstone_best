// 얼굴 메시로 이마 · 양 볼을 매 프레임 따라가며 평균 RGB 를 뽑는다 (기획 변경 보고서 FR-05 · FR-08).
//
// 보고서의 ARKit ARFaceAnchor 자리에 MediaPipe Face Landmarker(Apache-2.0)를 쓴다.
//   ARKit 얼굴 메시 1,220점  ↔  MediaPipe 478점
//   ARKit blendShapes 52종   ↔  MediaPipe faceBlendshapes 52종 (같은 이름: eyeBlinkLeft, jawOpen …)
//   anchor.transform         ↔  facialTransformationMatrixes
// 영상은 이 페이지 안에서 평균 색으로만 바뀌고, 프레임은 바로 버린다. 서버로 가는 것은 숫자뿐이다.
"use strict";

const FACE = (() => {
  // MediaPipe 표준 메시 번호. 눈 · 입 · 코끝 · 머리카락 경계를 피한 피부 영역 (볼은 좌우 대칭 쌍).
  const ROI = {
    forehead: [151, 108, 337, 69, 299, 109, 338],       // 이마 가운데 (눈썹 · 머리카락 경계 피함)
    cheekL: [116, 117, 118, 119, 100, 36, 205, 187, 123],
    cheekR: [345, 346, 347, 348, 329, 266, 425, 411, 352],
  };
  const NOSE = 1, FACE_L = 234, FACE_R = 454;
  const BLINK = 0.5, TALK = 0.25;

  let landmarker = null, source = "", lastPolys = null;

  async function init() {
    if (landmarker) return source;
    const tries = [
      { base: "/vendor/mediapipe/", model: "/vendor/mediapipe/face_landmarker.task", name: "로컬" },
      { base: "https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@1.1.1/",
        model: "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task", name: "CDN" },
    ];
    let last;
    for (const t of tries) {
      try {
        const vision = await import(t.base + "vision_bundle.mjs");
        const files = await vision.FilesetResolver.forVisionTasks(t.base + "wasm");
        for (const delegate of ["GPU", "CPU"]) {
          try {
            landmarker = await vision.FaceLandmarker.createFromOptions(files, {
              baseOptions: { modelAssetPath: t.model, delegate },
              runningMode: "VIDEO", numFaces: 1,
              outputFaceBlendshapes: true, outputFacialTransformationMatrixes: true,
            });
            source = t.name + " · " + delegate;
            return source;
          } catch (e) { last = e; }
        }
      } catch (e) { last = e; }
    }
    throw last || new Error("얼굴 메시를 불러오지 못했어요");
  }

  // 볼록 껍질 (점 순서와 상관없이 영역 다각형을 만든다)
  function hull(pts) {
    const p = pts.slice().sort((a, b) => a[0] - b[0] || a[1] - b[1]);
    const cross = (o, a, b) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
    const lo = [], up = [];
    for (const q of p) { while (lo.length >= 2 && cross(lo[lo.length - 2], lo[lo.length - 1], q) <= 0) lo.pop(); lo.push(q); }
    for (let i = p.length - 1; i >= 0; i--) { const q = p[i]; while (up.length >= 2 && cross(up[up.length - 2], up[up.length - 1], q) <= 0) up.pop(); up.push(q); }
    return lo.slice(0, -1).concat(up.slice(0, -1));
  }

  function inside(poly, x, y) {
    let s = 0;
    for (let i = 0; i < poly.length; i++) {
      const a = poly[i], b = poly[(i + 1) % poly.length];
      const c = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0]);
      if (c !== 0) { if (s === 0) s = Math.sign(c); else if (Math.sign(c) !== s) return false; }
    }
    return true;
  }

  function roiMean(img, W, H, poly) {
    let x0 = W, y0 = H, x1 = 0, y1 = 0;
    for (const [x, y] of poly) { x0 = Math.min(x0, x); y0 = Math.min(y0, y); x1 = Math.max(x1, x); y1 = Math.max(y1, y); }
    x0 = Math.max(0, Math.floor(x0)); y0 = Math.max(0, Math.floor(y0));
    x1 = Math.min(W - 1, Math.ceil(x1)); y1 = Math.min(H - 1, Math.ceil(y1));
    let r = 0, g = 0, b = 0, n = 0;
    for (let y = y0; y <= y1; y++) for (let x = x0; x <= x1; x++) {
      if (!inside(poly, x + 0.5, y + 0.5)) continue;
      const i = (y * W + x) * 4;
      r += img[i]; g += img[i + 1]; b += img[i + 2]; n++;
    }
    return n ? { rgb: [r / n, g / n, b / n], n } : null;
  }

  // 한 프레임: 얼굴 찾기 → 세 영역 평균 RGB · 깜빡임 · 말하기 · 코 위치 · 밝기
  function sample(video, canvas, tMs) {
    const W = canvas.width, H = canvas.height, ctx = canvas.getContext("2d", { willReadFrequently: true });
    const res = landmarker.detectForVideo(video, tMs);
    if (!res.faceLandmarks || !res.faceLandmarks.length) return { t: tMs, face: false };
    const lm = res.faceLandmarks[0];
    ctx.drawImage(video, 0, 0, W, H);
    const img = ctx.getImageData(0, 0, W, H).data;
    const pt = (i) => [lm[i].x * W, lm[i].y * H];
    const out = { t: tMs, face: true };
    let tr = 0, tg = 0, tb = 0, tn = 0;
    const cheek = [0, 0, 0]; let cn = 0;
    lastPolys = {};
    for (const [name, ids] of Object.entries(ROI)) {
      const poly = hull(ids.map(pt));
      lastPolys[name] = poly.map(([x, y]) => [x / W, y / H]);       // 확인용 (정규화 좌표)
      const m = roiMean(img, W, H, poly);
      if (!m) return { t: tMs, face: false };
      out[name] = m.rgb;
      tr += m.rgb[0] * m.n; tg += m.rgb[1] * m.n; tb += m.rgb[2] * m.n; tn += m.n;
      if (name !== "forehead") { for (let k = 0; k < 3; k++) cheek[k] += m.rgb[k] * m.n; cn += m.n; }
    }
    out.rgb = [tr / tn, tg / tn, tb / tn];                    // 심박용: 세 영역 합친 평균
    out.fh = out.forehead;                                     // 안색용: 이마
    out.ck = cheek.map((v) => v / cn);                         // 안색용: 양 볼
    out.lum = 0.299 * out.rgb[0] + 0.587 * out.rgb[1] + 0.114 * out.rgb[2];
    const fw = Math.hypot(lm[FACE_R].x - lm[FACE_L].x, lm[FACE_R].y - lm[FACE_L].y);
    out.nose = [lm[NOSE].x / fw, lm[NOSE].y / fw];            // 얼굴 폭으로 나눈 위치 → 거리와 무관한 움직임
    const bs = {};
    if (res.faceBlendshapes && res.faceBlendshapes[0]) for (const c of res.faceBlendshapes[0].categories) bs[c.categoryName] = c.score;
    out.blink = Math.max(bs.eyeBlinkLeft || 0, bs.eyeBlinkRight || 0);
    out.talk = bs.jawOpen || 0;
    out.skip = out.blink > BLINK || out.talk > TALK;
    out.box = { x: Math.min(...lm.map((p) => p.x)), y: Math.min(...lm.map((p) => p.y)),
                w: fw, h: Math.max(...lm.map((p) => p.y)) - Math.min(...lm.map((p) => p.y)) };
    return out;
  }

  // FR-08 품질: 밝기 · 머리 이동량 · (심박의) SNR
  const Q = { lumLo: 55, lumHi: 225, lumOk: 0.9, motionMax: 0.035, skipMax: 0.3, snrMin: 0 };

  function quality(frames, est) {
    const f = frames.filter((x) => x.face);
    if (f.length < 60) return { ok: false, why: "face", face: f.length / Math.max(1, frames.length) };
    const lumOk = f.filter((x) => x.lum >= Q.lumLo && x.lum <= Q.lumHi).length / f.length;
    const mx = f.map((x) => x.nose[0]), my = f.map((x) => x.nose[1]);
    const med = (v) => { const s = [...v].sort((a, b) => a - b); return s[s.length >> 1]; };
    const cx = med(mx), cy = med(my);
    const motion = med(f.map((x) => Math.hypot(x.nose[0] - cx, x.nose[1] - cy)));
    const skip = f.filter((x) => x.skip).length / f.length;
    const bright = f.reduce((s, x) => s + x.lum, 0) / f.length;
    const snr = est ? est.snr : -99;
    let why = "";
    if (lumOk < Q.lumOk) why = "light";
    else if (motion > Q.motionMax || skip > Q.skipMax) why = "move";
    else if (snr < Q.snrMin) why = "signal";
    return { ok: !why, why, bright, motion, skip, lumOk, snr, face: f.length / frames.length };
  }

  return { init, sample, quality, ROI, Q, source: () => source, lastPolys: () => lastPolys };
})();
