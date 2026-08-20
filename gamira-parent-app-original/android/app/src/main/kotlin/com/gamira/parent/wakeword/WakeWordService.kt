package com.gamira.parent.wakeword

import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.AutomaticGainControl
import android.media.audiofx.NoiseSuppressor
import android.os.Build
import android.os.IBinder
import android.os.SystemClock
import android.util.Log
import androidx.core.app.NotificationCompat
import com.gamira.parent.MainActivity
import kotlin.concurrent.thread

/**
 * Always-on wake-word listening, as a foreground service.
 *
 * This is the reason the detector is not just `getUserMedia` in the WebView
 * any more. Android suspends a browser tab's (and a WebView's) audio the
 * moment the screen goes off, so a wake word detector living there stops
 * detecting exactly when you would want it most — after you put the phone
 * down. A foreground service with a microphone type keeps running, at the
 * cost of a notification the person can see, which is the right trade to
 * make visible rather than hide.
 */
class WakeWordService : Service() {

    private var worker: Thread? = null
    @Volatile private var running = false

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_STOP) {
            stopListening()
            stopSelf()
            return START_NOT_STICKY
        }

        startForegroundWithMic()
        startListening()
        // START_STICKY: if Android kills this under memory pressure, the
        // person's intent was "keep listening", so it should come back.
        return START_STICKY
    }

    private fun startForegroundWithMic() {
        val manager = getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL, "Listening", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Shown while Gamira is listening for its name"
                    setShowBadge(false)
                },
            )
        }

        val open = PendingIntent.getActivity(
            this, 0, Intent(this, MainActivity::class.java),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val stop = PendingIntent.getService(
            this, 1, Intent(this, WakeWordService::class.java).setAction(ACTION_STOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

        val phrase = WakeWordBridge.detector?.wakeWord?.takeIf { it.isNotEmpty() } ?: "Gamira"
        val notification: Notification = NotificationCompat.Builder(this, CHANNEL)
            .setContentTitle("Listening for “$phrase”")
            .setContentText("Audio is processed on this phone and never leaves it.")
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentIntent(open)
            .addAction(0, "Stop", stop)
            .setOngoing(true)
            .setPriority(NotificationCompat.PRIORITY_LOW)
            .build()

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(NOTIFICATION_ID, notification, ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE)
        } else {
            startForeground(NOTIFICATION_ID, notification)
        }
    }

    private fun startListening() {
        if (running) return
        val detector = runCatching { WakeWordBridge.ensureLoaded(applicationContext) }
            .onFailure {
                Log.e(TAG, "Could not load the wake-word model", it)
                WakeWordBridge.onMicLost("The wake-word model could not be loaded.")
                stopSelf()
            }
            .getOrNull() ?: return

        running = true
        worker = thread(name = "wakeword-mic", priority = Thread.MAX_PRIORITY) {
            runCatching { captureLoop(detector) }
                .onFailure { Log.e(TAG, "Capture stopped", it) }
            running = false
        }
    }

    /**
     * Reopens the microphone with a different [MediaRecorder.AudioSource]
     * whenever [WakeWordBridge.audioTapActive] flips, rather than running one
     * `AudioRecord` for the whole service lifetime.
     *
     * The two modes need different platform tuning and there is no source
     * that is right for both: `VOICE_RECOGNITION` asks the platform to leave
     * gain control and noise suppression off, which is exactly what the
     * wake-word model needs — it was trained on untouched audio, and effects
     * tuned for a phone call would change the signal in ways it never saw.
     * `VOICE_COMMUNICATION` is the other way round, and matters for a reason
     * `VOICE_RECOGNITION` does not: without echo cancellation, the microphone
     * hears Gemini's own reply coming out of the speaker and she interrupts
     * herself in a loop. A brief gap in capture while the swap happens is a
     * fair trade for a conversation that does not fight itself.
     */
    private fun captureLoop(detector: WakeDetector) {
        while (running) {
            runRecorderSession(detector, WakeWordBridge.audioTapActive)
        }
    }

    /** Runs until [running] goes false or [WakeWordBridge.audioTapActive] no longer matches [tapping]. */
    private fun runRecorderSession(detector: WakeDetector, tapping: Boolean) {
        val sampleRate = detector.sampleRate
        // ~50 ms per read, matching the web build's AudioWorklet batching:
        // fine enough that the trigger's 80 ms inference cadence still lands
        // on time, coarse enough not to flood this thread with syscalls.
        val chunkSamples = (sampleRate / 20).coerceAtLeast(1)

        val minBuffer = AudioRecord.getMinBufferSize(
            sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT,
        )
        val bufferBytes = maxOf(minBuffer, chunkSamples * 4 * 8)

        val source = if (tapping) {
            MediaRecorder.AudioSource.VOICE_COMMUNICATION
        } else {
            MediaRecorder.AudioSource.VOICE_RECOGNITION
        }
        val recorder = AudioRecord(source, sampleRate, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_FLOAT, bufferBytes)

        if (recorder.state != AudioRecord.STATE_INITIALIZED) {
            Log.e(TAG, "Microphone unavailable (state ${recorder.state})")
            recorder.release()
            WakeWordBridge.onMicLost("The microphone could not be opened. Another app may be using it.")
            running = false
            return
        }

        // Effects only make sense on the conversation source: attaching them
        // to VOICE_RECOGNITION would fight the model's own PCEN normalisation
        // with a second, uncoordinated one.
        var aec: AcousticEchoCanceler? = null
        var noiseSuppressor: NoiseSuppressor? = null
        var agc: AutomaticGainControl? = null
        if (tapping) {
            val sessionId = recorder.audioSessionId
            if (AcousticEchoCanceler.isAvailable()) {
                aec = AcousticEchoCanceler.create(sessionId)?.apply { enabled = true }
            }
            if (NoiseSuppressor.isAvailable()) {
                noiseSuppressor = NoiseSuppressor.create(sessionId)?.apply { enabled = true }
            }
            if (AutomaticGainControl.isAvailable()) {
                agc = AutomaticGainControl.create(sessionId)?.apply { enabled = true }
            }
        }

        val buffer = FloatArray(chunkSamples)
        recorder.startRecording()
        WakeWordBridge.onListeningChanged(true)
        Log.i(TAG, "Listening at $sampleRate Hz in ${chunkSamples}-sample chunks (tapping=$tapping)")

        try {
            while (running && WakeWordBridge.audioTapActive == tapping) {
                var filled = 0
                while (filled < chunkSamples && running && WakeWordBridge.audioTapActive == tapping) {
                    val read = recorder.read(buffer, filled, chunkSamples - filled, AudioRecord.READ_BLOCKING)
                    if (read <= 0) {
                        Log.w(TAG, "Microphone read returned $read")
                        WakeWordBridge.onMicLost("The microphone stopped returning audio.")
                        running = false
                        return
                    }
                    filled += read
                }
                if (!running || WakeWordBridge.audioTapActive != tapping) break

                if (tapping) {
                    WakeWordBridge.emitAudioChunk(buffer, filled)
                } else {
                    val event = detector.push(buffer, filled, SystemClock.elapsedRealtime())
                    if (event != null) WakeWordBridge.onEvent(event)
                }
            }
        } finally {
            aec?.release()
            noiseSuppressor?.release()
            agc?.release()
            runCatching { recorder.stop() }
            recorder.release()
            WakeWordBridge.onListeningChanged(false)
            Log.i(TAG, "Stopped listening (tapping=$tapping)")
        }
    }

    private fun stopListening() {
        running = false
        worker?.join(1_000)
        worker = null
    }

    override fun onDestroy() {
        stopListening()
        super.onDestroy()
    }

    companion object {
        private const val TAG = "WakeWordService"
        private const val CHANNEL = "wakeword-listening"
        private const val NOTIFICATION_ID = 4201
        const val ACTION_STOP = "com.gamira.parent.wakeword.STOP"

        fun start(context: Context) {
            val intent = Intent(context, WakeWordService::class.java)
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                context.startForegroundService(intent)
            } else {
                context.startService(intent)
            }
        }

        fun stop(context: Context) {
            context.startService(Intent(context, WakeWordService::class.java).setAction(ACTION_STOP))
        }
    }
}
