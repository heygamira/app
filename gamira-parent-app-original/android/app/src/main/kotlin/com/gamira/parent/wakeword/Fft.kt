package com.gamira.parent.wakeword

/**
 * Real FFT magnitude, sized once and reused.
 *
 * A direct port of `src/lib/wakeword/rfft.js` — same radix-2 iterative
 * algorithm, same bit-reversal table, same twiddle table, same Float64
 * intermediates. Only the magnitude is ever needed, so this runs a full
 * complex transform with the imaginary input zeroed and returns |X[k]| for
 * k in 0..n/2.
 */
class Fft(private val n: Int) {

    init {
        require(n >= 2 && (n and (n - 1)) == 0) { "FFT size must be a power of two, got $n" }
    }

    private val half = n / 2
    private val rev: IntArray
    private val cos: DoubleArray = DoubleArray(half)
    private val sin: DoubleArray = DoubleArray(half)
    private val re = DoubleArray(n)
    private val im = DoubleArray(n)

    init {
        var levels = 0
        while ((1 shl levels) < n) levels++

        rev = IntArray(n)
        for (i in 0 until n) {
            var x = i
            var r = 0
            for (j in 0 until levels) {
                r = (r shl 1) or (x and 1)
                x = x ushr 1
            }
            rev[i] = r
        }

        for (i in 0 until half) {
            val angle = -2.0 * Math.PI * i / n
            cos[i] = Math.cos(angle)
            sin[i] = Math.sin(angle)
        }
    }

    /**
     * Fills `out[0..n/2]` with the magnitude spectrum of
     * `input[offset..offset+n) * window`.
     */
    fun magnitude(input: DoubleArray, offset: Int, window: DoubleArray, out: DoubleArray) {
        for (i in 0 until n) {
            re[rev[i]] = input[offset + i] * window[i]
            im[i] = 0.0
        }

        var size = 2
        while (size <= n) {
            val halfSize = size / 2
            val step = n / size
            var start = 0
            while (start < n) {
                var tw = 0
                for (k in 0 until halfSize) {
                    val even = start + k
                    val odd = even + halfSize
                    val wr = cos[tw]
                    val wi = sin[tw]
                    val tr = re[odd] * wr - im[odd] * wi
                    val ti = re[odd] * wi + im[odd] * wr
                    re[odd] = re[even] - tr
                    im[odd] = im[even] - ti
                    re[even] += tr
                    im[even] += ti
                    tw += step
                }
                start += size
            }
            size = size shl 1
        }

        for (k in 0..half) out[k] = Math.hypot(re[k], im[k])
    }
}
