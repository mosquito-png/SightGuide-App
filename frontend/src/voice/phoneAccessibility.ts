import { Capacitor, registerPlugin } from "@capacitor/core";

export interface PhoneAccessibilityPluginInterface {
  isAccessibilityServiceEnabled(): Promise<{ enabled: boolean; running: boolean }>;
  openAccessibilitySettings(): Promise<{ opened: boolean }>;
  executeAction(options: {
    action: string;
    target?: string;
    text?: string;
    direction?: string;
    ordinal?: number;
    globalAction?: string;
  }): Promise<{ success: boolean; message: string }>;
  setOverlayVisible(options: { visible: boolean }): Promise<{ visible: boolean }>;
  setSafetyConfirmation(options: { enabled: boolean }): Promise<{ enabled: boolean }>;
}

const PhoneAccessibility = registerPlugin<PhoneAccessibilityPluginInterface>("PhoneAccessibility");

/** Check if running on Android device where PhoneAccessibility is supported */
export function isNativeAccessibilityAvailable(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";
}

/** Query whether SightGuide Accessibility Service is currently enabled and active */
export async function checkAccessibilityServiceStatus(): Promise<{ enabled: boolean; running: boolean }> {
  if (!isNativeAccessibilityAvailable()) {
    return { enabled: false, running: false };
  }
  try {
    return await PhoneAccessibility.isAccessibilityServiceEnabled();
  } catch (err) {
    console.warn("Failed to check accessibility service status:", err);
    return { enabled: false, running: false };
  }
}

/** Open Android Settings > Accessibility screen so user can grant service permissions */
export async function openAndroidAccessibilitySettings(): Promise<boolean> {
  if (!isNativeAccessibilityAvailable()) {
    return false;
  }
  try {
    const res = await PhoneAccessibility.openAccessibilitySettings();
    return !!res.opened;
  } catch (err) {
    console.warn("Failed to open accessibility settings:", err);
    return false;
  }
}

/** Dispatch an accessibility action (click, type, scroll, global_nav, etc.) to the Android service */
export async function dispatchPhoneAction(options: {
  action: string;
  target?: string;
  text?: string;
  direction?: string;
  ordinal?: number;
  globalAction?: string;
}): Promise<{ success: boolean; message: string }> {
  if (!isNativeAccessibilityAvailable()) {
    return {
      success: false,
      message: "Whole-phone accessibility is only available on native Android devices.",
    };
  }
  try {
    return await PhoneAccessibility.executeAction(options);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return { success: false, message: msg };
  }
}

/** Toggle visibility of the floating accessible voice trigger bubble across apps */
export async function setAccessibilityOverlay(visible: boolean): Promise<boolean> {
  if (!isNativeAccessibilityAvailable()) return false;
  try {
    const res = await PhoneAccessibility.setOverlayVisible({ visible });
    return res.visible;
  } catch (err) {
    console.warn("Failed to set overlay visibility:", err);
    return false;
  }
}

/** Toggle safety confirmation prompts before sensitive operations (e.g. delete) */
export async function setAccessibilitySafetyConfirmation(enabled: boolean): Promise<boolean> {
  if (!isNativeAccessibilityAvailable()) return false;
  try {
    const res = await PhoneAccessibility.setSafetyConfirmation({ enabled });
    return res.enabled;
  } catch (err) {
    console.warn("Failed to update safety confirmation:", err);
    return false;
  }
}
