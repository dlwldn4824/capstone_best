// 촬영 전 · 중 자세 판정. 화면의 타원(가이드)을 기준으로 얼굴 크기 · 위치 · 각도 · 밝기 · 흔들림을 보고
// 지금 고쳐야 할 것 하나만 돌려준다. UI 와 카메라를 모른다.
//
// 기준을 이렇게 잡은 이유
//   크기   볼 바깥(234–454) 폭이 타원 폭의 60–95%  — 이마 · 볼 ROI 가 160×120 축소 영상에서도 충분한 픽셀을 갖는 거리 (팔 길이, 약 30–40cm)
//   위치   얼굴 중심이 타원 중심에서 반지름의 18% 안
//   각도   좌우 · 갸웃 15° · 위아래 20° 안 — 볼 한쪽이 가려지거나 이마가 빛을 비스듬히 받으면 ROI 색이 흔들린다
//   밝기   ROI 밝기 70–215 — 품질 기준(55–225)보다 안쪽에서 안내해 측정 중 경계를 넘지 않게
//   흔들림 최근 0.5초 코끝 이동이 얼굴 폭의 2% 안 — 품질 기준(프레임 간 3.5%)보다 엄격하게

export const FRAMING = {
  sizeMin: 0.6, sizeMax: 0.95,
  centerMax: 0.18,
  yawMax: 15, rollMax: 15, pitchMax: 20,
  lightMin: 70, lightMax: 215,
  shakeMax: 0.02,
  mouthMax: 0.4,
};

export const FRAMING_TEXT = {
  noface: '얼굴을 원 안에 맞춰 주세요',
  far: '조금 더 가까이 와 주세요',
  near: '조금만 멀어져 주세요',
  center: '얼굴을 원 가운데로 옮겨 주세요',
  angle: '화면을 정면으로 봐 주세요',
  dark: '조금 더 밝은 곳으로 가 주세요',
  bright: '빛이 너무 강해요, 조금 비켜 주세요',
  shake: '휴대폰을 세워 두고 가만히 있어 주세요',
  mouth: '입을 다물고 편하게 있어 주세요',
  ready: '좋아요, 그대로 있어 주세요',
};

// m: { found, size, dx, dy, pose:{yaw,pitch,roll}|null, brightness, shake, mouthOpen }
// 반환: { ok, issue, text }
export function framingIssue(m, f = FRAMING) {
  let issue = null;
  if (!m || !m.found) issue = 'noface';
  else if (m.size < f.sizeMin) issue = 'far';
  else if (m.size > f.sizeMax) issue = 'near';
  else if (Math.hypot(m.dx, m.dy) > f.centerMax) issue = 'center';
  else if (m.pose && (Math.abs(m.pose.yaw) > f.yawMax || Math.abs(m.pose.roll) > f.rollMax || Math.abs(m.pose.pitch) > f.pitchMax)) issue = 'angle';
  else if (m.brightness < f.lightMin) issue = 'dark';
  else if (m.brightness > f.lightMax) issue = 'bright';
  else if (m.shake > f.shakeMax) issue = 'shake';
  else if (m.mouthOpen > f.mouthMax) issue = 'mouth';
  return { ok: !issue, issue: issue || 'ready', text: FRAMING_TEXT[issue || 'ready'] };
}

// 랜드마크(0–1, 원본 영상 기준) → 화면 타원 기준 크기 · 위치. map: 정규화 좌표 → 화면 px, oval: {cx, cy, rx, ry} 화면 px
export function measureFraming(lm, map, oval) {
  const [lx] = map(lm[234].x, lm[234].y), [rx] = map(lm[454].x, lm[454].y);
  const [, ty] = map(lm[10].x, lm[10].y), [, by] = map(lm[152].x, lm[152].y);
  const cx = (lx + rx) / 2, cy = (ty + by) / 2;
  return { size: Math.abs(rx - lx) / (2 * oval.rx), dx: (cx - oval.cx) / oval.rx, dy: (cy - oval.cy) / oval.ry };
}
