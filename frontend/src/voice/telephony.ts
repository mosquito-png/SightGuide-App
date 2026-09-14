import { Capacitor, registerPlugin } from "@capacitor/core";

export interface DirectTelephonyPluginInterface {
  checkPermissions(): Promise<{ camera?: string; microphone?: string; location?: string; call: string; sms: string }>;
  requestTelephonyPermissions(): Promise<{ call: string; sms: string }>;
  requestAllAppPermissions(): Promise<{ camera?: string; microphone?: string; location?: string; call?: string; sms?: string }>;
  getNativeLocation(): Promise<{ latitude: number; longitude: number; accuracy?: number; provider?: string }>;
  directCall(options: { phoneNumber: string }): Promise<{ status: string; phoneNumber?: string; message?: string }>;
  directSms(options: { phoneNumber: string; message: string }): Promise<{ status: string; phoneNumber?: string; parts?: number; message?: string }>;
  sendWhatsApp(options: { phoneNumber: string; message: string }): Promise<{ status: string }>;
}

const DirectTelephony = registerPlugin<DirectTelephonyPluginInterface>("DirectTelephony");

/** Check if running inside native Android app where DirectTelephony is supported */
export function isNativeTelephonyAvailable(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";
}

/** Request all required permissions (Camera, Microphone, GPS Location, Calling, SMS) upfront on app startup */
export async function requestAllAppStartupPermissions(): Promise<void> {
  if (!isNativeTelephonyAvailable()) {
    return;
  }
  try {
    await DirectTelephony.requestAllAppPermissions();
  } catch (error) {
    console.warn("App startup permissions request failed:", error);
  }
}

/** Fetch fast native GPS coordinates from Android LocationManager */
export async function getFastNativeLocation(): Promise<{ lat: number; lon: number } | null> {
  if (!isNativeTelephonyAvailable()) {
    return null;
  }
  try {
    const res = await DirectTelephony.getNativeLocation();
    if (typeof res.latitude === "number" && typeof res.longitude === "number") {
      return { lat: res.latitude, lon: res.longitude };
    }
  } catch (err) {
    console.warn("Fast native location lookup failed:", err);
  }
  return null;
}

/** Request runtime CALL_PHONE and SEND_SMS permissions */
export async function requestTelephonyPermissions(): Promise<{ call: boolean; sms: boolean }> {
  if (!isNativeTelephonyAvailable()) {
    return { call: false, sms: false };
  }
  try {
    const res = await DirectTelephony.requestTelephonyPermissions();
    return {
      call: res.call === "granted",
      sms: res.sms === "granted",
    };
  } catch (error) {
    console.warn("Telephony permissions request failed:", error);
    return { call: false, sms: false };
  }
}

/**
 * Directly places an outbound phone call.
 * On Native Android: Directly dials via Intent.ACTION_CALL without showing the dialpad.
 * In Browser fallback: Opens tel: URI.
 */
export async function makeDirectCall(phoneNumber: string): Promise<{ success: boolean; status: string }> {
  const cleanNumber = phoneNumber.replace(/[^\d+]/g, "").trim();
  if (!cleanNumber) {
    return { success: false, status: "invalid_number" };
  }

  if (isNativeTelephonyAvailable()) {
    try {
      const res = await DirectTelephony.directCall({ phoneNumber: cleanNumber });
      return { success: true, status: res.status };
    } catch (error) {
      console.warn("Direct native call failed, falling back to tel: URI:", error);
    }
  }

  // Web fallback
  try {
    window.location.href = `tel:${cleanNumber}`;
    return { success: true, status: "tel_uri" };
  } catch (err) {
    return { success: false, status: "error" };
  }
}

/**
 * Directly sends a text message in the background.
 * On Native Android: Directly transmits via Android SmsManager without opening messaging app.
 * In Browser fallback: Opens sms: URI.
 */
export async function sendDirectSms(
  phoneNumber: string,
  message: string,
): Promise<{ success: boolean; status: string }> {
  const cleanNumber = phoneNumber.replace(/[^\d+]/g, "").trim();
  if (!cleanNumber || !message) {
    return { success: false, status: "missing_fields" };
  }

  if (isNativeTelephonyAvailable()) {
    try {
      const res = await DirectTelephony.directSms({ phoneNumber: cleanNumber, message });
      return { success: true, status: res.status };
    } catch (error) {
      console.warn("Direct native SMS failed, falling back to sms: URI:", error);
    }
  }

  // Web fallback
  try {
    const isIOS = typeof navigator !== "undefined" && /iPad|iPhone|iPod/.test(navigator.userAgent);
    const separator = isIOS ? "&" : "?";
    window.location.href = `sms:${cleanNumber}${separator}body=${encodeURIComponent(message)}`;
    return { success: true, status: "sms_uri" };
  } catch (err) {
    return { success: false, status: "error" };
  }
}

/**
 * Dispatches a WhatsApp message with prefilled emergency text.
 */
export async function sendWhatsAppAlert(
  phoneNumber: string,
  message: string,
): Promise<{ success: boolean; status: string }> {
  let cleanNumber = phoneNumber.replace(/[^\d]/g, "").trim();
  if (cleanNumber.length === 10) {
    cleanNumber = `91${cleanNumber}`;
  }

  if (isNativeTelephonyAvailable()) {
    try {
      const res = await DirectTelephony.sendWhatsApp({ phoneNumber: cleanNumber, message });
      return { success: true, status: res.status };
    } catch (error) {
      console.warn("Native WhatsApp dispatch failed:", error);
    }
  }

  // Web fallback
  try {
    const url = `https://wa.me/${cleanNumber}?text=${encodeURIComponent(message)}`;
    window.open(url, "_blank");
    return { success: true, status: "whatsapp_web" };
  } catch {
    return { success: false, status: "error" };
  }
}

/**
 * Register a listener for when the active phone call is completed / ended by the user or remote party.
 */
export function addCallEndedListener(callback: () => void): () => void {
  if (!isNativeTelephonyAvailable()) {
    return () => {};
  }
  let removed = false;
  let listenerPromise: Promise<any> | null = null;

  try {
    listenerPromise = (DirectTelephony as any).addListener("callEnded", () => {
      if (!removed) {
        callback();
      }
    });
  } catch (err) {
    console.warn("Failed to attach callEnded listener:", err);
  }

  return () => {
    removed = true;
    if (listenerPromise) {
      listenerPromise.then((handle: any) => handle?.remove?.()).catch(() => {});
    }
  };
}

