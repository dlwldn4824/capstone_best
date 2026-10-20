// Run any table script with pipeline constants overridden (for A/B of design choices).
// LO=0.7 H=2 node scripts/robustness/variant.js 05_harmonic
import { SPEC_OPTS, PULSE_FILTER } from '../../src/pipeline/index.js';
if (process.env.LO) PULSE_FILTER[0] = +process.env.LO;
if (process.env.H) SPEC_OPTS.harmonics = +process.env.H;
if (process.env.SUB === '0') SPEC_OPTS.subharmonic = null;
console.log(`\n> variant LO=${PULSE_FILTER[0]} H=${SPEC_OPTS.harmonics} SUB=${JSON.stringify(SPEC_OPTS.subharmonic)}`);
await import(`./${process.argv[2]}.js`);
