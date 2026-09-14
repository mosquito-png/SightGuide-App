import { Capacitor } from "@capacitor/core";
import { SpeechRecognition } from "@capacitor-community/speech-recognition";
import type { PluginListenerHandle } from "@capacitor/core";

export type RecognizerResultItem = { transcript: string; isFinal: boolean };

export interface BrowserRecognitionEvent {
  resultIndex: number;
  results: ArrayLike<{
    isFinal: boolean;
    length: number;
    [index: number]: { transcript: string };
  }>;
}

export interface BrowserRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: { error?: string }) => void) | null;
  onresult: ((event: BrowserRecognitionEvent) => void) | null;
}

type RecognitionCtor = new () => BrowserRecognitionLike;
type SpeechRecognitionWindow = Window & {
  SpeechRecognition?: RecognitionCtor;
  webkitSpeechRecognition?: RecognitionCtor;
  webkitAudioContext?: typeof AudioContext;
};

function recognizerConstructor(): RecognitionCtor | null {
  const browser = window as SpeechRecognitionWindow;
  const ctor = browser.SpeechRecognition ?? browser.webkitSpeechRecognition;
  return ctor ?? null;
}

export function isSpeechRecognitionSupported(): boolean {
  return recognizerConstructor() !== null;
}

export function isNativeSpeechRecognitionAvailable(): boolean {
  return Capacitor.isNativePlatform();
}

export async function requestNativeSpeechPermissions(): Promise<boolean> {
  if (!isNativeSpeechRecognitionAvailable()) return false;
  try {
    const availability = await SpeechRecognition.available();
    if (!availability.available) return false;
    const permissions = await SpeechRecognition.requestPermissions();
    return permissions.speechRecognition === "granted";
  } catch {
    return false;
  }
}

/** Native fallback used only when Android WebView lacks SpeechRecognition. */
export class NativeSpeechRecognizer {
  private partialListener: PluginListenerHandle | null = null;
  private stateListener: PluginListenerHandle | null = null;
  private latestTranscript = "";
  private expectedStop = false;
  private started = false;

  async start(options: {
    onstart?: () => void;
    onend?: () => void;
    onerror?: (error: string | undefined) => void;
    onresult?: (records: RecognizerResultItem[]) => void;
  }): Promise<boolean> {
    if (!isNativeSpeechRecognitionAvailable()) return false;
    this.expectedStop = false;
    this.latestTranscript = "";
    await this.removeListeners();

    try {
      const availability = await SpeechRecognition.available();
      if (!availability.available) return false;
      const permissions = await SpeechRecognition.requestPermissions();
      if (permissions.speechRecognition !== "granted") {
        options.onerror?.("not-allowed");
        return false;
      }

      this.partialListener = await SpeechRecognition.addListener("partialResults", (data) => {
        const transcript = data.matches?.[0]?.trim() ?? "";
        if (!transcript) return;
        this.latestTranscript = transcript;
      });
      this.stateListener = await SpeechRecognition.addListener("listeningState", ({ status }) => {
        if (status === "started") {
          this.started = true;
          options.onstart?.();
          return;
        }
        this.started = false;
        if (!this.expectedStop && this.latestTranscript) {
          options.onresult?.([{ transcript: this.latestTranscript, isFinal: true }]);
        }
        options.onend?.();
      });

      await SpeechRecognition.start({
        language: "en-US",
        maxResults: 1,
        partialResults: true,
        popup: false,
      });
      if (!this.started) {
        this.started = true;
        options.onstart?.();
      }
      return true;
    } catch (error) {
      await this.removeListeners();
      options.onerror?.(error instanceof Error ? error.message : "native-speech-error");
      return false;
    }
  }

  async stop(): Promise<void> {
    this.expectedStop = true;
    try {
      if (this.started) await SpeechRecognition.stop();
    } catch {
      // The native recognizer may already have ended.
    }
    await this.removeListeners();
    this.started = false;
  }

  private async removeListeners(): Promise<void> {
    await this.partialListener?.remove();
    await this.stateListener?.remove();
    this.partialListener = null;
    this.stateListener = null;
  }
}

function collectRecords(event: BrowserRecognitionEvent): RecognizerResultItem[] {
  const records: RecognizerResultItem[] = [];
  const results = event.results;
  if (!results || typeof results.length !== "number") return records;
  for (let i = 0; i < results.length; i += 1) {
    const result = results[i];
    if (!result) continue;
    const item = result[0];
    if (!item) continue;
    records.push({ transcript: item.transcript, isFinal: result.isFinal });
  }
  return records;
}

export class VoiceRecognizer {
  private instance: BrowserRecognitionLike | null = null;
  private listeningFlag = false;
  private expectedEnd = false;

  get listening(): boolean {
    return this.listeningFlag;
  }

  start(options: {
    continuous: boolean;
    interimResults: boolean;
    onstart?: () => void;
    onend?: () => void;
    onerror?: (error: string | undefined) => void;
    onresult?: (records: RecognizerResultItem[]) => void;
  }): boolean {
    const ctor = recognizerConstructor();
    if (!ctor) return false;
    this.stop();
    this.expectedEnd = false;
    const recognition = new ctor();
    recognition.lang = "en-US";
    recognition.continuous = options.continuous;
    recognition.interimResults = options.interimResults;
    recognition.maxAlternatives = 1;

    recognition.onstart = () => {
      this.listeningFlag = true;
      options.onstart?.();
    };
    recognition.onend = () => {
      this.listeningFlag = false;
      if (this.expectedEnd) {
        this.expectedEnd = false;
        return;
      }
      options.onend?.();
    };
    recognition.onerror = (event) => {
      options.onerror?.(event.error);
    };
    recognition.onresult = (event) => {
      options.onresult?.(collectRecords(event));
    };

    this.instance = recognition;
    try {
      recognition.start();
    } catch {
      this.instance = null;
      this.listeningFlag = false;
      return false;
    }
    return true;
  }

  stop(): void {
    this.expectedEnd = true;
    const instance = this.instance;
    this.instance = null;
    if (instance) {
      try {
        instance.stop();
      } catch {
        /* already stopped */
      }
    }
    this.listeningFlag = false;
  }

  /** Hard abort — used on teardown so no restart logic runs. */
  abort(): void {
    this.expectedEnd = true;
    const instance = this.instance;
    this.instance = null;
    if (instance) {
      try {
        instance.abort();
      } catch {
        /* already aborted */
      }
    }
    this.listeningFlag = false;
  }
}
