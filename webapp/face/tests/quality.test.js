import { describe, it, expect } from 'vitest';
import { synthSamples } from '../src/debug/synth.js';
import { analyze } from '../src/pipeline/index.js';

describe('품질 4조건', () => {
  it('어두운 얼굴(밝기 40) → brightness 실패', () => {
    const r = analyze(synthSamples({ brightness: 40 }));
    expect(r.quality.brightnessOk).toBe(false);
    expect(r.quality.reason).toBe('brightness');
  });
  it('머리 이동 큼 → motion 실패', () => {
    const r = analyze(synthSamples({ motion: 12 }));
    expect(r.quality.motionOk).toBe(false);
  });
  it('깜빡임 40% → blink 실패', () => {
    const r = analyze(synthSamples({ blinkRate: 0.4 }));
    expect(r.quality.blinkOk).toBe(false);
  });
  it('잡음만 있는 신호 → SNR 실패', () => {
    const s = synthSamples({ noise: 30, seed: 9 });
    for (const x of s) { x.forehead = x.forehead.map(v => v); }
    const r = analyze(synthSamples({ noise: 60, seed: 9, driftAmp: 0 }));
    expect(r.quality.snrOk).toBe(false);
  });
  it('8초 미만 → short', () => {
    const r = analyze(synthSamples({ durationSec: 5 }));
    expect(r.quality.reason).toBe('short');
  });
});
