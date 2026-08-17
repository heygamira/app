// Real FFT magnitude, sized once and reused.
//
// Stands in for the `scipy.fft.rfft` call in the trainer's
// `utils/audio_utils.py::Frontend._mel_uncentered`. Only the magnitude is ever
// needed, so this computes a full complex radix-2 transform with the imaginary
// input zeroed and returns |X[k]| for k in 0..n/2.
//
// The intermediates are Float64 even though the model is Float32 throughout.
// The arithmetic here is the one place where accumulated rounding could push
// the features away from what training saw, and doubles cost nothing at this
// size: 512 points, ~100 transforms a second.

/**
 * @param {number} n transform size; must be a power of two
 * @returns {(input: Float32Array, offset: number, window: Float32Array, out: Float64Array) => void}
 *   fills `out[0..n/2]` with the magnitude spectrum of `input[offset..offset+n]`
 *   multiplied by `window`
 */
export function createRfft(n) {
  if (n < 2 || (n & (n - 1)) !== 0) {
    throw new Error(`FFT size must be a power of two, got ${n}`);
  }

  let levels = 0;
  while (1 << levels < n) levels += 1;

  // Bit-reversal permutation, precomputed.
  const rev = new Uint32Array(n);
  for (let i = 0; i < n; i++) {
    let x = i;
    let r = 0;
    for (let j = 0; j < levels; j++) {
      r = (r << 1) | (x & 1);
      x >>>= 1;
    }
    rev[i] = r >>> 0;
  }

  // Twiddles for the largest stage; smaller stages stride into the same table.
  const half = n >> 1;
  const cos = new Float64Array(half);
  const sin = new Float64Array(half);
  for (let i = 0; i < half; i++) {
    const angle = (-2 * Math.PI * i) / n;
    cos[i] = Math.cos(angle);
    sin[i] = Math.sin(angle);
  }

  const re = new Float64Array(n);
  const im = new Float64Array(n);

  return function rfftMagnitude(input, offset, window, out) {
    // Window and bit-reverse in one pass.
    for (let i = 0; i < n; i++) {
      re[rev[i]] = input[offset + i] * window[i];
      im[i] = 0;
    }

    for (let size = 2; size <= n; size <<= 1) {
      const halfSize = size >> 1;
      const step = n / size;
      for (let start = 0; start < n; start += size) {
        for (let k = 0, tw = 0; k < halfSize; k++, tw += step) {
          const even = start + k;
          const odd = even + halfSize;
          const wr = cos[tw];
          const wi = sin[tw];
          const tr = re[odd] * wr - im[odd] * wi;
          const ti = re[odd] * wi + im[odd] * wr;
          re[odd] = re[even] - tr;
          im[odd] = im[even] - ti;
          re[even] += tr;
          im[even] += ti;
        }
      }
    }

    for (let k = 0; k <= half; k++) {
      out[k] = Math.hypot(re[k], im[k]);
    }
  };
}
