import type { DeviceDirective } from "./voiceTypes";
import { makeDirectCall, sendDirectSms } from "./telephony";
import { dispatchPhoneAction, isNativeAccessibilityAvailable } from "./phoneAccessibility";

const CONTACTS_KEY = "sightguide.contacts";
const EMERGENCY_CONTACT_KEY = "sightguide.emergency_contact";

export interface EmergencyContact {
  name: string;
  phone: string;
  relationship?: string;
  customMessage?: string;
}

export interface SavedContact {
  name: string;
  phone: string;
}

export interface DirectivePlatform {
  speak: (text: string) => void;
  onEmergency?: (phoneNumber: string | null, location?: string | null) => void;
  onNavigate?: (destination: string) => void;
  onScreenChange?: (screen: string) => void;
  onSearch?: (query: string, url: string) => void;
  onOpenExternal?: (url: string, name: string) => void;
  onMessageSent?: (recipient: string, body: string, number?: string) => void;
  onMuteChange?: (muted: boolean) => void;
  onScanChange?: (scanning: boolean) => void;
  onCameraSwitch?: () => void;
  onUnmute?: () => void;
}

export function getDefaultEmergencyContact(): EmergencyContact {
  return {
    name: "Primary Emergency Contact",
    phone: "9341240360",
    relationship: "Emergency Contact",
  };
}

export function loadEmergencyContact(): EmergencyContact | null {
  try {
    const raw = window.localStorage.getItem(EMERGENCY_CONTACT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object" && "phone" in parsed && typeof (parsed as any).phone === "string") {
      return parsed as EmergencyContact;
    }
    return null;
  } catch {
    return null;
  }
}

export function saveEmergencyContact(contact: EmergencyContact | null): void {
  try {
    if (!contact) {
      window.localStorage.removeItem(EMERGENCY_CONTACT_KEY);
    } else {
      window.localStorage.setItem(EMERGENCY_CONTACT_KEY, JSON.stringify(contact));
    }
  } catch {
    /* storage unavailable */
  }
}

export function formatEmergencySMS(
  contact: EmergencyContact,
  location: { lat: number; lon: number } | null,
): string {
  const note = contact.customMessage ? ` ${contact.customMessage.trim()}` : "";
  if (location && typeof location.lat === "number" && typeof location.lon === "number") {
    const mapsUrl = `https://maps.google.com/?q=${location.lat.toFixed(6)},${location.lon.toFixed(6)}`;
    return `EMERGENCY ALERT: I need urgent help! My current GPS location is: ${mapsUrl} (${location.lat.toFixed(5)}, ${location.lon.toFixed(5)}).${note} - Sent via SightGuide AI`;
  }
  return `EMERGENCY ALERT: I need urgent help! My exact GPS location could not be determined.${note} - Sent via SightGuide AI`;
}

export function buildSmsUrl(phone: string, body?: string): string {
  const cleanPhone = phone.replace(/[^\d+]/g, "");
  if (!body) return `sms:${cleanPhone}`;
  const encodedBody = encodeURIComponent(body);
  const isIOS = typeof navigator !== "undefined" && /iPad|iPhone|iPod/.test(navigator.userAgent);
  const separator = isIOS ? "&" : "?";
  return `sms:${cleanPhone}${separator}body=${encodedBody}`;
}

export function loadContacts(): Record<string, string> {
  try {
    const raw = window.localStorage.getItem(CONTACTS_KEY);
    if (!raw) {
      // Provide standard initial mock contacts so users can test "call Mom", "text Dad" immediately
      const initial: Record<string, string> = {
        mom: "+1 (555) 234-5678",
        dad: "+1 (555) 876-5432",
      };
      saveContacts(initial);
      return initial;
    }
    const parsed = JSON.parse(raw) as unknown;
    if (parsed && typeof parsed === "object") return parsed as Record<string, string>;
    return {};
  } catch {
    return {};
  }
}

export function saveContacts(contacts: Record<string, string>): void {
  try {
    window.localStorage.setItem(CONTACTS_KEY, JSON.stringify(contacts));
  } catch {
    /* storage unavailable */
  }
}

export function loadContactsList(): SavedContact[] {
  const contacts = loadContacts();
  return Object.entries(contacts).map(([name, phone]) => ({ name, phone }));
}

export function addContact(name: string, phone: string): void {
  const trimmedName = name.trim().toLowerCase();
  const trimmedPhone = phone.trim();
  if (!trimmedName || !trimmedPhone) return;
  const contacts = loadContacts();
  contacts[trimmedName] = trimmedPhone;
  saveContacts(contacts);
}

export function removeContact(name: string): void {
  const trimmed = name.trim().toLowerCase();
  const contacts = loadContacts();
  delete contacts[trimmed];
  saveContacts(contacts);
}

export function findContactNumber(name: string): { name: string; number: string } | undefined {
  const contacts = loadContacts();
  const requested = String(name || "").trim().toLowerCase();
  if (!requested) return undefined;
  if (contacts[requested]) return { name: requested, number: contacts[requested] };
  const match = Object.entries(contacts).find(([key]) => key.toLowerCase().includes(requested) || requested.includes(key.toLowerCase()));
  return match ? { name: match[0], number: match[1] } : undefined;
}

function isPhoneNumber(value: string): boolean {
  const digits = String(value || "").replace(/[^\d]/g, "");
  return digits.length >= 3;
}

async function notificationGranted(): Promise<boolean> {
  if (typeof window === "undefined" || !("Notification" in window)) return false;
  if (Notification.permission === "granted") return true;
  if (Notification.permission === "denied") return false;
  try {
    const permission = await Notification.requestPermission();
    return permission === "granted";
  } catch {
    return false;
  }
}

function scheduleReminder(directive: DeviceDirective, platform: DirectivePlatform): void {
  const parameters = directive.parameters ?? {};
  const seconds = typeof parameters.seconds === "number" ? parameters.seconds : 0;
  const label = String(directive.value || parameters.text || "your reminder");
  if (seconds > 0) {
    window.setTimeout(() => {
      void (async () => {
        if (await notificationGranted()) {
          new Notification("SightGuide reminder", { body: label, tag: "sightguide-reminder" });
        }
        platform.speak(`Reminder: ${label}`);
      })();
    }, Math.max(seconds * 1000, 1000));
    return;
  }
  if (seconds === 0 && parameters.handled) return;
  platform.speak(`I'll remind you to ${label}. You can ask me to remind you in a number of minutes.`);
}

/** Execute a device directive. All device-side actions happen here. */
export async function executeDeviceDirective(directive: DeviceDirective, platform: DirectivePlatform): Promise<void> {
  const action = directive.action;
  const value = String(directive.value ?? "");
  const params = directive.parameters ?? {};

  switch (action) {
    case "call": {
      const recipient = String(params.recipient || value || "");
      if (isPhoneNumber(recipient)) {
        platform.speak(`Calling ${recipient} now.`);
        await makeDirectCall(recipient);
        return;
      }
      const match = findContactNumber(recipient);
      if (match) {
        platform.speak(`Calling ${match.name} at ${match.number} now.`);
        await makeDirectCall(match.number);
      } else {
        platform.speak(`I don't have a saved phone number for ${recipient || "that contact"}. You can add them in Settings.`);
      }
      return;
    }

    case "message": {
      const recipient = String(params.recipient || value || "");
      const body = typeof params.body === "string" ? params.body : "";

      if (isPhoneNumber(recipient)) {
        platform.speak(`Sending message to ${recipient}.`);
        await sendDirectSms(recipient, body);
        platform.onMessageSent?.(recipient, body, recipient);
        return;
      }

      const match = findContactNumber(recipient);
      if (match) {
        platform.speak(`Sending message to ${match.name}.`);
        await sendDirectSms(match.number, body);
        platform.onMessageSent?.(match.name, body, match.number);
      } else {
        platform.speak(`I don't have a saved phone number for ${recipient || "that contact"}. You can add them in Settings.`);
      }
      return;
    }

    case "search_web": {
      const query = String(params.query || value || "SightGuide");
      const url = String(params.url || `https://www.google.com/search?q=${encodeURIComponent(query)}`);
      platform.speak(`Searching online for ${query}.`);
      try {
        window.open(url, "_blank");
      } catch {
        window.location.href = url;
      }
      platform.onSearch?.(query, url);
      return;
    }

    case "open_screen": {
      const screen = String(params.screen || value || "home");
      const screenLabel = screen === "vision" ? "Camera and Vision" : screen;
      platform.speak(`Opening ${screenLabel}.`);
      platform.onScreenChange?.(screen);
      return;
    }

    case "phone_control": {
      const subAction = String(params.sub_action || value || "unknown");
      const target = String(params.target || params.query || "");
      const text = String(params.text || "");
      const direction = String(params.direction || "down");
      const ordinal = typeof params.ordinal === "number" ? params.ordinal : undefined;
      const globalAction = String(params.global_action || "back");

      const result = await dispatchPhoneAction({
        action: subAction,
        target,
        text,
        direction,
        ordinal,
        globalAction,
      });

      if (!result.success && result.message) {
        platform.speak(result.message);
      }
      return;
    }

    case "open_external": {
      const appName = String(params.name || value || "app");
      const url = String(params.url || `https://www.google.com/search?q=${encodeURIComponent(appName)}`);
      platform.speak(`Opening ${appName} now.`);

      // Attempt direct Android package launch if on native platform
      if (isNativeAccessibilityAvailable()) {
        const res = await dispatchPhoneAction({ action: "open_app", target: appName });
        if (res.success) {
          platform.onOpenExternal?.(url, appName);
          return;
        }
      }

      try {
        window.open(url, "_blank");
      } catch {
        window.location.href = url;
      }
      platform.onOpenExternal?.(url, appName);
      return;
    }

    case "reminder":
      scheduleReminder(directive, platform);
      return;

    case "sos":
      platform.onEmergency?.(value || null, (params.location as string) || null);
      return;

    case "start_navigation":
      platform.onNavigate?.(String(value || params.destination || ""));
      return;

    case "start_scan":
      platform.onScanChange?.(true);
      return;

    case "stop_scan":
      platform.onScanChange?.(false);
      return;

    case "switch_camera":
      platform.onCameraSwitch?.();
      return;

    case "mute":
      platform.onMuteChange?.(true);
      return;

    case "unmute":
      platform.onMuteChange?.(false);
      platform.onUnmute?.();
      return;

    default:
      return;
  }
}

