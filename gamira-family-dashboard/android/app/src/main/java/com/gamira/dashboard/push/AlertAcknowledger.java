package com.gamira.dashboard.push;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Log;

import com.gamira.dashboard.BuildConfig;

import java.io.IOException;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.nio.charset.StandardCharsets;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Fires the same {@code POST /alerts/{id}/acknowledge} call the web
 * SosAlertOverlay's "I have seen this" button makes (see
 * src/lib/useAlerts.js), from native code, for the lock-screen "Silence"
 * action. Reads the bearer token that {@code src/api/gamiraClient.js}
 * mirrors into Capacitor Preferences on sign-in — Preferences is a thin
 * wrapper over a plain SharedPreferences file ("CapacitorStorage"), which
 * lets this read the token directly without duplicating the app's whole auth
 * stack natively.
 */
final class AlertAcknowledger {

    private static final String TAG = "AlertAcknowledger";
    private static final String PREFS_FILE = "CapacitorStorage";
    private static final String TOKEN_KEY = "gamira_access_token";
    private static final ExecutorService EXECUTOR = Executors.newSingleThreadExecutor();

    private AlertAcknowledger() {
    }

    static void acknowledgeAsync(Context context, String alertId) {
        EXECUTOR.execute(() -> {
            try {
                acknowledge(context, alertId);
            } catch (Exception e) {
                // The alert stays unacknowledged server-side on failure; the
                // existing SSE-driven escalation path is the safety net for
                // that, exactly as it is for any other missed alert today.
                Log.w(TAG, "acknowledge failed for alert " + alertId, e);
            }
        });
    }

    private static void acknowledge(Context context, String alertId) throws IOException {
        SharedPreferences prefs = context.getSharedPreferences(PREFS_FILE, Context.MODE_PRIVATE);
        String token = prefs.getString(TOKEN_KEY, null);
        if (token == null || token.isEmpty()) {
            Log.w(TAG, "no stored access token, cannot acknowledge alert " + alertId);
            return;
        }

        URL url = new URL(BuildConfig.API_BASE_URL + "/alerts/" + alertId + "/acknowledge");
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();
        try {
            connection.setRequestMethod("POST");
            connection.setRequestProperty("Authorization", "Bearer " + token);
            connection.setRequestProperty("Content-Type", "application/json");
            connection.setConnectTimeout(10_000);
            connection.setReadTimeout(10_000);
            connection.setDoOutput(true);
            try (OutputStream out = connection.getOutputStream()) {
                out.write("{}".getBytes(StandardCharsets.UTF_8));
            }
            int status = connection.getResponseCode();
            if (status >= 200 && status < 300) {
                Log.i(TAG, "acknowledged alert " + alertId);
            } else {
                Log.w(TAG, "acknowledge returned status " + status + " for alert " + alertId);
            }
        } finally {
            connection.disconnect();
        }
    }
}
