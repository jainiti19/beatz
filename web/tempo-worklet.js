/* Pitch-preserving tempo change for the web player.
 *
 * WHY IT IS SHAPED LIKE THIS. A time-stretcher cannot exist as a Web Audio
 * node: the graph pulls a fixed 128 samples per quantum, so nothing
 * downstream can make the sources upstream of it play slower. A pitch-shifter
 * can, because it consumes and produces at the same rate. So tempo is two
 * halves that cancel:
 *
 *   1. every stem source runs at playbackRate = r   -> slower, key drops by r
 *   2. this one node on the master bus lifts by 1/r -> key restored
 *
 * Net: the beat slows, the key stays put. One shifter on the mix rather than
 * four on the stems, so the mixer keeps working live and a phone pays once.
 *
 * The shifter is the textbook pair: stretch time by p without touching pitch
 * (WSOLA), then resample by p to put the duration back. The resampling is what
 * moves the key; the WSOLA is what stops the duration moving with it.
 *
 * Runs in Node too (the guards at the bottom) so the algorithm can be tested
 * against real audio without a browser.
 */

// Hann at 50% overlap sums to a constant, so overlap-add needs no normalising.
function hann(n) {
  const w = new Float32Array(n);
  for (let i = 0; i < n; i++) w[i] = 0.5 - 0.5 * Math.cos((2 * Math.PI * i) / n);
  return w;
}

/* Streaming WSOLA + resampler. Push input, pull the same number of samples
 * back out, pitch-shifted by `p` with the duration untouched. */
class StreamShifter {
  constructor(p, nCh, opt = {}) {
    this.nCh = nCh;
    this.N = opt.frame || 2048;          // grain length
    this.Hs = this.N >> 1;               // synthesis hop (50% overlap)
    this.tol = opt.tol || 256;           // how far a grain may slide to fit
    this.corrLen = opt.corrLen || 320;   // samples compared when sliding it
    this.win = hann(this.N);

    // Circular buffers. Capacities are powers of two so the index wrap is a
    // mask rather than a modulo — this runs inside the audio callback.
    this.IC = 16384; this.IM = this.IC - 1;
    this.AC = 8192;  this.AM = this.AC - 1;

    this.inp = [];  // input, per channel
    this.acc = [];  // overlap-added stretched output, per channel
    for (let c = 0; c < nCh; c++) {
      this.inp.push(new Float32Array(this.IC));
      this.acc.push(new Float32Array(this.AC));
    }
    this.mono = new Float32Array(this.IC);  // channel sum, for the search only

    this.inWrite = 0;    // absolute index of the next input sample to arrive
    this.grain = 0;      // grains emitted
    this.prevPos = 0;    // absolute input index the last grain came from
    this.rpos = 0;       // absolute read position in the stretched timeline
    // The first grain cannot be built until enough input exists to window it
    // and to run the search over. Emitting silence until then costs one fixed
    // delay; letting it fail per-quantum instead chops the first tenth of a
    // second into alternating audio and silence, which is audible on every
    // play. Same total latency either way -- this way it is a clean delay.
    this.warmup = this.N + this.tol + this.Hs;
    this.setRatio(p);
  }

  setRatio(p) {
    this.p = p;
    this.Ha = this.Hs / p;   // analysis hop: below Hs stretches, above compresses
  }

  /* Absolute stretched samples below this are final — no later grain can
   * still add to them. Grain g covers [g*Hs, g*Hs + 2*Hs). */
  get finalUpTo() { return this.grain * this.Hs; }

  push(chans, n) {
    for (let i = 0; i < n; i++) {
      const w = (this.inWrite + i) & this.IM;
      let sum = 0;
      for (let c = 0; c < this.nCh; c++) { const v = chans[c][i]; this.inp[c][w] = v; sum += v; }
      this.mono[w] = sum / this.nCh;
    }
    this.inWrite += n;
  }

  /* Emit one grain, or return false if the input for it has not arrived. */
  makeGrain() {
    const { N, Hs, tol, corrLen } = this;
    const nominal = Math.round(this.grain * this.Ha);
    let pos = nominal;

    // Everything the grain and its search will touch must still be in the
    // buffer: not yet arrived, and not yet overwritten by the wrap.
    const need = nominal + tol + N;
    if (need > this.inWrite) return false;
    const oldest = this.inWrite - this.IC + 1;
    if (this.grain > 0 && nominal - tol < oldest) return false;

    if (this.grain > 0) {
      // The template is what would have come next had we kept reading straight
      // on from the previous grain. Find the input that most looks like it, so
      // the seam lands where the waveform already agrees. Without this the
      // periods collide at every hop and it sounds like a flanger.
      const tStart = this.prevPos + Hs;
      let best = -Infinity, bestPos = nominal;
      for (let cand = nominal - tol; cand <= nominal + tol; cand++) {
        if (cand < 0) continue;
        let dot = 0, energy = 0;
        for (let k = 0; k < corrLen; k++) {
          const a = this.mono[(tStart + k) & this.IM];
          const b = this.mono[(cand + k) & this.IM];
          dot += a * b;
          energy += b * b;
        }
        // Normalised: without dividing out the candidate's own energy the
        // search just walks to the loudest moment nearby, not the best match.
        const score = dot / Math.sqrt(energy + 1e-9);
        if (score > best) { best = score; bestPos = cand; }
      }
      pos = bestPos;
    }

    const base = this.grain * Hs;
    // The first half already carries the previous grain's tail; the second
    // half is new ground and has to be cleared before it is added into.
    for (let k = Hs; k < N; k++) {
      const a = (base + k) & this.AM;
      for (let c = 0; c < this.nCh; c++) this.acc[c][a] = 0;
    }
    for (let k = 0; k < N; k++) {
      const a = (base + k) & this.AM;
      const w = this.win[k];
      const s = (pos + k) & this.IM;
      for (let c = 0; c < this.nCh; c++) this.acc[c][a] += this.inp[c][s] * w;
    }

    this.prevPos = pos;
    this.grain++;
    return true;
  }

  /* Fill n frames of output. Returns false on underrun (start-up only). */
  pull(out, n) {
    if (this.inWrite < this.warmup) {
      for (let c = 0; c < this.nCh; c++) out[c].fill(0, 0, n);
      return false;
    }
    for (let i = 0; i < n; i++) {
      // Cubic needs one sample either side, so wait until rpos+2 is final.
      while (this.rpos + 2 >= this.finalUpTo) {
        if (!this.makeGrain()) {
          for (let k = i; k < n; k++) for (let c = 0; c < this.nCh; c++) out[c][k] = 0;
          return false;
        }
      }
      const i1 = Math.floor(this.rpos);
      const f = this.rpos - i1;
      for (let c = 0; c < this.nCh; c++) {
        const A = this.acc[c];
        const a = A[(i1 - 1) & this.AM], b = A[i1 & this.AM];
        const cc = A[(i1 + 1) & this.AM], d = A[(i1 + 2) & this.AM];
        // Catmull-Rom: linear interpolation audibly dulls the top end, and
        // these are already lossy mp3s.
        out[c][i] = b + 0.5 * f * (cc - a + f * (2 * a - 5 * b + 4 * cc - d + f * (3 * (b - cc) + d - a)));
      }
      this.rpos += this.p;
    }
    return true;
  }
}

if (typeof registerProcessor === 'function') {
  class TempoProcessor extends AudioWorkletProcessor {
    constructor(options) {
      super();
      const p = (options.processorOptions && options.processorOptions.pitch) || 1;
      this.shifter = null;
      this.pitch = p;
      // A ratio of 1 must cost nothing: at normal speed the audio has to reach
      // the speakers byte-for-byte as before, or every song is "improved".
      this.port.onmessage = (e) => {
        if (e.data && typeof e.data.pitch === 'number') {
          this.pitch = e.data.pitch;
          this.shifter = null;   // rebuilt lazily so state never half-updates
        }
      };
    }

    process(inputs, outputs) {
      const input = inputs[0], output = outputs[0];
      if (!input || input.length === 0) return true;
      const n = output[0].length;

      if (Math.abs(this.pitch - 1) < 1e-6) {
        for (let c = 0; c < output.length; c++) {
          if (input[c]) output[c].set(input[c]);
          else output[c].fill(0);
        }
        return true;
      }

      // Rebuilt, never re-ratioed in place: the grain counter and the read
      // position are both denominated in the old ratio, so changing it live
      // jumps the analysis position and tears. A rebuild costs one 72ms
      // warm-up, which is what a speed button should sound like anyway.
      if (!this.shifter || this.shifter.nCh !== output.length) {
        this.shifter = new StreamShifter(this.pitch, output.length);
      }
      const chans = [];
      for (let c = 0; c < output.length; c++) chans.push(input[c] || new Float32Array(n));
      this.shifter.push(chans, n);
      this.shifter.pull(output, n);
      return true;
    }
  }
  registerProcessor('tempo-processor', TempoProcessor);
}

if (typeof module !== 'undefined' && module.exports) {
  module.exports = { hann, StreamShifter };
}
