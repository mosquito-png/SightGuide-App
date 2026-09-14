package com.sightguide.app;

import android.Manifest;
import android.content.Context;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.location.Location;
import android.location.LocationListener;
import android.location.LocationManager;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.telephony.PhoneStateListener;
import android.telephony.SmsManager;
import android.telephony.TelephonyCallback;
import android.telephony.TelephonyManager;
import android.util.Log;

import androidx.annotation.RequiresApi;
import androidx.core.content.ContextCompat;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.getcapacitor.annotation.Permission;
import com.getcapacitor.annotation.PermissionCallback;

import java.net.URLEncoder;
import java.util.ArrayList;

@CapacitorPlugin(
    name = "DirectTelephony",
    permissions = {
        @Permission(strings = { Manifest.permission.CAMERA }, alias = "camera"),
        @Permission(strings = { Manifest.permission.RECORD_AUDIO }, alias = "microphone"),
        @Permission(strings = { Manifest.permission.ACCESS_FINE_LOCATION, Manifest.permission.ACCESS_COARSE_LOCATION }, alias = "location"),
        @Permission(strings = { Manifest.permission.CALL_PHONE }, alias = "call"),
        @Permission(strings = { Manifest.permission.SEND_SMS }, alias = "sms"),
        @Permission(strings = { Manifest.permission.READ_PHONE_STATE }, alias = "phoneState")
    }
)
public class DirectTelephonyPlugin extends Plugin {
    private static final String TAG = "DirectTelephony";

    private boolean isCallInProgress = false;
    private boolean hasBeenActive = false;
    private TelephonyManager telephonyManager;

    @RequiresApi(api = Build.VERSION_CODES.S)
    private static class CustomTelephonyCallback extends TelephonyCallback implements TelephonyCallback.CallStateListener {
        private final DirectTelephonyPlugin plugin;

        CustomTelephonyCallback(DirectTelephonyPlugin plugin) {
            this.plugin = plugin;
        }

        @Override
        public void onCallStateChanged(int state) {
            plugin.handleCallStateChanged(state);
        }
    }

    private class CustomPhoneStateListener extends PhoneStateListener {
        @Override
        public void onCallStateChanged(int state, String phoneNumber) {
            handleCallStateChanged(state);
        }
    }

    @Override
    public void load() {
        super.load();
        initCallStateListener();
    }

    private void initCallStateListener() {
        try {
            Context context = getContext();
            if (context == null) return;
            telephonyManager = (TelephonyManager) context.getSystemService(Context.TELEPHONY_SERVICE);
            if (telephonyManager == null) return;

            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                CustomTelephonyCallback callback = new CustomTelephonyCallback(this);
                telephonyManager.registerTelephonyCallback(context.getMainExecutor(), callback);
            } else {
                CustomPhoneStateListener listener = new CustomPhoneStateListener();
                telephonyManager.listen(listener, PhoneStateListener.LISTEN_CALL_STATE);
            }
            Log.d(TAG, "Call state listener registered successfully.");
        } catch (Exception e) {
            Log.e(TAG, "Error initializing call state listener", e);
        }
    }

    public void handleCallStateChanged(int state) {
        Log.d(TAG, "Call state changed: " + state + " (inProgress=" + isCallInProgress + ", active=" + hasBeenActive + ")");

        if (state == TelephonyManager.CALL_STATE_OFFHOOK || state == TelephonyManager.CALL_STATE_RINGING) {
            hasBeenActive = true;
        } else if (state == TelephonyManager.CALL_STATE_IDLE) {
            if (isCallInProgress || hasBeenActive) {
                isCallInProgress = false;
                hasBeenActive = false;
                Log.d(TAG, "Call ended. Returning to SightGuide...");

                new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
                    @Override
                    public void run() {
                        bringAppToFront();
                        JSObject ret = new JSObject();
                        ret.put("status", "call_ended");
                        notifyListeners("callEnded", ret);
                    }
                }, 600);
            }
        }
    }

    private void bringAppToFront() {
        try {
            Context context = getContext();
            if (context == null) return;
            Intent intent = new Intent(context, MainActivity.class);
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK | Intent.FLAG_ACTIVITY_REORDER_TO_FRONT | Intent.FLAG_ACTIVITY_SINGLE_TOP);
            context.startActivity(intent);
            Log.d(TAG, "SightGuide brought back to front successfully.");
        } catch (Exception e) {
            Log.e(TAG, "Failed to bring SightGuide to front: ", e);
        }
    }

    @PluginMethod
    public void checkPermissions(PluginCall call) {
        Context context = getContext();
        boolean hasCamera = ContextCompat.checkSelfPermission(context, Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED;
        boolean hasMic = ContextCompat.checkSelfPermission(context, Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED;
        boolean hasLocation = ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) == PackageManager.PERMISSION_GRANTED ||
                              ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) == PackageManager.PERMISSION_GRANTED;
        boolean hasCall = ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) == PackageManager.PERMISSION_GRANTED;
        boolean hasSms = ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) == PackageManager.PERMISSION_GRANTED;

        JSObject ret = new JSObject();
        ret.put("camera", hasCamera ? "granted" : "denied");
        ret.put("microphone", hasMic ? "granted" : "denied");
        ret.put("location", hasLocation ? "granted" : "denied");
        ret.put("call", hasCall ? "granted" : "denied");
        ret.put("sms", hasSms ? "granted" : "denied");
        call.resolve(ret);
    }

    @PluginMethod
    public void requestAllAppPermissions(PluginCall call) {
        requestAllPermissions(call, "allPermissionsCallback");
    }

    @PermissionCallback
    private void allPermissionsCallback(PluginCall call) {
        checkPermissions(call);
    }

    @PluginMethod
    public void getNativeLocation(PluginCall call) {
        Context context = getContext();
        if (ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_FINE_LOCATION) != PackageManager.PERMISSION_GRANTED &&
            ContextCompat.checkSelfPermission(context, Manifest.permission.ACCESS_COARSE_LOCATION) != PackageManager.PERMISSION_GRANTED) {
            call.reject("Location permission not granted");
            return;
        }

        try {
            LocationManager lm = (LocationManager) context.getSystemService(Context.LOCATION_SERVICE);
            if (lm == null) {
                call.reject("LocationManager not available");
                return;
            }

            // 1. Instant check: Best last known location across all active providers
            Location bestLocation = null;
            for (String provider : lm.getProviders(true)) {
                try {
                    Location l = lm.getLastKnownLocation(provider);
                    if (l == null) continue;
                    if (bestLocation == null || l.getAccuracy() < bestLocation.getAccuracy()) {
                        bestLocation = l;
                    }
                } catch (SecurityException ignored) {}
            }

            if (bestLocation != null) {
                JSObject ret = new JSObject();
                ret.put("latitude", bestLocation.getLatitude());
                ret.put("longitude", bestLocation.getLongitude());
                ret.put("accuracy", bestLocation.getAccuracy());
                ret.put("provider", bestLocation.getProvider());
                call.resolve(ret);
                return;
            }

            // 2. Request single fresh location fix if no last known location exists
            final boolean[] resolved = {false};
            final LocationListener locationListener = new LocationListener() {
                @Override
                public void onLocationChanged(Location loc) {
                    if (resolved[0]) return;
                    resolved[0] = true;
                    try {
                        lm.removeUpdates(this);
                    } catch (Exception ignored) {}
                    JSObject ret = new JSObject();
                    ret.put("latitude", loc.getLatitude());
                    ret.put("longitude", loc.getLongitude());
                    ret.put("accuracy", loc.getAccuracy());
                    ret.put("provider", loc.getProvider());
                    call.resolve(ret);
                }
                @Override
                public void onStatusChanged(String provider, int status, Bundle extras) {}
                @Override
                public void onProviderEnabled(String provider) {}
                @Override
                public void onProviderDisabled(String provider) {}
            };

            String bestProvider = lm.isProviderEnabled(LocationManager.GPS_PROVIDER) ? LocationManager.GPS_PROVIDER : LocationManager.NETWORK_PROVIDER;
            lm.requestSingleUpdate(bestProvider, locationListener, Looper.getMainLooper());

            // 3-second hard timeout
            new Handler(Looper.getMainLooper()).postDelayed(new Runnable() {
                @Override
                public void run() {
                    if (!resolved[0]) {
                        resolved[0] = true;
                        try {
                            lm.removeUpdates(locationListener);
                        } catch (Exception ignored) {}
                        call.reject("Location request timed out");
                    }
                }
            }, 3000);

        } catch (Exception e) {
            Log.e(TAG, "Error getting native location", e);
            call.reject("Failed to get location: " + e.getMessage());
        }
    }

    @PluginMethod
    public void directCall(PluginCall call) {
        String phoneNumber = call.getString("phoneNumber");
        if (phoneNumber == null || phoneNumber.trim().isEmpty()) {
            call.reject("Phone number is required");
            return;
        }

        String cleanNumber = phoneNumber.replaceAll("[^\\d+]", "");
        Context context = getContext();

        if (ContextCompat.checkSelfPermission(context, Manifest.permission.CALL_PHONE) != PackageManager.PERMISSION_GRANTED) {
            try {
                isCallInProgress = true;
                hasBeenActive = false;
                Intent dialIntent = new Intent(Intent.ACTION_DIAL, Uri.parse("tel:" + cleanNumber));
                dialIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(dialIntent);
                JSObject ret = new JSObject();
                ret.put("status", "dial_fallback");
                ret.put("message", "Dialer opened (CALL_PHONE permission not granted)");
                call.resolve(ret);
            } catch (Exception e) {
                isCallInProgress = false;
                call.reject("Failed to dial: " + e.getMessage());
            }
            return;
        }

        try {
            isCallInProgress = true;
            hasBeenActive = false;
            Intent callIntent = new Intent(Intent.ACTION_CALL, Uri.parse("tel:" + cleanNumber));
            callIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
            context.startActivity(callIntent);

            JSObject ret = new JSObject();
            ret.put("status", "calling");
            ret.put("phoneNumber", cleanNumber);
            call.resolve(ret);
        } catch (Exception e) {
            isCallInProgress = false;
            Log.e(TAG, "Direct call error", e);
            call.reject("Could not place direct call: " + e.getMessage());
        }
    }

    @PluginMethod
    public void directSms(PluginCall call) {
        String phoneNumber = call.getString("phoneNumber");
        String message = call.getString("message");

        if (phoneNumber == null || phoneNumber.trim().isEmpty()) {
            call.reject("Phone number is required");
            return;
        }
        if (message == null || message.trim().isEmpty()) {
            call.reject("Message text is required");
            return;
        }

        String cleanNumber = phoneNumber.replaceAll("[^\\d+]", "");
        Context context = getContext();

        if (ContextCompat.checkSelfPermission(context, Manifest.permission.SEND_SMS) != PackageManager.PERMISSION_GRANTED) {
            try {
                Intent smsIntent = new Intent(Intent.ACTION_SENDTO, Uri.parse("smsto:" + cleanNumber));
                smsIntent.putExtra("sms_body", message);
                smsIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(smsIntent);
                JSObject ret = new JSObject();
                ret.put("status", "sms_fallback");
                ret.put("message", "SMS app opened (SEND_SMS permission not granted)");
                call.resolve(ret);
            } catch (Exception e) {
                call.reject("Failed to open SMS: " + e.getMessage());
            }
            return;
        }

        try {
            SmsManager smsManager;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.S) {
                smsManager = context.getSystemService(SmsManager.class);
            } else {
                smsManager = SmsManager.getDefault();
            }

            ArrayList<String> parts = smsManager.divideMessage(message);
            smsManager.sendMultipartTextMessage(cleanNumber, null, parts, null, null);

            JSObject ret = new JSObject();
            ret.put("status", "sent");
            ret.put("phoneNumber", cleanNumber);
            ret.put("parts", parts.size());
            call.resolve(ret);
        } catch (Exception e) {
            Log.e(TAG, "Direct SMS error", e);
            call.reject("Could not send direct SMS: " + e.getMessage());
        }
    }

    @PluginMethod
    public void sendWhatsApp(PluginCall call) {
        String phoneNumber = call.getString("phoneNumber");
        String message = call.getString("message", "");

        if (phoneNumber == null || phoneNumber.trim().isEmpty()) {
            call.reject("Phone number is required");
            return;
        }

        String cleanNumber = phoneNumber.replaceAll("[^\\d]", "");
        if (cleanNumber.length() == 10) {
            cleanNumber = "91" + cleanNumber;
        }

        try {
            String encodedMessage = URLEncoder.encode(message, "UTF-8");
            String url = "https://api.whatsapp.com/send?phone=" + cleanNumber + "&text=" + encodedMessage;
            Intent intent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
            intent.setPackage("com.whatsapp");
            intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);

            Context context = getContext();
            PackageManager pm = context.getPackageManager();
            if (intent.resolveActivity(pm) != null) {
                context.startActivity(intent);
                JSObject ret = new JSObject();
                ret.put("status", "whatsapp_opened");
                call.resolve(ret);
            } else {
                Intent webIntent = new Intent(Intent.ACTION_VIEW, Uri.parse(url));
                webIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(webIntent);
                JSObject ret = new JSObject();
                ret.put("status", "whatsapp_web_opened");
                call.resolve(ret);
            }
        } catch (Exception e) {
            Log.e(TAG, "WhatsApp dispatch error", e);
            call.reject("Could not dispatch WhatsApp message: " + e.getMessage());
        }
    }
}
