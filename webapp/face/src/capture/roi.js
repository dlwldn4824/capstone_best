// ROI 폴리곤(MediaPipe 478 랜드마크 인덱스)과 영역 평균 RGB 계산.
// 인덱스를 바꾸고 싶으면 여기만 수정한다. 눈·입·코끝은 제외.

export const ROI_INDEX = {
  // 이마: 눈썹 위 ~ 헤어라인 아래. 시계 방향
  forehead: [10, 338, 297, 332, 284, 333, 299, 337, 151, 108, 69, 104, 54, 103, 67, 109],
  // 왼볼(화면 기준 왼쪽 = 사용자 오른쪽 볼이 아니라, 랜드마크 좌표계 기준 왼쪽)
  lcheek: [50, 101, 118, 117, 111, 116, 123, 147, 187, 207, 205, 36],
  // 오른볼
  rcheek: [280, 330, 347, 346, 340, 345, 352, 376, 411, 427, 425, 266],
};
// 얼굴 폭 기준점(양쪽 광대 바깥) 과 중심점
export const FACE_WIDTH_PAIR = [234, 454];
export const FACE_CENTER_IDX = 1; // 코끝

export class RoiSampler {
  constructor(w = 160, h = 120) {
    this.canvas = typeof OffscreenCanvas !== 'undefined' ? new OffscreenCanvas(w, h) : Object.assign(document.createElement('canvas'), { width: w, height: h });
    this.ctx = this.canvas.getContext('2d', { willReadFrequently: true });
    this.w = w; this.h = h;
  }

  // videoEl 프레임을 축소해 그린 뒤 ROI별 평균 RGB와 얼굴 밝기를 계산.
  // landmarks: 0–1 정규화 좌표. 반환: { forehead, lcheek, rcheek, brightness, faceWidth, faceCenter, polys }
  sample(videoEl, landmarks, videoW, videoH) {
    const { ctx, w, h } = this;
    ctx.drawImage(videoEl, 0, 0, w, h);
    const img = ctx.getImageData(0, 0, w, h).data;
    const out = { polys: {}, valid: true };
    let faceSum = 0, faceN = 0;
    for (const [name, idx] of Object.entries(ROI_INDEX)) {
      const poly = idx.map(i => [landmarks[i].x * w, landmarks[i].y * h]);
      out.polys[name] = idx.map(i => [landmarks[i].x * videoW, landmarks[i].y * videoH]);
      const [minx, maxx] = [Math.max(0, Math.floor(Math.min(...poly.map(p => p[0])))), Math.min(w - 1, Math.ceil(Math.max(...poly.map(p => p[0]))))];
      const [miny, maxy] = [Math.max(0, Math.floor(Math.min(...poly.map(p => p[1])))), Math.min(h - 1, Math.ceil(Math.max(...poly.map(p => p[1]))))];
      let r = 0, g = 0, b = 0, n = 0;
      for (let y = miny; y <= maxy; y++) for (let x = minx; x <= maxx; x++) {
        if (!pointInPoly(x + 0.5, y + 0.5, poly)) continue;
        const o = (y * w + x) * 4;
        r += img[o]; g += img[o + 1]; b += img[o + 2]; n++;
      }
      out[name] = n ? [r / n, g / n, b / n] : [0, 0, 0];
      if (n < 4) out.valid = false;                 // 영역이 화면 밖이거나 너무 작다 → 이 프레임은 쓰지 않는다
      faceSum += (r + g + b) / 3; faceN += n;
    }
    out.brightness = faceN ? faceSum / faceN : 0;
    const a = landmarks[FACE_WIDTH_PAIR[0]], b2 = landmarks[FACE_WIDTH_PAIR[1]];
    out.faceWidth = Math.hypot((a.x - b2.x) * videoW, (a.y - b2.y) * videoH);
    const c = landmarks[FACE_CENTER_IDX];
    out.faceCenter = [c.x * videoW, c.y * videoH];
    return out;
  }
}

function pointInPoly(x, y, poly) {
  let inside = false;
  for (let i = 0, j = poly.length - 1; i < poly.length; j = i++) {
    const [xi, yi] = poly[i], [xj, yj] = poly[j];
    if ((yi > y) !== (yj > y) && x < (xj - xi) * (y - yi) / (yj - yi) + xi) inside = !inside;
  }
  return inside;
}
