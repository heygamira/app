package com.gamira.dashboard.push;

import android.app.Activity;
import android.app.KeyguardManager;
import android.content.Context;
import android.content.Intent;
import android.media.AudioAttributes;
import android.media.MediaPlayer;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.os.PowerManager;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.os.VibratorManager;
import android.util.Log;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.TextView;

import androidx.annotation.Nullable;
import androidx.core.app.NotificationManagerCompat;

import com.gamira.dashboard.MainActivity;
import com.gamira.dashboard.R;

import java.io.IOException;

/**
 * The lock-screen alarm UI a locked/backgrounded SOS full-screen intent
 * opens. Deliberately a plain Activity, not a Capacitor BridgeActivity — it
 * has to boot and start ringing in a second or two on a phone that may be
 * asleep, which doesn't depend on the WebView/JS bundle being healthy.
 * "Open Gamira" foregrounds the real app, where SosAlertOverlay (already
 * global, see Layout.jsx) shows the same alert with full detail and the real
 * "I have seen this" acknowledge action. "Silence" stops the local alarm and
 * also acknowledges the alert directly (see AlertAcknowledger) so a locked
 * phone doesn't need to be unlocked just to quiet it.
 */
public class SosAlertActivity extends Activity {

    private static final String TAG = "SosAlertActivity";
    private static final long TIMEOUT_MS = 90_000L;

    public static final String EXTRA_NOTIFICATION_ID = "notification_id";
    public static final String EXTRA_ENTITY_ID = "entity_id";
    public static final String EXTRA_SENIOR_PROFILE_ID = "senior_profile_id";
    public static final String EXTRA_TITLE = "title";
    public static final String EXTRA_BODY = "body";

    private MediaPlayer mediaPlayer;
    private Vibrator vibrator;
    private PowerManager.WakeLock wakeLock;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable timeoutRunnable = this::onTimeout;
    private boolean finishing = false;

    @Override
    protected void onCreate(@Nullable Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        showOverLockScreen();
        setContentView(R.layout.activity_sos_alert);

        String title = getIntent().getStringExtra(EXTRA_TITLE);
        String body = getIntent().getStringExtra(EXTRA_BODY);

        TextView titleView = findViewById(R.id.sos_title);
        TextView bodyView = findViewById(R.id.sos_body);
        titleView.setText(title != null && !title.isEmpty() ? title : "Emergency SOS");
        bodyView.setText(body != null ? body : "");

        Button openButton = findViewById(R.id.sos_open_button);
        Button silenceButton = findViewById(R.id.sos_silence_button);
        openButton.setOnClickListener(v -> openGamira());
        silenceButton.setOnClickListener(v -> silence());

        handler.postDelayed(timeoutRunnable, TIMEOUT_MS);
    }

    private void showOverLockScreen() {
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O_MR1) {
            setShowWhenLocked(true);
            setTurnScreenOn(true);
            KeyguardManager keyguardManager =
                    (KeyguardManager) getSystemService(Context.KEYGUARD_SERVICE);
            if (keyguardManager != null) {
                // No-op on a secured lock (PIN/pattern/biometric) — the OS
                // correctly still requires the user to unlock, and the
                // content is shown over the lock screen either way.
                keyguardManager.requestDismissKeyguard(this, null);
            }
        } else {
            getWindow().addFlags(
                    WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED
                            | WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
                            | WindowManager.LayoutParams.FLAG_DISMISS_KEYGUARD
                            | WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        }

        PowerManager powerManager = (PowerManager) getSystemService(Context.POWER_SERVICE);
        if (powerManager != null) {
            wakeLock = powerManager.newWakeLock(
                    PowerManager.PARTIAL_WAKE_LOCK, "gamira:sos_alert");
            // Belt-and-braces for OEMs slow to honor the window flags above;
            // released once those have had a chance to take effect.
            wakeLock.acquire(10_000L);
        }
    }

    @Override
    protected void onResume() {
        super.onResume();
        startAlarm();
    }

    private void startAlarm() {
        if (mediaPlayer == null) {
            try {
                mediaPlayer = new MediaPlayer();
                mediaPlayer.setAudioAttributes(new AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_ALARM)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                        .build());
                mediaPlayer.setDataSource(this, SosAlarmSound.resolve(this));
                mediaPlayer.setLooping(true);
                mediaPlayer.prepare();
                mediaPlayer.start();
            } catch (IOException | IllegalStateException e) {
                Log.w(TAG, "could not start alarm sound", e);
            }
        }

        if (vibrator == null) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                VibratorManager vibratorManager =
                        (VibratorManager) getSystemService(Context.VIBRATOR_MANAGER_SERVICE);
                vibrator = vibratorManager != null ? vibratorManager.getDefaultVibrator() : null;
            } else {
                vibrator = (Vibrator) getSystemService(Context.VIBRATOR_SERVICE);
            }
        }
        if (vibrator != null) {
            long[] pattern = {0, 500, 250, 500};
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                vibrator.vibrate(VibrationEffect.createWaveform(pattern, 0));
            } else {
                vibrator.vibrate(pattern, 0);
            }
        }
    }

    private void stopAlarm() {
        if (mediaPlayer != null) {
            try {
                mediaPlayer.stop();
            } catch (IllegalStateException ignored) {
                // Already stopped/released — nothing to do.
            }
            mediaPlayer.release();
            mediaPlayer = null;
        }
        if (vibrator != null) {
            vibrator.cancel();
        }
        handler.removeCallbacks(timeoutRunnable);
        if (wakeLock != null && wakeLock.isHeld()) {
            wakeLock.release();
        }
    }

    private void cancelTrayNotification() {
        NotificationManagerCompat.from(this)
                .cancel(GamiraFirebaseMessagingService.SOS_NOTIFICATION_ID);
    }

    private void openGamira() {
        stopAlarm();
        cancelTrayNotification();
        // Does not also acknowledge — opening the app surfaces the same
        // SosAlertOverlay (refreshed via Layout.jsx's appStateChange
        // listener) where "I have seen this" is the one real acknowledge
        // action for that flow.
        Intent intent = new Intent(this, MainActivity.class);
        intent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_CLEAR_TOP);
        startActivity(intent);
        finish();
    }

    private void silence() {
        stopAlarm();
        cancelTrayNotification();
        acknowledge();
        finish();
    }

    private void onTimeout() {
        if (finishing) {
            return;
        }
        finishing = true;
        stopAlarm();
        cancelTrayNotification();
        acknowledge();
        finish();
    }

    private void acknowledge() {
        String entityId = getIntent().getStringExtra(EXTRA_ENTITY_ID);
        if (entityId != null && !entityId.isEmpty()) {
            AlertAcknowledger.acknowledgeAsync(getApplicationContext(), entityId);
        }
    }

    @Override
    protected void onDestroy() {
        super.onDestroy();
        stopAlarm();
    }
}
