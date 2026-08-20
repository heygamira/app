package com.gamira.dashboard.push;

import android.app.PendingIntent;
import android.content.Context;
import android.content.Intent;
import android.os.Build;
import android.util.Log;

import androidx.core.app.NotificationCompat;
import androidx.core.app.NotificationManagerCompat;
import androidx.lifecycle.Lifecycle;
import androidx.lifecycle.ProcessLifecycleOwner;

import com.gamira.dashboard.GamiraApplication;
import com.gamira.dashboard.R;
import com.google.firebase.messaging.FirebaseMessagingService;
import com.google.firebase.messaging.RemoteMessage;

import java.util.Map;

/**
 * Receives every FCM message natively. SOS/SOS_ESCALATION pushes are sent
 * data-only by the backend (see gamira-backend's PushMessage.data_only) so
 * they reach {@link #onMessageReceived} in every app state — foregrounded,
 * backgrounded, or killed — which is what lets this raise a full-screen,
 * sound-playing alarm even on a locked phone.
 */
public class GamiraFirebaseMessagingService extends FirebaseMessagingService {

    private static final String TAG = "GamiraFCM";
    // Fixed id: a second SOS while the first is still showing replaces it
    // instead of stacking, matching SosAlertOverlay showing alerts[0] plus
    // an "N more waiting" line.
    static final int SOS_NOTIFICATION_ID = 4200;

    @Override
    public void onMessageReceived(RemoteMessage remoteMessage) {
        super.onMessageReceived(remoteMessage);
        Map<String, String> data = remoteMessage.getData();
        String type = data.get("type");
        if (!"sos".equals(type) && !"sos_escalation".equals(type)) {
            // Every other notification type only reaches here while the app
            // is foregrounded (FCM auto-displays notification+data payloads
            // once backgrounded) — SSE already handles that case.
            return;
        }

        boolean appInForeground = ProcessLifecycleOwner.get().getLifecycle()
                .getCurrentState().isAtLeast(Lifecycle.State.RESUMED);
        if (appInForeground) {
            // SosAlertOverlay + alarm.js are already showing/sounding this;
            // firing the native alarm too would double up sound and vibration.
            Log.i(TAG, "sos push received while foregrounded, skipping native alarm");
            return;
        }

        raiseNativeAlarm(data);
    }

    private void raiseNativeAlarm(Map<String, String> data) {
        Context context = getApplicationContext();

        Intent activityIntent = new Intent(context, SosAlertActivity.class);
        activityIntent.setFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
        activityIntent.putExtra(SosAlertActivity.EXTRA_NOTIFICATION_ID, data.get("notification_id"));
        activityIntent.putExtra(SosAlertActivity.EXTRA_ENTITY_ID, data.get("entity_id"));
        activityIntent.putExtra(SosAlertActivity.EXTRA_SENIOR_PROFILE_ID, data.get("senior_profile_id"));
        activityIntent.putExtra(SosAlertActivity.EXTRA_TITLE, data.get("title"));
        activityIntent.putExtra(SosAlertActivity.EXTRA_BODY, data.get("body"));

        int flags = PendingIntent.FLAG_UPDATE_CURRENT;
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
            flags |= PendingIntent.FLAG_IMMUTABLE;
        }
        PendingIntent fullScreenPendingIntent = PendingIntent.getActivity(
                context, SOS_NOTIFICATION_ID, activityIntent, flags);

        String title = data.get("title");
        String body = data.get("body");

        NotificationCompat.Builder builder = new NotificationCompat.Builder(
                context, GamiraApplication.SOS_CHANNEL_ID)
                .setSmallIcon(R.mipmap.ic_launcher)
                .setContentTitle(title != null && !title.isEmpty() ? title : "Emergency SOS")
                .setContentText(body != null && !body.isEmpty() ? body : "Someone needs your attention.")
                .setPriority(NotificationCompat.PRIORITY_HIGH)
                .setCategory(NotificationCompat.CATEGORY_CALL)
                .setAutoCancel(false)
                .setOngoing(true)
                .setContentIntent(fullScreenPendingIntent)
                // The `true` here asks the OS to treat this as urgent enough
                // to interrupt even when USE_FULL_SCREEN_INTENT hasn't been
                // granted (Android 14+) — it degrades to a heads-up
                // notification instead of doing nothing.
                .setFullScreenIntent(fullScreenPendingIntent, true);

        NotificationManagerCompat.from(context).notify(SOS_NOTIFICATION_ID, builder.build());
    }

    @Override
    public void onNewToken(String token) {
        super.onNewToken(token);
        // Not pushed to the backend from here — usePushRegistration.js
        // re-checks and re-registers on every app resume, and POST /devices
        // is documented safe to call on every app start.
        Log.i(TAG, "fcm token rotated");
    }
}
