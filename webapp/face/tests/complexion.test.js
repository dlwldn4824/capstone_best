import { describe, it, expect } from 'vitest';
import { complexionOf, toLab, COMPLEXION } from '../src/pipeline/complexion.js';
import { analyze } from '../src/pipeline/index.js';
import { synthSamples } from '../src/debug/synth.js';

// 이마 · 양 볼 색을 직접 정해 만든 샘플 (맥박은 보지 않는다)
function rows(n, forehead, cheek, scale = 1) {
  const mul = c => c.map(v => Math.min(255, v * scale));
  const fh = mul(forehead), ck = mul(cheek);
  const brightness = (fh[0] + fh[1] + fh[2] + 2 * (ck[0] + ck[1] + ck[2])) / 9;
  return Array.from({ length: n }, (_, i) => ({
    t: i * (1000 / 30), forehead: fh, lcheek: ck, rcheek: ck,
    faceWidth: 200, faceCenter: [320, 240], brightness, blink: 0, mouthOpen: 0,
  }));
}

describe('안색: 볼 a* − 이마 a*', () => {
  it('sRGB → Lab 이 알려진 값과 맞는다', () => {
    const [L, a, b] = toLab(255, 255, 255);
    expect(L).toBeCloseTo(100, 1);
    expect(Math.abs(a)).toBeLessThan(0.01);
    expect(Math.abs(b)).toBeLessThan(0.05);   // 반올림한 변환 행렬이라 흰색에서도 0.01 정도는 남는다
    const red = toLab(255, 0, 0);
    expect(red[1]).toBeGreaterThan(70);      // 빨강은 a* 가 크게 양수
  });

  it('볼이 이마보다 붉으면 delta 가 양수, 같으면 0', () => {
    const redder = complexionOf(rows(300, [150, 110, 95], [168, 108, 94]));
    expect(redder.delta).toBeGreaterThan(0.5);
    expect(redder.reliable).toBe(true);

    const same = complexionOf(rows(300, [150, 110, 95], [150, 110, 95]));
    expect(Math.abs(same.delta)).toBeLessThan(1e-9);
  });

  it('조명이 세지면 절대 붉은 기는 흔들리지만 볼−이마 차이는 훨씬 덜 움직인다', () => {
    const fh = [150, 110, 95], ck = [168, 108, 94];
    const base = complexionOf(rows(300, fh, ck, 1.0));
    const dim = complexionOf(rows(300, fh, ck, 0.8));
    const bright = complexionOf(rows(300, fh, ck, 1.2));

    const absSwing = Math.max(Math.abs(dim.cheekA - base.cheekA), Math.abs(bright.cheekA - base.cheekA));
    const relSwing = Math.max(Math.abs(dim.delta - base.delta), Math.abs(bright.delta - base.delta));
    expect(absSwing).toBeGreaterThan(0.3);        // 절대값은 조명 따라 움직인다
    expect(relSwing).toBeLessThan(absSwing / 2);  // 차이는 그 절반도 안 움직인다
  });

  it('5초(150프레임)보다 짧으면 값을 내지 않는다', () => {
    const short = complexionOf(rows(COMPLEXION.minFrames - 1, [150, 110, 95], [168, 108, 94]));
    expect(Number.isNaN(short.delta)).toBe(true);
    expect(short.reliable).toBe(false);
    expect(short.reason).toBe('short');
  });

  it('너무 어두우면 재긴 하되 믿을 수 없다고 표시한다', () => {
    const dark = complexionOf(rows(300, [30, 22, 19], [34, 22, 19]));
    expect(Number.isFinite(dark.delta)).toBe(true);
    expect(dark.reliable).toBe(false);
    expect(dark.reason).toBe('brightness');
  });

  it('analyze() 결과에 실리고, 품질 판정과 점수에는 끼어들지 않는다', () => {
    const clean = analyze(synthSamples({ bpm: 72, noise: 0.2 }));
    expect(Number.isFinite(clean.complexion.delta)).toBe(true);
    expect(clean.complexion.frames).toBeGreaterThan(COMPLEXION.minFrames);

    // 안색이 어떻든 품질 이유에는 등장하지 않는다
    const dark = analyze(synthSamples({ brightness: 40 }));
    expect(dark.quality.reason).toBe('brightness');
    expect(Object.keys(dark.quality)).not.toContain('complexion');
  });
});
