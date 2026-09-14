package com.sightguide.app.accessibility;

import android.accessibilityservice.AccessibilityService;
import android.accessibilityservice.GestureDescription;
import android.content.Context;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.graphics.Path;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.os.Build;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.speech.RecognitionListener;
import android.speech.RecognizerIntent;
import android.speech.SpeechRecognizer;
import android.speech.tts.TextToSpeech;
import android.util.Log;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.view.accessibility.AccessibilityEvent;
import android.view.accessibility.AccessibilityNodeInfo;
import android.widget.Button;
import android.widget.FrameLayout;

import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

/**
 * Generic Android Accessibility Service for SightGuide.
 * Enables whole-phone hands-free voice navigation across any app on Android.
 */
public class SightGuideAccessibilityService extends AccessibilityService {
    private static final String TAG = "SightGuideA11y";

    private static SightGuideAccessibilityService sInstance;

    private final Handler mHandler = new Handler(Looper.getMainLooper());
    private TextToSpeech mTTS;
    private boolean mTTSReady = false;

    private WindowManager mWindowManager;
    private View mOverlayView;
    private boolean mOverlayVisible = false;

    private SpeechRecognizer mSpeechRecognizer;
    private boolean mIsListening = false;

    private boolean mSafetyConfirmationEnabled = true;
    private String mPendingSensitiveAction = null;
    private Runnable mPendingActionRunnable = null;

    public static SightGuideAccessibilityService getInstance() {
        return sInstance;
    }

    public static boolean isRunning() {
        return sInstance != null;
    }

    @Override
    public void onCreate() {
        super.onCreate();
        sInstance = this;
        initTTS();
    }

    @Override
    protected void onServiceConnected() {
        super.onServiceConnected();
        sInstance = this;
        Log.i(TAG, "SightGuide Accessibility Service connected.");
        speak("SightGuide whole-phone voice accessibility is now active.");
        mHandler.post(this::initFloatingOverlay);
    }

    @Override
    public void onAccessibilityEvent(AccessibilityEvent event) {
        // Active window event monitoring if needed for state tracking
    }

    @Override
    public void onInterrupt() {
        Log.w(TAG, "SightGuide Accessibility Service interrupted.");
        if (mTTS != null && mTTS.isSpeaking()) {
            mTTS.stop();
        }
    }

    @Override
    public void onDestroy() {
        sInstance = null;
        removeFloatingOverlay();
        if (mSpeechRecognizer != null) {
            mSpeechRecognizer.destroy();
            mSpeechRecognizer = null;
        }
        if (mTTS != null) {
            mTTS.stop();
            mTTS.shutdown();
            mTTS = null;
        }
        super.onDestroy();
    }

    // ==========================================
    // Text-to-Speech (Auditory Feedback)
    // ==========================================

    private void initTTS() {
        mTTS = new TextToSpeech(this, status -> {
            if (status == TextToSpeech.SUCCESS) {
                mTTS.setLanguage(Locale.US);
                mTTS.setSpeechRate(1.05f);
                mTTSReady = true;
            }
        });
    }

    public void speak(String text) {
        if (text == null || text.trim().isEmpty()) return;
        mHandler.post(() -> {
            if (mTTS != null && mTTSReady) {
                mTTS.speak(text, TextToSpeech.QUEUE_FLUSH, null, "a11y_tts_" + System.currentTimeMillis());
            }
        });
    }

    // ==========================================
    // Floating Accessible Voice Overlay Trigger
    // ==========================================

    private void initFloatingOverlay() {
        if (mOverlayView != null) return;
        try {
            mWindowManager = (WindowManager) getSystemService(WINDOW_SERVICE);
            if (mWindowManager == null) return;

            int layoutType;
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
                layoutType = WindowManager.LayoutParams.TYPE_ACCESSIBILITY_OVERLAY;
            } else {
                layoutType = WindowManager.LayoutParams.TYPE_PHONE;
            }

            WindowManager.LayoutParams params = new WindowManager.LayoutParams(
                    WindowManager.LayoutParams.WRAP_CONTENT,
                    WindowManager.LayoutParams.WRAP_CONTENT,
                    layoutType,
                    WindowManager.LayoutParams.FLAG_NOT_FOCUSABLE | WindowManager.LayoutParams.FLAG_LAYOUT_IN_SCREEN,
                    PixelFormat.TRANSLUCENT
            );
            params.gravity = Gravity.BOTTOM | Gravity.END;
            params.x = 36;
            params.y = 120;

            FrameLayout container = new FrameLayout(this);
            Button micButton = new Button(this);
            micButton.setText("🎙️ Voice");
            micButton.setContentDescription("SightGuide Voice Control. Tap to speak phone command.");
            micButton.setBackgroundColor(Color.parseColor("#FFE171"));
            micButton.setTextColor(Color.parseColor("#121317"));
            micButton.setTextSize(15f);
            micButton.setPadding(28, 20, 28, 20);

            micButton.setOnClickListener(v -> toggleVoiceRecognition());

            container.addView(micButton);
            mOverlayView = container;
            mWindowManager.addView(mOverlayView, params);
            mOverlayVisible = true;
        } catch (Exception e) {
            Log.e(TAG, "Failed to create accessibility overlay: " + e.getMessage());
        }
    }

    public void setOverlayVisible(boolean visible) {
        mHandler.post(() -> {
            if (mOverlayView == null && visible) {
                initFloatingOverlay();
                return;
            }
            if (mOverlayView != null) {
                mOverlayView.setVisibility(visible ? View.VISIBLE : View.GONE);
                mOverlayVisible = visible;
            }
        });
    }

    private void removeFloatingOverlay() {
        if (mWindowManager != null && mOverlayView != null) {
            try {
                mWindowManager.removeView(mOverlayView);
            } catch (Exception ignored) {
            }
            mOverlayView = null;
            mOverlayVisible = false;
        }
    }

    // ==========================================
    // Native Speech Recognizer Outside App
    // ==========================================

    public void toggleVoiceRecognition() {
        mHandler.post(() -> {
            if (mIsListening) {
                stopListening();
            } else {
                startListening();
            }
        });
    }

    private void startListening() {
        if (!SpeechRecognizer.isRecognitionAvailable(this)) {
            speak("Speech recognition is not available on this device.");
            return;
        }
        if (mSpeechRecognizer == null) {
            mSpeechRecognizer = SpeechRecognizer.createSpeechRecognizer(this);
        }
        mSpeechRecognizer.setRecognitionListener(new RecognitionListener() {
            @Override
            public void onReadyForSpeech(Bundle params) {
                mIsListening = true;
                speak("Listening.");
            }

            @Override
            public void onBeginningOfSpeech() {}

            @Override
            public void onRmsChanged(float rmsdB) {}

            @Override
            public void onBufferReceived(byte[] buffer) {}

            @Override
            public void onEndOfSpeech() {
                mIsListening = false;
            }

            @Override
            public void onError(int error) {
                mIsListening = false;
                Log.w(TAG, "Speech recognition error: " + error);
            }

            @Override
            public void onResults(Bundle results) {
                mIsListening = false;
                ArrayList<String> matches = results.getStringArrayList(SpeechRecognizer.RESULTS_RECOGNITION);
                if (matches != null && !matches.isEmpty()) {
                    String spoken = matches.get(0);
                    Log.i(TAG, "Recognized spoken command outside app: " + spoken);
                    handleSpokenCommand(spoken);
                }
            }

            @Override
            public void onPartialResults(Bundle partialResults) {}

            @Override
            public void onEvent(int eventType, Bundle params) {}
        });

        Intent intent = new Intent(RecognizerIntent.ACTION_RECOGNIZE_SPEECH);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE_MODEL, RecognizerIntent.LANGUAGE_MODEL_FREE_FORM);
        intent.putExtra(RecognizerIntent.EXTRA_LANGUAGE, Locale.getDefault());
        intent.putExtra(RecognizerIntent.EXTRA_MAX_RESULTS, 1);
        mSpeechRecognizer.startListening(intent);
    }

    private void stopListening() {
        if (mSpeechRecognizer != null && mIsListening) {
            mSpeechRecognizer.stopListening();
            mIsListening = false;
        }
    }

    // ==========================================
    // Command Dispatching
    // ==========================================

    public void handleSpokenCommand(String text) {
        String clean = (text != null ? text.trim() : "");
        if (clean.isEmpty()) return;

        // Check for safety confirmation response
        if (mPendingSensitiveAction != null) {
            String lower = clean.toLowerCase(Locale.US);
            if (lower.contains("yes") || lower.contains("confirm") || lower.contains("proceed") || lower.contains("do it")) {
                speak("Confirmed.");
                Runnable action = mPendingActionRunnable;
                mPendingSensitiveAction = null;
                mPendingActionRunnable = null;
                if (action != null) action.run();
                return;
            } else if (lower.contains("no") || lower.contains("cancel") || lower.contains("stop") || lower.contains("abort")) {
                speak("Action canceled.");
                mPendingSensitiveAction = null;
                mPendingActionRunnable = null;
                return;
            }
        }

        String lower = clean.toLowerCase(Locale.US);

        // App Launch: "open [app]" or "launch [app]"
        if (lower.startsWith("open ") || lower.startsWith("launch ")) {
            String target = lower.replaceFirst("^(open|launch)\\s+", "").trim();
            // If target is ordinal like "first video", click it instead
            if (target.matches("^(the\\s+)?(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|next)\\s+.*")) {
                executeOrdinalClick(target);
                return;
            }
            launchAppByName(target);
            return;
        }

        // Search: "search for [query]"
        if (lower.startsWith("search for ") || lower.startsWith("search ")) {
            String query = lower.replaceFirst("^search(\\s+for)?\\s+", "").trim();
            executeInAppSearch(query);
            return;
        }

        // Typing / Dictating: "type: [text]" or "type [text]" or "write [text]"
        if (lower.startsWith("type:") || lower.startsWith("type ") || lower.startsWith("write ") || lower.startsWith("enter ")) {
            String textToType = clean.replaceFirst("^(?i)(type:|type|write|enter)\\s*", "").trim();
            executeType(textToType);
            return;
        }

        // Media Controls: "play" or "pause" or "resume"
        if (lower.equals("play") || lower.equals("resume") || lower.equals("play video") || lower.equals("play music")) {
            executeMediaControl("play");
            return;
        }
        if (lower.equals("pause") || lower.equals("pause video") || lower.equals("pause music")) {
            executeMediaControl("pause");
            return;
        }

        // Scrolling: "scroll down", "scroll up", "swipe down", "swipe up"
        if (lower.contains("scroll down") || lower.contains("swipe down") || lower.contains("page down")) {
            executeScroll("down");
            return;
        }
        if (lower.contains("scroll up") || lower.contains("swipe up") || lower.contains("page up")) {
            executeScroll("up");
            return;
        }

        // System Navigation: "go back", "go home", "recent apps"
        if (lower.contains("go back") || lower.equals("back")) {
            executeGlobalNav("back");
            return;
        }
        if (lower.contains("go home") || lower.equals("home") || lower.contains("home screen")) {
            executeGlobalNav("home");
            return;
        }
        if (lower.contains("recent apps") || lower.contains("recents") || lower.contains("show recents")) {
            executeGlobalNav("recents");
            return;
        }
        if (lower.contains("notifications") || lower.contains("open notifications")) {
            executeGlobalNav("notifications");
            return;
        }

        // Read Screen: "read screen", "what's on my screen"
        if (lower.contains("read screen") || lower.contains("what is on my screen") || lower.contains("what's on my screen")) {
            executeReadScreen();
            return;
        }

        // Ordinal click: "click the first video"
        if (lower.matches(".*\\b(first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|next)\\s+.*")) {
            executeOrdinalClick(lower);
            return;
        }

        // Click / Tap: "click [target]" or "tap [target]" or "send"
        if (lower.startsWith("click ") || lower.startsWith("tap ") || lower.startsWith("press ") || lower.startsWith("select ")) {
            String target = lower.replaceFirst("^(click|tap|press|select)\\s+(on\\s+)?(the\\s+)?", "").trim();
            executeClick(target);
            return;
        }

        // Direct single-word button fallback (e.g., "send", "submit", "next", "done", "cancel")
        if (lower.equals("send") || lower.equals("submit") || lower.equals("next") || lower.equals("done") || lower.equals("cancel")) {
            executeClick(lower);
            return;
        }

        // General target click fallback
        executeClick(clean);
    }

    // ==========================================
    // Generic Accessibility Action Implementations
    // ==========================================

    public boolean executeClick(String targetQuery) {
        if (targetQuery == null || targetQuery.trim().isEmpty()) return false;
        String query = targetQuery.trim();

        // Safety check for sensitive actions
        if (mSafetyConfirmationEnabled && isSensitiveAction(query)) {
            promptSensitiveConfirmation(query, () -> performDirectClick(query, null));
            return true;
        }

        return performDirectClick(query, null);
    }

    public boolean executeOrdinalClick(String queryWithOrdinal) {
        String lower = queryWithOrdinal.toLowerCase(Locale.US);
        int ordinal = 1;
        if (lower.contains("second") || lower.contains("2nd")) ordinal = 2;
        else if (lower.contains("third") || lower.contains("3rd")) ordinal = 3;
        else if (lower.contains("fourth") || lower.contains("4th")) ordinal = 4;
        else if (lower.contains("fifth") || lower.contains("5th")) ordinal = 5;
        else if (lower.contains("last")) ordinal = -1;

        String target = lower.replaceAll("\\b(open|click|tap|select|play|the|first|second|third|fourth|fifth|1st|2nd|3rd|4th|5th|last|next)\\b", "").trim();
        if (target.isEmpty()) target = "item";

        return performDirectClick(target, ordinal);
    }

    private boolean performDirectClick(String query, Integer ordinal) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("I cannot access this screen. The active app may be restricting accessibility.");
            return false;
        }

        List<AccessibilityNodeInfo> matches = new ArrayList<>();
        findMatchingNodes(root, query.toLowerCase(Locale.US), matches);

        if (matches.isEmpty()) {
            // Fallback: search across all interactive clickable nodes if query is generic like "item" or "video"
            findClickableNodes(root, matches);
        }

        if (matches.isEmpty()) {
            speak("I could not find " + query + " on the screen.");
            root.recycle();
            return false;
        }

        // Handle ambiguity if multiple matches and no ordinal specified
        if (matches.size() > 1 && ordinal == null) {
            speak("I found " + matches.size() + " items matching " + query + ". Opening the first one. You can say: open the second " + query + ", to pick another.");
            ordinal = 1;
        }

        AccessibilityNodeInfo targetNode;
        if (ordinal != null) {
            if (ordinal == -1) {
                targetNode = matches.get(matches.size() - 1);
            } else {
                int index = Math.max(0, Math.min(ordinal - 1, matches.size() - 1));
                targetNode = matches.get(index);
            }
        } else {
            targetNode = matches.get(0);
        }

        boolean clicked = clickNodeOrParent(targetNode);
        if (clicked) {
            String label = getNodeLabel(targetNode);
            speak("Opened " + (label != null ? label : query) + ".");
        } else {
            // Gesture tap fallback
            Rect bounds = new Rect();
            targetNode.getBoundsInScreen(bounds);
            if (!bounds.isEmpty()) {
                dispatchGestureTap(bounds.centerX(), bounds.centerY());
                speak("Tapped " + query + ".");
                clicked = true;
            } else {
                speak("Could not click " + query + ".");
            }
        }

        root.recycle();
        return clicked;
    }

    public boolean executeType(String textToType) {
        if (textToType == null) return false;
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("Cannot access the screen to type.");
            return false;
        }

        AccessibilityNodeInfo targetField = root.findFocus(AccessibilityNodeInfo.FOCUS_INPUT);
        if (targetField == null) {
            targetField = findFirstEditableNode(root);
        }

        if (targetField == null) {
            speak("No text input field is currently active or focused.");
            root.recycle();
            return false;
        }

        Bundle args = new Bundle();
        args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, textToType);
        boolean success = targetField.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);

        if (success) {
            speak("Typed: " + textToType);
        } else {
            speak("Failed to type text into the field.");
        }

        targetField.recycle();
        root.recycle();
        return success;
    }

    public boolean executeInAppSearch(String query) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("Cannot read the screen to search.");
            return false;
        }

        // 1. Look for search button/icon or existing search input
        List<AccessibilityNodeInfo> searchNodes = new ArrayList<>();
        findMatchingNodes(root, "search", searchNodes);

        if (!searchNodes.isEmpty()) {
            AccessibilityNodeInfo searchNode = searchNodes.get(0);
            if (searchNode.isEditable()) {
                Bundle args = new Bundle();
                args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, query);
                searchNode.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
                speak("Searching for " + query + ".");
                root.recycle();
                return true;
            } else {
                clickNodeOrParent(searchNode);
                mHandler.postDelayed(() -> executeType(query), 450);
                root.recycle();
                return true;
            }
        }

        // Fallback: check if an editable field is already visible and type into it
        AccessibilityNodeInfo editable = findFirstEditableNode(root);
        if (editable != null) {
            Bundle args = new Bundle();
            args.putCharSequence(AccessibilityNodeInfo.ACTION_ARGUMENT_SET_TEXT_CHARSEQUENCE, query);
            editable.performAction(AccessibilityNodeInfo.ACTION_SET_TEXT, args);
            speak("Searching for " + query + ".");
            root.recycle();
            return true;
        }

        speak("Could not locate a search bar on this screen.");
        root.recycle();
        return false;
    }

    public boolean executeMediaControl(String command) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("Cannot access media controls on this screen.");
            return false;
        }

        String targetWord = command.equalsIgnoreCase("pause") ? "pause" : "play";
        List<AccessibilityNodeInfo> matches = new ArrayList<>();
        findMatchingNodes(root, targetWord, matches);

        if (!matches.isEmpty()) {
            clickNodeOrParent(matches.get(0));
            speak(targetWord.substring(0, 1).toUpperCase() + targetWord.substring(1) + "ing.");
            root.recycle();
            return true;
        }

        // Toggle center screen tap as fallback for video players (e.g. YouTube fullscreen)
        int screenWidth = getResources().getDisplayMetrics().widthPixels;
        int screenHeight = getResources().getDisplayMetrics().heightPixels;
        dispatchGestureTap(screenWidth / 2, screenHeight / 3);
        speak((targetWord.equals("pause") ? "Paused" : "Playing") + " media.");

        root.recycle();
        return true;
    }

    public boolean executeScroll(String direction) {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("Cannot scroll this screen.");
            return false;
        }

        AccessibilityNodeInfo scrollable = findFirstScrollableNode(root);
        boolean scrolled = false;

        if (scrollable != null) {
            if ("up".equalsIgnoreCase(direction)) {
                scrolled = scrollable.performAction(AccessibilityNodeInfo.ACTION_SCROLL_BACKWARD);
            } else {
                scrolled = scrollable.performAction(AccessibilityNodeInfo.ACTION_SCROLL_FORWARD);
            }
        }

        if (!scrolled) {
            // Gesture swipe fallback
            int width = getResources().getDisplayMetrics().widthPixels;
            int height = getResources().getDisplayMetrics().heightPixels;
            int startX = width / 2;
            int startY = "up".equalsIgnoreCase(direction) ? (height / 4) : (3 * height / 4);
            int endY = "up".equalsIgnoreCase(direction) ? (3 * height / 4) : (height / 4);
            dispatchGestureSwipe(startX, startY, startX, endY);
            scrolled = true;
        }

        speak("Scrolled " + direction + ".");
        root.recycle();
        return scrolled;
    }

    public boolean executeGlobalNav(String action) {
        int globalAction;
        String announcement;

        switch (action.toLowerCase(Locale.US)) {
            case "home":
                globalAction = GLOBAL_ACTION_HOME;
                announcement = "Going home.";
                break;
            case "recents":
                globalAction = GLOBAL_ACTION_RECENTS;
                announcement = "Showing recent applications.";
                break;
            case "notifications":
                globalAction = GLOBAL_ACTION_NOTIFICATIONS;
                announcement = "Opening notifications.";
                break;
            case "quick_settings":
                globalAction = GLOBAL_ACTION_QUICK_SETTINGS;
                announcement = "Opening quick settings.";
                break;
            case "back":
            default:
                globalAction = GLOBAL_ACTION_BACK;
                announcement = "Going back.";
                break;
        }

        boolean result = performGlobalAction(globalAction);
        speak(announcement);
        return result;
    }

    public boolean launchAppByName(String appName) {
        PackageManager pm = getPackageManager();
        List<ApplicationInfo> packages = pm.getInstalledApplications(PackageManager.GET_META_DATA);
        String targetClean = appName.toLowerCase(Locale.US).trim();

        String bestPackage = null;
        for (ApplicationInfo app : packages) {
            String label = pm.getApplicationLabel(app).toString().toLowerCase(Locale.US);
            if (label.equals(targetClean) || label.contains(targetClean) || targetClean.contains(label)) {
                bestPackage = app.packageName;
                break;
            }
        }

        // Hardcoded fallbacks for popular accessibility apps
        if (bestPackage == null) {
            if (targetClean.contains("youtube")) bestPackage = "com.google.android.youtube";
            else if (targetClean.contains("whatsapp")) bestPackage = "com.whatsapp";
            else if (targetClean.contains("chrome") || targetClean.contains("browser")) bestPackage = "com.android.chrome";
            else if (targetClean.contains("settings")) bestPackage = "com.android.settings";
            else if (targetClean.contains("camera")) bestPackage = "com.google.android.GoogleCamera";
            else if (targetClean.contains("spotify")) bestPackage = "com.spotify.music";
        }

        if (bestPackage != null) {
            Intent intent = pm.getLaunchIntentForPackage(bestPackage);
            if (intent != null) {
                intent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
                startActivity(intent);
                speak("Opening " + appName + ".");
                return true;
            }
        }

        speak("I could not find an app named " + appName + " on your phone.");
        return false;
    }

    public void executeReadScreen() {
        AccessibilityNodeInfo root = getRootInActiveWindow();
        if (root == null) {
            speak("I cannot read this screen.");
            return;
        }

        List<String> items = new ArrayList<>();
        collectScreenSummary(root, items);

        if (items.isEmpty()) {
            speak("This screen does not contain readable elements.");
        } else {
            StringBuilder sb = new StringBuilder("On this screen: ");
            int maxItems = Math.min(items.size(), 6);
            for (int i = 0; i < maxItems; i++) {
                sb.append(items.get(i));
                if (i < maxItems - 1) sb.append(", ");
            }
            if (items.size() > maxItems) {
                sb.append(". And ").append(items.size() - maxItems).append(" more items.");
            }
            speak(sb.toString());
        }

        root.recycle();
    }

    // ==========================================
    // Safety & Confirmation Engine
    // ==========================================

    private boolean isSensitiveAction(String text) {
        if (text == null) return false;
        String lower = text.toLowerCase(Locale.US);
        return lower.contains("delete") ||
                lower.contains("uninstall") ||
                lower.contains("erase") ||
                lower.contains("wipe") ||
                lower.contains("format") ||
                lower.contains("clear all") ||
                lower.contains("send money") ||
                lower.contains("pay");
    }

    private void promptSensitiveConfirmation(String actionDescription, Runnable onConfirmed) {
        mPendingSensitiveAction = actionDescription;
        mPendingActionRunnable = onConfirmed;
        speak("This action will " + actionDescription + ". Please say Yes to confirm, or Cancel to stop.");
    }

    public void setSafetyConfirmationEnabled(boolean enabled) {
        this.mSafetyConfirmationEnabled = enabled;
    }

    public boolean isSafetyConfirmationEnabled() {
        return mSafetyConfirmationEnabled;
    }

    // ==========================================
    // Node Inspection & Traversal Helpers
    // ==========================================

    private void findMatchingNodes(AccessibilityNodeInfo node, String query, List<AccessibilityNodeInfo> results) {
        if (node == null) return;

        String text = node.getText() != null ? node.getText().toString().toLowerCase(Locale.US) : "";
        String desc = node.getContentDescription() != null ? node.getContentDescription().toString().toLowerCase(Locale.US) : "";
        String viewId = node.getViewIdResourceName() != null ? node.getViewIdResourceName().toLowerCase(Locale.US) : "";

        boolean matches = (!text.isEmpty() && text.contains(query)) ||
                (!desc.isEmpty() && desc.contains(query)) ||
                (!viewId.isEmpty() && viewId.contains(query));

        if (matches && (node.isClickable() || node.isCheckable() || node.isEditable() || hasClickableParent(node))) {
            results.add(node);
        }

        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                findMatchingNodes(child, query, results);
            }
        }
    }

    private void findClickableNodes(AccessibilityNodeInfo node, List<AccessibilityNodeInfo> results) {
        if (node == null) return;
        if (node.isClickable() && node.isVisibleToUser()) {
            results.add(node);
        }
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                findClickableNodes(child, results);
            }
        }
    }

    private AccessibilityNodeInfo findFirstEditableNode(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isEditable()) return node;
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                AccessibilityNodeInfo res = findFirstEditableNode(child);
                if (res != null) return res;
            }
        }
        return null;
    }

    private AccessibilityNodeInfo findFirstScrollableNode(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.isScrollable()) return node;
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                AccessibilityNodeInfo res = findFirstScrollableNode(child);
                if (res != null) return res;
            }
        }
        return null;
    }

    private boolean clickNodeOrParent(AccessibilityNodeInfo node) {
        if (node == null) return false;
        if (node.isClickable() && node.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
            return true;
        }
        AccessibilityNodeInfo parent = node.getParent();
        while (parent != null) {
            if (parent.isClickable() && parent.performAction(AccessibilityNodeInfo.ACTION_CLICK)) {
                parent.recycle();
                return true;
            }
            AccessibilityNodeInfo temp = parent.getParent();
            parent.recycle();
            parent = temp;
        }
        return false;
    }

    private boolean hasClickableParent(AccessibilityNodeInfo node) {
        if (node == null) return false;
        AccessibilityNodeInfo parent = node.getParent();
        while (parent != null) {
            if (parent.isClickable()) {
                parent.recycle();
                return true;
            }
            AccessibilityNodeInfo temp = parent.getParent();
            parent.recycle();
            parent = temp;
        }
        return false;
    }

    private String getNodeLabel(AccessibilityNodeInfo node) {
        if (node == null) return null;
        if (node.getText() != null && !node.getText().toString().trim().isEmpty()) {
            return node.getText().toString().trim();
        }
        if (node.getContentDescription() != null && !node.getContentDescription().toString().trim().isEmpty()) {
            return node.getContentDescription().toString().trim();
        }
        return null;
    }

    private void collectScreenSummary(AccessibilityNodeInfo node, List<String> list) {
        if (node == null || list.size() > 10) return;
        String label = getNodeLabel(node);
        if (label != null && label.length() > 1 && !list.contains(label) && (node.isClickable() || node.isEditable() || node.isHeading())) {
            list.add(label);
        }
        int count = node.getChildCount();
        for (int i = 0; i < count; i++) {
            AccessibilityNodeInfo child = node.getChild(i);
            if (child != null) {
                collectScreenSummary(child, list);
                child.recycle();
            }
        }
    }

    // ==========================================
    // Gesture Dispatch Fallbacks
    // ==========================================

    private void dispatchGestureTap(int x, int y) {
        Path path = new Path();
        path.moveTo(x, y);
        GestureDescription.StrokeDescription stroke = new GestureDescription.StrokeDescription(path, 0, 50);
        GestureDescription.Builder builder = new GestureDescription.Builder();
        builder.addStroke(stroke);
        dispatchGesture(builder.build(), null, null);
    }

    private void dispatchGestureSwipe(int startX, int startY, int endX, int endY) {
        Path path = new Path();
        path.moveTo(startX, startY);
        path.lineTo(endX, endY);
        GestureDescription.StrokeDescription stroke = new GestureDescription.StrokeDescription(path, 0, 250);
        GestureDescription.Builder builder = new GestureDescription.Builder();
        builder.addStroke(stroke);
        dispatchGesture(builder.build(), null, null);
    }
}
