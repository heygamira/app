package com.gamira.dashboard.push;

import android.content.Context;
import android.media.RingtoneManager;
import android.net.Uri;

/**
 * Resolves the SOS alarm sound at runtime via {@code getIdentifier} rather
 * than compiling against a fixed {@code R.raw.sos_alarm} reference — that
 * would fail to build until the asset exists. Drop a file in as
 * {@code res/raw/sos_alarm.<ext>} (mp3/ogg/wav) and it is picked up with no
 * code change; until then this falls back to the device's own alarm sound.
 */
public final class SosAlarmSound {

    private static final String RESOURCE_NAME = "sos_alarm";

    private SosAlarmSound() {
    }

    public static Uri resolve(Context context) {
        int resId = context.getResources()
                .getIdentifier(RESOURCE_NAME, "raw", context.getPackageName());
        if (resId != 0) {
            return Uri.parse("android.resource://" + context.getPackageName() + "/" + resId);
        }
        Uri fallback = RingtoneManager.getActualDefaultRingtoneUri(
                context, RingtoneManager.TYPE_ALARM);
        if (fallback != null) {
            return fallback;
        }
        return RingtoneManager.getDefaultUri(RingtoneManager.TYPE_NOTIFICATION);
    }
}
