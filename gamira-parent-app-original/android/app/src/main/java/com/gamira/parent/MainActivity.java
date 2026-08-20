package com.gamira.parent;

import android.Manifest;
import android.content.pm.PackageManager;
import android.os.Bundle;
import android.webkit.PermissionRequest;
import androidx.core.app.ActivityCompat;
import com.getcapacitor.BridgeActivity;
import com.getcapacitor.BridgeWebChromeClient;
import com.gamira.parent.wakeword.WakeWordPlugin;

public class MainActivity extends BridgeActivity {
  private static final int REQUEST_MIC_LOCATION = 1001;

  @Override
  public void onCreate(Bundle savedInstanceState) {
    // Must run before super.onCreate(), which is where Capacitor's bridge
    // reads the registered-plugin list and starts loading the WebView.
    registerPlugin(WakeWordPlugin.class);

    super.onCreate(savedInstanceState);

    // getUserMedia() in the WebView cannot succeed without the app also
    // holding the OS-level runtime permission — this asks for it once, up
    // front, rather than leaving the WebView's mic prompt to fail silently
    // against a never-granted permission.
    ActivityCompat.requestPermissions(
        this,
        new String[] {
          Manifest.permission.RECORD_AUDIO,
          Manifest.permission.ACCESS_FINE_LOCATION,
          Manifest.permission.ACCESS_COARSE_LOCATION
        },
        REQUEST_MIC_LOCATION);

    // Capacitor's own WebChromeClient never grants getUserMedia's
    // PermissionRequest — without this override, the mic/camera prompt the
    // web app triggers is denied automatically, every time.
    getBridge()
        .getWebView()
        .setWebChromeClient(
            new BridgeWebChromeClient(getBridge()) {
              @Override
              public void onPermissionRequest(final PermissionRequest request) {
                runOnUiThread(
                    () -> {
                      boolean micGranted =
                          ActivityCompat.checkSelfPermission(
                                  MainActivity.this, Manifest.permission.RECORD_AUDIO)
                              == PackageManager.PERMISSION_GRANTED;
                      if (micGranted) {
                        request.grant(request.getResources());
                      } else {
                        request.deny();
                      }
                    });
              }
            });
  }
}
