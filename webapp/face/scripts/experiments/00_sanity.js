// Sanity: analyzeX({extract:'pos', fuse:'best'}) must reproduce src analyze() bpm / snr / pass exactly.
// node scripts/experiments/00_sanity.js
import { scan, SEEDS, bpmFor } from './motion.js';
import { analyzeX } from './methods.js';
import { analyze } from '../../src/pipeline/index.js';
let diff = 0, n = 0;
for (const sc of ['still', 'nod', 'turn', 'walk']) for (const [i, seed] of SEEDS(15).entries()) {
  const { samples } = scan({ scenario: sc, seed, bpm: bpmFor(i), motionScale: 2 });
  const a = analyze(samples), b = analyzeX(samples, {});
  n++;
  if (Math.abs(a.bpm - b.bpm) > 1e-6 || Math.abs(a.snrDb - b.snrDb) > 1e-6 || a.quality.pass !== b.quality.pass || a.hrvReliable !== b.hrvReliable) { diff++; console.log(sc, seed, a.bpm, b.bpm, a.quality.reason, b.quality.reason); }
}
console.log(`\n> sanity: analyzeX(pos,best) vs analyze(): ${n - diff}/${n} identical (bpm, snrDb, quality.pass, hrvReliable)`);
