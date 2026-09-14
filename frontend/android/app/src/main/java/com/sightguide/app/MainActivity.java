package com.sightguide.app;

import android.os.Bundle;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    @Override
    public void onCreate(Bundle savedInstanceState) {
        registerPlugin(DirectTelephonyPlugin.class);
        registerPlugin(PhoneAccessibilityPlugin.class);
        super.onCreate(savedInstanceState);
    }
}

