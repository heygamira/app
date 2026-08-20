package com.gamira.parent.wakeword

import android.content.Context
import org.json.JSONObject
import java.io.ByteArrayOutputStream
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * The wake-word bundle, read straight out of the app's own assets.
 *
 * `python main.py export-web` writes `public/wake/manifest.json` and a
 * versioned directory beside it; `npx cap sync` then copies the built `dist/`
 * — this bundle included — into `android/app/src/main/assets/public`. So this
 * reads exactly the same files the WebView's `bundle.js` fetches over
 * `https://localhost/wake/...`, just from the APK's asset store instead of a
 * network round trip — the model that reads is always the model that shipped,
 * because both come from the one build.
 */
class WakeBundle private constructor(
    val manifest: JSONObject,
    val spec: WakeFrontendSpec,
    val filterbank: DoubleArray,
    val window: DoubleArray,
    val modelBytes: ByteArray,
) {
    val wakeWord: String get() = manifest.optString("wake_word", "")

    companion object {
        private const val ROOT = "public/wake"

        fun load(context: Context): WakeBundle {
            val assets = context.assets
            val manifest = JSONObject(readText(assets, "$ROOT/manifest.json"))

            val bundleVersion = manifest.optInt("bundle_version", 1)
            if (bundleVersion > 1) {
                throw IllegalStateException(
                    "wake bundle v$bundleVersion is newer than this app understands (v1); rebuild the app",
                )
            }

            val frontendPath = manifest.getString("frontend")
            val filterbankPath = manifest.getString("filterbank")
            val windowPath = manifest.getString("window")
            val modelPath = manifest.getString("model")

            val spec = WakeFrontendSpec.fromJson(JSONObject(readText(assets, "$ROOT/$frontendPath")))
            val filterbank = readFloat32(assets, "$ROOT/$filterbankPath")
            val window = readFloat32(assets, "$ROOT/$windowPath")
            val modelBytes = readBytes(assets, "$ROOT/$modelPath")

            return WakeBundle(manifest, spec, filterbank, window, modelBytes)
        }

        private fun readText(assets: android.content.res.AssetManager, path: String): String =
            assets.open(path).bufferedReader(Charsets.UTF_8).use { it.readText() }

        private fun readBytes(assets: android.content.res.AssetManager, path: String): ByteArray =
            assets.open(path).use { stream ->
                val out = ByteArrayOutputStream()
                stream.copyTo(out)
                out.toByteArray()
            }

        /** Little-endian float32, matching `new Float32Array(arrayBuffer)` on the web side. */
        private fun readFloat32(assets: android.content.res.AssetManager, path: String): DoubleArray {
            val bytes = readBytes(assets, path)
            val buffer = ByteBuffer.wrap(bytes).order(ByteOrder.LITTLE_ENDIAN)
            val count = bytes.size / 4
            val out = DoubleArray(count)
            for (i in 0 until count) out[i] = buffer.getFloat(i * 4).toDouble()
            return out
        }
    }
}
