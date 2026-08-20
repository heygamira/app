package com.gamira.parent.wakeword

import android.Manifest
import android.os.Build
import com.getcapacitor.JSObject
import com.getcapacitor.PermissionState
import com.getcapacitor.Plugin
import com.getcapacitor.PluginCall
import com.getcapacitor.PluginMethod
import com.getcapacitor.annotation.CapacitorPlugin
import com.getcapacitor.annotation.Permission
import com.getcapacitor.annotation.PermissionCallback
import org.json.JSONObject

/**
 * The wake-word detector's bridge into the WebView.
 *
 * `src/lib/wakeword/engine.js` talks to this instead of spinning up its own
 * `getUserMedia` + AudioWorklet + Worker pipeline when running inside the
 * native app, because that pipeline dies the moment the screen locks — see
 * `WakeWordService` for why. The event names and payload shapes mirror
 * `worker.js`'s `postMessage` calls exactly (`ready`, `score`… `maybe`,
 * `detect`, `release`, `error`), so the JS-side state machine in
 * `useWakeWord.js` needs no changes at all — only `engine.js` knows this
 * plugin exists.
 */
@CapacitorPlugin(
    name = "WakeWord",
    permissions = [
        Permission(alias = "microphone", strings = [Manifest.permission.RECORD_AUDIO]),
        Permission(alias = "notifications", strings = ["android.permission.POST_NOTIFICATIONS"]),
    ],
)
class WakeWordPlugin : Plugin() {

    override fun load() {
        WakeWordBridge.onEvent { event, payload -> notifyListeners(event, JSObject.fromJSONObject(payload)) }
    }

    @PluginMethod
    fun start(call: PluginCall) {
        val options = JSONObject()
        if (call.getDouble("thresholdOffset") != null) {
            options.put("thresholdOffset", call.getDouble("thresholdOffset"))
        }
        if (call.getDouble("preconnectThreshold") != null) {
            options.put("preconnectThreshold", call.getDouble("preconnectThreshold"))
        }

        // Loading the model here, off the permission path, means a slow first
        // load happens while the permission dialog (if any) is still on
        // screen rather than serially after it.
        try {
            WakeWordBridge.ensureLoaded(context, options)
        } catch (error: Exception) {
            call.reject("Could not load the wake-word model: ${error.message}")
            return
        }

        if (getPermissionState("microphone") != PermissionState.GRANTED) {
            // Notifications are asked for at the same time on the versions
            // that have them: a foreground service is required to post one,
            // and if it cannot, the only visible sign that the microphone is
            // live disappears.
            val aliases = if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                arrayOf("microphone", "notifications")
            } else {
                arrayOf("microphone")
            }
            requestPermissionForAliases(aliases, call, "onMicPermission")
            return
        }

        WakeWordService.start(context)
        call.resolve(statusObject())
    }

    @PermissionCallback
    private fun onMicPermission(call: PluginCall) {
        if (getPermissionState("microphone") == PermissionState.GRANTED) {
            WakeWordService.start(context)
            call.resolve(statusObject())
        } else {
            call.reject(
                "Without microphone access there is nothing to listen to. You can grant it in " +
                    "Settings › Apps › Gamira › Permissions.",
            )
        }
    }

    @PluginMethod
    fun stop(call: PluginCall) {
        WakeWordService.stop(context)
        call.resolve(JSObject().put("listening", false))
    }

    @PluginMethod
    fun pause(call: PluginCall) {
        WakeWordBridge.pause()
        call.resolve()
    }

    @PluginMethod
    fun resume(call: PluginCall) {
        WakeWordBridge.resume()
        call.resolve()
    }

    @PluginMethod
    fun setOptions(call: PluginCall) {
        WakeWordBridge.setOptions(
            thresholdOffset = call.getDouble("thresholdOffset"),
            preconnectThreshold = call.getDouble("preconnectThreshold"),
        )
        call.resolve()
    }

    @PluginMethod
    fun status(call: PluginCall) {
        call.resolve(statusObject())
    }

    private fun statusObject(): JSObject {
        val detector = WakeWordBridge.detector
        return JSObject()
            .put("listening", WakeWordBridge.isListening)
            .put("wakeWord", detector?.wakeWord ?: "")
            .put("threshold", detector?.effectiveThreshold() ?: 0.0)
            .put("sampleRate", detector?.sampleRate ?: 0)
    }
}
