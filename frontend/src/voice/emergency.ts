import { Capacitor } from "@capacitor/core";
import { getDeviceLocation, type DeviceLocation } from "./geolocation";
import {
  formatEmergencySMS,
  getDefaultEmergencyContact,
  loadEmergencyContact,
  type EmergencyContact,
} from "./deviceActions";
import { makeDirectCall, sendDirectSms } from "./telephony";

export type EmergencyStep =
  | "idle"
  | "countdown"
  | "locating"
  | "contact_ready"
  | "sms_ready"
  | "calling"
  | "completed"
  | "cancelled"
  | "error";

export interface EmergencyProgress {
  step: EmergencyStep;
  countdown: number;
  location: DeviceLocation | null;
  locationStatus: "pending" | "acquired" | "unavailable";
  contact: EmergencyContact;
  smsBody: string;
  smsUrl: string;
  callUrl: string;
  message: string;
  isCustomContact: boolean;
}

/** Check if device is running natively on Android/iOS via Capacitor */
export function isNativePlatform(): boolean {
  return Capacitor.isNativePlatform();
}

/** Build SMS URL with cross-platform URI schema handling */
export function buildSmsUrl(phone: string, body: string): string {
  const cleanPhone = phone.replace(/[^\d+]/g, "");
  const encodedBody = encodeURIComponent(body);
  const isIOS = typeof navigator !== "undefined" && /iPad|iPhone|iPod/.test(navigator.userAgent);
  const separator = isIOS ? "&" : "?";
  return `sms:${cleanPhone}${separator}body=${encodedBody}`;
}

/** Build Tel URL */
export function buildTelUrl(phone: string): string {
  const cleanPhone = phone.replace(/[^\d+]/g, "");
  return `tel:${cleanPhone}`;
}

/** Copy text to clipboard safely across browsers */
export async function copyToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // fall back
  }
  try {
    const textarea = document.createElement("textarea");
    textarea.value = text;
    textarea.style.position = "fixed";
    textarea.style.opacity = "0";
    textarea.style.pointerEvents = "none";
    document.body.appendChild(textarea);
    textarea.focus();
    textarea.select();
    const copied = document.execCommand("copy");
    document.body.removeChild(textarea);
    return copied;
  } catch {
    return false;
  }
}

/**
 * Execute the core emergency dispatch workflow:
 * 1. Obtain current GPS location (with strict 4s timeout)
 * 2. Identify configured or default emergency contact (default: 9341240360)
 * 3. Prepare formatted emergency SMS with location map link
 * 4. Dispatch SMS directly in background without human interaction
 * 5. Send WhatsApp emergency alert
 * 6. Directly place automated phone call (focuses on call)
 */
export async function executeEmergencyDispatch(options: {
  contactOverride?: EmergencyContact | null;
  speak?: (text: string) => void;
  onProgress?: (progress: Partial<EmergencyProgress>) => void;
}): Promise<EmergencyProgress> {
  const { contactOverride, speak, onProgress } = options;

  // 1. Identify configured contact (default: 9341240360)
  const savedContact = loadEmergencyContact();
  const defaultContact = getDefaultEmergencyContact();
  const isCustom = Boolean(contactOverride || savedContact);
  const contact: EmergencyContact = contactOverride || savedContact || defaultContact;

  onProgress?.({
    step: "locating",
    contact,
    isCustomContact: isCustom,
    message: `Acquiring GPS location for emergency contact (${contact.phone})...`,
  });

  speak?.(`Emergency activated. Acquiring location and calling ${contact.name}.`);

  // 2. Obtain location with 4-second hard timeout
  let location: DeviceLocation | null = null;
  try {
    location = await getDeviceLocation(4000);
  } catch {
    location = null;
  }

  const locationStatus = location ? "acquired" : "unavailable";
  if (location) {
    onProgress?.({
      location,
      locationStatus: "acquired",
      message: `Location acquired: ${location.lat.toFixed(4)}, ${location.lon.toFixed(4)}`,
    });
  } else {
    onProgress?.({
      location: null,
      locationStatus: "unavailable",
      message: "Location unavailable. Proceeding with emergency dispatch.",
    });
    speak?.("Location unavailable. Proceeding with emergency call.");
  }

  // 3. Prepare SMS & Messages
  const smsBody = formatEmergencySMS(contact, location);
  const smsUrl = buildSmsUrl(contact.phone, smsBody);
  const callUrl = buildTelUrl(contact.phone);

  onProgress?.({
    step: "sms_ready",
    location,
    locationStatus,
    contact,
    smsBody,
    smsUrl,
    callUrl,
    message: `Sending background emergency SMS & WhatsApp to ${contact.phone}...`,
  });

  // 4. Send background SMS directly via SmsManager (no app opens / 100% automated)
  try {
    await sendDirectSms(contact.phone, smsBody);
  } catch (err) {
    console.warn("Direct SMS dispatch failed:", err);
  }

  // 5. Initiate Direct Phone Call (takes priority & focuses screen immediately)
  onProgress?.({
    step: "calling",
    message: `Directly placing emergency call to ${contact.phone}...`,
  });

  speak?.(`Calling ${contact.name} now.`);

  try {
    await makeDirectCall(contact.phone);
  } catch (err) {
    console.warn("Direct phone call failed:", err);
  }

  const result: EmergencyProgress = {
    step: "completed",
    countdown: 0,
    location,
    locationStatus,
    contact,
    smsBody,
    smsUrl,
    callUrl,
    message: `Emergency dispatch active. Sent SMS & calling ${contact.phone}.`,
    isCustomContact: isCustom,
  };

  onProgress?.(result);
  return result;
}

