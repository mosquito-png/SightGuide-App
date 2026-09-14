export type VoiceState =
  | "idle"
  | "waiting_for_wake_word"
  | "listening"
  | "processing"
  | "executing"
  | "speaking"
  | "error";

export type VoiceStateLabel = string;

export const VOICE_STATE_LABELS: Record<VoiceState, string> = {
  idle: "IDLE",
  waiting_for_wake_word: "SAY HEY SIGHTGUIDE",
  listening: "LISTENING",
  processing: "PROCESSING",
  executing: "EXECUTING",
  speaking: "SPEAKING",
  error: "VOICE UNAVAILABLE",
};

export interface DeviceDirective {
  action: string;
  value?: string | null;
  parameters?: Record<string, unknown>;
}

export interface ConversationTurn {
  role: "user" | "assistant";
  text: string;
}

export interface VoiceCommandResponse {
  intent: string;
  text: string;
  priority: "normal" | "warning" | "urgent";
  action: string;
  directives: DeviceDirective[];
  needs_frame: boolean;
  navigation_destination?: string | null;
  detected_items?: string[];
  extracted_text?: string | null;
  timestamp?: string | null;
}

export interface VoiceAssistantCallbacks {
  onState: (state: VoiceState) => void;
  onMessage: (message: string, priority?: string) => void;
  onTranscript?: (transcript: string) => void;
  onError: (message: string) => void;
  onDirective: (directive: DeviceDirective, response: VoiceCommandResponse) => void;
}

export interface CommandOptions {
  context: ConversationTurn[];
  lat: number | null;
  lon: number | null;
  imageBase64: string | null;
  signal?: AbortSignal;
}

export type CommandSender = (text: string, options: CommandOptions) => Promise<VoiceCommandResponse>;
export type FrameProvider = () => Promise<string | null>;