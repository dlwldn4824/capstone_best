import { describe, it, expect } from 'vitest';
import { framingIssue, measureFraming } from '../src/capture/framing.js';
import { poseFromMatrix } from '../src/capture/facemesh.js';

const good = { found: true, size: 0.78, dx: 0, dy: 0, pose: { yaw: 2, pitch: 5, roll: 1 }, brightness: 140, shake: 0.005, mouthOpen: 0.05 };

describe('자세 안내', () => {
  it('좋은 자세면 ready', () => expect(framingIssue(good)).toMatchObject({ ok: true, issue: 'ready' }));
  it('우선순위: 얼굴 없음 → 거리 → 위치 → 각도 → 밝기 → 흔들림 → 입', () => {
    expect(framingIssue({ found: false }).issue).toBe('noface');
    expect(framingIssue({ ...good, size: 0.4, dx: 0.5, brightness: 20 }).issue).toBe('far');
    expect(framingIssue({ ...good, size: 1.1 }).issue).toBe('near');
    expect(framingIssue({ ...good, dx: 0.2, brightness: 20 }).issue).toBe('center');
    expect(framingIssue({ ...good, pose: { yaw: 25, pitch: 0, roll: 0 } }).issue).toBe('angle');
    expect(framingIssue({ ...good, pose: { yaw: 0, pitch: -25, roll: 0 } }).issue).toBe('angle');
    expect(framingIssue({ ...good, brightness: 50 }).issue).toBe('dark');
    expect(framingIssue({ ...good, brightness: 240 }).issue).toBe('bright');
    expect(framingIssue({ ...good, shake: 0.05 }).issue).toBe('shake');
    expect(framingIssue({ ...good, mouthOpen: 0.7 }).issue).toBe('mouth');
  });
  it('각도 정보가 없으면 각도는 건너뛴다', () => expect(framingIssue({ ...good, pose: null }).ok).toBe(true));
  it('measureFraming: 타원 중심에 타원 폭 80% 얼굴', () => {
    const lm = []; for (let i = 0; i < 478; i++) lm.push({ x: 0.5, y: 0.5 });
    lm[234] = { x: 0.3, y: 0.5 }; lm[454] = { x: 0.7, y: 0.5 }; lm[10] = { x: 0.5, y: 0.25 }; lm[152] = { x: 0.5, y: 0.75 };
    const m = measureFraming(lm, (x, y) => [x * 400, y * 800], { cx: 200, cy: 400, rx: 100, ry: 140 });
    expect(m.size).toBeCloseTo(0.8, 5);
    expect(m.dx).toBeCloseTo(0, 5);
    expect(m.dy).toBeCloseTo(0, 5);
  });
  it('poseFromMatrix: 단위 행렬은 0°, y축 20° 회전은 yaw 20°', () => {
    const I = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1];
    const p0 = poseFromMatrix(I);
    expect(Math.abs(p0.yaw) + Math.abs(p0.pitch) + Math.abs(p0.roll)).toBeLessThan(1e-9);
    const a = 20 * Math.PI / 180, c = Math.cos(a), s = Math.sin(a);
    const Ry = [c, 0, -s, 0, 0, 1, 0, 0, s, 0, c, 0, 0, 0, 0, 1];   // 열 우선
    const p = poseFromMatrix(Ry);
    expect(Math.abs(p.yaw)).toBeCloseTo(20, 5);
    expect(Math.abs(p.pitch)).toBeLessThan(1e-6);
    expect(Math.abs(p.roll)).toBeLessThan(1e-6);
  });
});
