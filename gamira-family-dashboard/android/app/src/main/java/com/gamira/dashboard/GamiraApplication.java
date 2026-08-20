package com.gamira.dashboard;

import android.app.Application;
import android.app.Notification;
import android.app.NotificationChannel;
import android.app.NotificationManager;
import android.media.AudioAttributes;
import android.os.Build;

import com.gamira.dashboard.push.SosAlarmSound;

/**
 * Creates the notification channels SOS delivery needs before any push can
 * arrive. Channel creation is idempotent — safe to run on every launch.
 */
public class GamiraApplication extends Application {

    public static final String SOS_CHANNEL_ID = "sos_alerts";
    public static final String GENERAL_CHANNEL_ID = "general_alerts";

    @Override
    public void onCreate() {
        super.onCreate();
        createNotificationChannels();
    }

    private void createNotificationChannels() {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) {
            return;
        }
        NotificationManager manager = getSystemService(NotificationManager.class);
        if (manager == null) {
            return;
        }

        AudioAttributes alarmAttributes = new AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_ALARM)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build();

        NotificationChannel sosChannel = new NotificationChannel(
                SOS_CHANNEL_ID, "Emergency SOS alerts", NotificationManager.IMPORTANCE_HIGH);
        sosChannel.setDescription(
                "Full-screen, high-priority alerts when a family member presses SOS.");
        sosChannel.setSound(SosAlarmSound.resolve(this), alarmAttributes);
        sosChannel.enableVibration(true);
        sosChannel.setVibrationPattern(new long[]{0, 500, 250, 500});
        // An emergency alert for a care app should cut through silent/DND —
        // confirmed deliberately, not a default left unexamined.
        sosChannel.setBypassDnd(true);
        sosChannel.setLockscreenVisibility(Notification.VISIBILITY_PUBLIC);
        manager.createNotificationChannel(sosChannel);

        NotificationChannel generalChannel = new NotificationChannel(
                GENERAL_CHANNEL_ID, "General alerts", NotificationManager.IMPORTANCE_DEFAULT);
        generalChannel.setDescription("Non-emergency notifications from Gamira.");
        manager.createNotificationChannel(generalChannel);
    }
}
