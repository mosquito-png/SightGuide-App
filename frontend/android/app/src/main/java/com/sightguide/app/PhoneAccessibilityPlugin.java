package com.sightguide.app;

import android.accessibilityservice.AccessibilityServiceInfo;
import android.content.Context;
import android.content.Intent;
import android.provider.Settings;
import android.view.accessibility.AccessibilityManager;

import com.getcapacitor.JSObject;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;
import com.sightguide.app.accessibility.SightGuideAccessibilityService;

import java.util.List;

@CapacitorPlugin(name = "PhoneAccessibility")
public class PhoneAccessibilityPlugin extends Plugin {

    @PluginMethod
    public void isAccessibilityServiceEnabled(PluginCall call) {
        Context context = getContext();
        boolean isRunning = SightGuideAccessibilityService.isRunning();
        boolean isEnabledInSettings = false;

        if (context != null) {
            try {
                AccessibilityManager am = (AccessibilityManager) context.getSystemService(Context.ACCESSIBILITY_SERVICE);
                if (am != null) {
                    List<AccessibilityServiceInfo> enabledServices =
                            am.getEnabledAccessibilityServiceList(AccessibilityServiceInfo.FEEDBACK_ALL_MASK);
                    String pkg = context.getPackageName();
                    for (AccessibilityServiceInfo service : enabledServices) {
                        if (service.getId() != null && service.getId().contains(pkg)) {
                            isEnabledInSettings = true;
                            break;
                        }
                    }
                }
            } catch (Exception ignored) {
            }
        }

        JSObject ret = new JSObject();
        ret.put("enabled", isRunning || isEnabledInSettings);
        ret.put("running", isRunning);
        call.resolve(ret);
    }

    @PluginMethod
    public void openAccessibilitySettings(PluginCall call) {
        Context context = getContext();
        if (context != null) {
            try {
                Intent intent = new Intent(Settings.ACTION_ACCESSIBILITY_SETTINGS);
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                context.startActivity(intent);
                JSObject ret = new JSObject();
                ret.put("opened", true);
                call.resolve(ret);
                return;
            } catch (Exception e) {
                call.reject("Failed to open accessibility settings: " + e.getMessage());
                return;
            }
        }
        call.reject("Context is null");
    }

    @PluginMethod
    public void executeAction(PluginCall call) {
        SightGuideAccessibilityService service = SightGuideAccessibilityService.getInstance();
        if (service == null) {
            call.reject("Accessibility Service is not currently running. Please enable it in Android Settings.");
            return;
        }

        String action = call.getString("action", "unknown");
        String target = call.getString("target", "");
        String text = call.getString("text", "");
        String direction = call.getString("direction", "down");
        Integer ordinal = call.getInt("ordinal", null);
        String globalAction = call.getString("globalAction", "back");

        boolean success = false;
        String message = "";

        switch (action) {
            case "click":
                if (ordinal != null && ordinal != 0) {
                    success = service.executeOrdinalClick(target);
                } else {
                    success = service.executeClick(target);
                }
                message = success ? "Click executed for " + target : "Failed to click " + target;
                break;

            case "type":
                success = service.executeType(text);
                message = success ? "Typed: " + text : "Failed to type text";
                break;

            case "scroll":
                success = service.executeScroll(direction);
                message = "Scrolled " + direction;
                break;

            case "global_nav":
                success = service.executeGlobalNav(globalAction);
                message = "Global navigation executed: " + globalAction;
                break;

            case "media":
                success = service.executeMediaControl(target);
                message = "Media control executed: " + target;
                break;

            case "search":
                success = service.executeInAppSearch(target);
                message = "Searched for: " + target;
                break;

            case "open_app":
                success = service.launchAppByName(target);
                message = success ? "Opened " + target : "Could not find app " + target;
                break;

            case "read_screen":
                service.executeReadScreen();
                success = true;
                message = "Reading screen content";
                break;

            default:
                service.handleSpokenCommand(text.isEmpty() ? target : text);
                success = true;
                message = "Command dispatched to service";
                break;
        }

        JSObject ret = new JSObject();
        ret.put("success", success);
        ret.put("message", message);
        call.resolve(ret);
    }

    @PluginMethod
    public void setOverlayVisible(PluginCall call) {
        boolean visible = call.getBoolean("visible", true);
        SightGuideAccessibilityService service = SightGuideAccessibilityService.getInstance();
        if (service != null) {
            service.setOverlayVisible(visible);
            JSObject ret = new JSObject();
            ret.put("visible", visible);
            call.resolve(ret);
        } else {
            JSObject ret = new JSObject();
            ret.put("visible", false);
            ret.put("warning", "Service not active");
            call.resolve(ret);
        }
    }

    @PluginMethod
    public void setSafetyConfirmation(PluginCall call) {
        boolean enabled = call.getBoolean("enabled", true);
        SightGuideAccessibilityService service = SightGuideAccessibilityService.getInstance();
        if (service != null) {
            service.setSafetyConfirmationEnabled(enabled);
        }
        JSObject ret = new JSObject();
        ret.put("enabled", enabled);
        call.resolve(ret);
    }
}
