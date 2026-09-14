import { isSpeechRecognitionSupported, VoiceRecognizer } from "./recognizer";
import { extractWakeCommand, joinFinalTranscripts, matchesCancelPhrase, matchesWakeWord } from "./wakeWord";
import { TextToSpeech } from "./tts";
import { getDeviceLocation } from "./geolocation";
import type {
  CommandSender,
  ConversationTurn,
  DeviceDirective,
  FrameProvider,
  VoiceAssistantCallbacks,
  VoiceCommandResponse,
  VoiceState,
} from "./voiceTypes";

const SILENCE_MS = 1700;
const MAX_COMMAND_MS = 12000;
const WAKE_ROTATION_MS = 45000;
const RESTART_COOLDOWN_MS = 900;
const MAX_CONTEXT_TURNS = 10;
const LOCATION_CACHE_MS = 10 * 60 * 1000;

type RecognizerMode = "wake" | "capture";

interface PositionResult {
  lat: number | null;
  lon: number | null;
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

export class VoiceAssistant {
  private readonly tts: TextToSpeech;
  private readonly sendCommand: CommandSender;
  private readonly getFrame: FrameProvider;
  private readonly callbacks: VoiceAssistantCallbacks;

  private state: VoiceState = "idle";
  private enabled = false;
  private disposed = false;

  private activeRecognizer: VoiceRecognizer | null = null;
  private recognizerMode: RecognizerMode | null = null;

  private timers: number[] = [];
  private generation = 0;
  private commandInFlight = false;
  private abortController: AbortController | null = null;

  private context: ConversationTurn[] = [];

  private captureBuffer = "";
  private captureFinalCount = 0;
  private lastSpeechAt = 0;

  private lastWakeAt = 0;
  private lastRestartAt = 0;

  private locationCache: { at: number; lat: number; lon: number } | null = null;

  constructor(options: {
    tts: TextToSpeech;
    sendCommand: CommandSender;
    getFrame: FrameProvider;
    callbacks: VoiceAssistantCallbacks;
  }) {
    this.tts = options.tts;
    this.sendCommand = options.sendCommand;
    this.getFrame = options.getFrame;
    this.callbacks = options.callbacks;
  }

  static isSupported(): boolean {
    return isSpeechRecognitionSupported();
  }

  getState(): VoiceState {
    return this.state;
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  getContext(): ConversationTurn[] {
    return [...this.context];
  }

  async enable(): Promise<boolean> {
    if (this.disposed) return false;
    if (!VoiceAssistant.isSupported()) {
      this.setState("error");
      this.callbacks.onError("Speech recognition is not supported in this browser.");
      return false;
    }
    this.enabled = true;
    this.setState("waiting_for_wake_word");
    this.startWakeListening();
    return true;
  }

  /** Interrupt current speech / processing and return to wake-word listening. */
  async interrupt(): Promise<void> {
    if (this.disposed) return;
    this.generation += 1;
    this.commandInFlight = false;
    this.abortController?.abort();
    this.abortController = null;
    this.tts.stop();
    this.clearTimers();
    if (this.enabled) {
      this.setState("waiting_for_wake_word");
      this.startWakeListening();
    } else {
      this.setState("idle");
    }
  }

  /** Full stop: cancel speech, processing, and stop listening for the wake word. */
  async stopAll(): Promise<void> {
    if (this.disposed) return;
    this.enabled = false;
    this.generation += 1;
    this.commandInFlight = false;
    this.abortController?.abort();
    this.abortController = null;
    this.tts.stop();
    this.clearTimers();
    this.stopActiveRecognizer();
    this.setState("idle");
  }

  dispose(): void {
    this.disposed = true;
    void this.stopAll();
    this.tts.dispose();
    this.clearTimers();
  }

  setMuted(muted: boolean): void {
    this.tts.setMuted(muted);
  }

  /** Capture one utterance without requiring the wake word (button fallback). */
  startManualListening(): void {
    if (this.disposed) return;
    if (!this.enabled) {
      void this.enable();
    }
    this.interruptProcessing();
    this.startCaptureListening();
  }

  // ---- internal state machine ----

  private setState(state: VoiceState): void {
    if (this.state === state) return;
    this.state = state;
    this.callbacks.onState(state);
  }

  private clearTimers(): void {
    for (const timer of this.timers) window.clearTimeout(timer);
    this.timers = [];
  }

  private after(ms: number, callback: () => void): void {
    const timer = window.setTimeout(() => {
      this.timers = this.timers.filter((entry) => entry !== timer);
      callback();
    }, ms);
    this.timers.push(timer);
  }

  private stopActiveRecognizer(): void {
    const recognizer = this.activeRecognizer;
    this.activeRecognizer = null;
    this.recognizerMode = null;
    if (recognizer) recognizer.stop();
  }

  private startWakeListening(): void {
    if (!this.enabled || this.disposed) return;
    this.generation += 1;
    this.commandInFlight = false;
    this.clearTimers();
    this.stopActiveRecognizer();

    const recognizer = new VoiceRecognizer();
    this.activeRecognizer = recognizer;
    this.recognizerMode = "wake";
    this.setState("waiting_for_wake_word");

    const started = recognizer.start({
      continuous: true,
      interimResults: true,
      onstart: () => {
        if (this.activeRecognizer !== recognizer) return;
        this.setState("waiting_for_wake_word");
      },
      onerror: (error) => this.handleWakeError(error),
      onend: () => this.handleWakeEnd(),
      onresult: (records) => this.handleWakeResults(records),
    });

    if (!started) {
      this.setState("error");
      this.callbacks.onError("The microphone could not be started.");
      return;
    }

    this.after(WAKE_ROTATION_MS, () => {
      if (this.disposed || !this.enabled) return;
      if (this.recognizerMode === "wake") {
        this.startWakeListening();
      }
    });
  }

  private handleWakeResults(records: Array<{ transcript: string; isFinal: boolean }>): void {
    if (this.recognizerMode !== "wake" || this.disposed) return;
    const finalText = joinFinalTranscripts(records);
    if (!finalText) return;

    if (matchesWakeWord(finalText)) {
      const embeddedCommand = extractWakeCommand(finalText);
      this.onWakeDetected(embeddedCommand);
    }
  }

  private onWakeDetected(embeddedCommand: string | null): void {
    const now = Date.now();
    if (now - this.lastWakeAt < 1500) return;
    this.lastWakeAt = now;

    this.interruptProcessing();
    this.callbacks.onMessage("How can I help?");
    if (embeddedCommand && embeddedCommand.length > 1) {
      this.captureBuffer = embeddedCommand;
      void this.handleUtterance(embeddedCommand);
      return;
    }
    this.startCaptureListening();
  }

  private startCaptureListening(): void {
    if (this.disposed) return;
    this.generation += 1;
    const gen = this.generation;
    this.captureBuffer = "";
    this.captureFinalCount = 0;
    this.lastSpeechAt = Date.now();
    this.clearTimers();
    this.stopActiveRecognizer();

    const recognizer = new VoiceRecognizer();
    this.activeRecognizer = recognizer;
    this.recognizerMode = "capture";
    this.setState("listening");

    const started = recognizer.start({
      continuous: false,
      interimResults: true,
      onstart: () => {
        if (this.activeRecognizer === recognizer) this.setState("listening");
      },
      onerror: (error) => {
        if (error === "not-allowed" || error === "service-not-allowed") {
          this.handleMicDenied();
        }
      },
      onresult: (records) => this.handleCaptureResults(records, gen),
      onend: () => this.handleCaptureEnd(gen),
    });

    if (!started) {
      this.startWakeListening();
      return;
    }

    this.after(MAX_COMMAND_MS, () => {
      if (this.generation === gen && this.state === "listening") this.finalizeCapture();
    });

    const silenceClock = (): void => {
      if (this.disposed || this.generation !== gen) return;
      if (this.state !== "listening" || this.recognizerMode !== "capture") return;
      if (this.captureBuffer.trim() && Date.now() - this.lastSpeechAt >= SILENCE_MS) {
        this.finalizeCapture();
        return;
      }
      this.after(SILENCE_MS, silenceClock);
    };
    this.after(SILENCE_MS, silenceClock);
  }

  private handleCaptureResults(records: Array<{ transcript: string; isFinal: boolean }>, gen: number): void {
    if (this.disposed || gen !== this.generation || this.recognizerMode !== "capture") return;
    if (records.some((record) => record.transcript.trim())) {
      this.lastSpeechAt = Date.now();
    }
    const finals = records.filter((record) => record.isFinal);
    if (finals.length > this.captureFinalCount) {
      const fresh = finals.slice(this.captureFinalCount).map((record) => record.transcript.trim()).join(" ").trim();
      if (fresh) {
        this.captureBuffer = `${this.captureBuffer} ${fresh}`.trim();
        this.callbacks.onTranscript?.(this.captureBuffer);
        this.lastSpeechAt = Date.now();
      }
      this.captureFinalCount = finals.length;
    }
  }

  private handleCaptureEnd(gen: number): void {
    if (this.disposed || gen !== this.generation || this.recognizerMode !== "capture") return;
    if (this.captureBuffer.trim()) {
      this.finalizeCapture();
    } else {
      this.startWakeListening();
    }
  }

  private finalizeCapture(): void {
    if (this.disposed) return;
    this.clearTimers();
    const text = this.captureBuffer.trim();
    this.captureBuffer = "";
    if (!text) {
      this.startWakeListening();
      return;
    }
    void this.handleUtterance(text);
  }

  private async handleUtterance(text: string): Promise<void> {
    if (matchesCancelPhrase(text)) {
      this.interruptProcessing();
      this.tts.speak("Stopped.");
      this.callbacks.onMessage("Stopped.");
      return;
    }
    this.setState("processing");
    this.pushContext("user", text);
    await this.dispatchCommand(text);
  }

  private pushContext(role: "user" | "assistant", text: string): void {
    const trimmed = text.trim();
    if (!trimmed) return;
    this.context.push({ role, text: trimmed });
    if (this.context.length > MAX_CONTEXT_TURNS) {
      this.context = this.context.slice(this.context.length - MAX_CONTEXT_TURNS);
    }
  }

  private async getPosition(): Promise<PositionResult> {
    if (this.locationCache && Date.now() - this.locationCache.at < LOCATION_CACHE_MS) {
      return { lat: this.locationCache.lat, lon: this.locationCache.lon };
    }
    const location = await getDeviceLocation(6000);
    if (!location) return { lat: null, lon: null };
    this.locationCache = { at: Date.now(), lat: location.lat, lon: location.lon };
    return { lat: location.lat, lon: location.lon };
  }

  private async dispatchCommand(text: string): Promise<void> {
    if (this.commandInFlight) return;
    this.commandInFlight = true;
    const gen = this.generation;
    const controller = new AbortController();
    this.abortController = controller;

    try {
      const position = await this.getPosition();
      if (gen !== this.generation) {
        this.commandInFlight = false;
        return;
      }

      let response: VoiceCommandResponse;
      try {
        response = await this.sendCommand(text, {
          context: this.getContext(),
          lat: position.lat,
          lon: position.lon,
          imageBase64: null,
          signal: controller.signal,
        });
      } catch (error) {
        if (isAbortError(error) || gen !== this.generation) {
          this.commandInFlight = false;
          return;
        }
        this.callbacks.onError("Connection to the assistant failed. Retrying…");
        response = await this.sendCommand(text, {
          context: this.getContext(),
          lat: position.lat,
          lon: position.lon,
          imageBase64: null,
          signal: undefined,
        });
      }

      if (gen !== this.generation) {
        this.commandInFlight = false;
        return;
      }

      if (response.needs_frame) {
        this.setState("executing");
        this.callbacks.onMessage("Looking now…");
        const frame = await this.getFrame();
        if (gen !== this.generation) {
          this.commandInFlight = false;
          return;
        }
        if (!frame) {
          this.callbacks.onError("The camera is not available. Enable it and try again.");
          await this.returnToWakeAndSpeak("I need the camera to see what is in front of you.");
          this.commandInFlight = false;
          return;
        }
        response = await this.sendCommand(text, {
          context: this.getContext(),
          lat: position.lat,
          lon: position.lon,
          imageBase64: frame,
          signal: controller.signal,
        });
        if (gen !== this.generation) {
          this.commandInFlight = false;
          return;
        }
      }

      await this.handleResponse(response, gen);
    } catch (error) {
      if (isAbortError(error) || gen !== this.generation) return;
      this.callbacks.onError("I had trouble reaching the assistant. Please try again.");
      await this.returnToWakeAndSpeak("I had trouble completing that. Please try again.");
    } finally {
      this.commandInFlight = false;
      this.abortController = null;
    }
  }

  private async handleResponse(response: VoiceCommandResponse, gen: number): Promise<void> {
    if (this.disposed || gen !== this.generation) return;

    if (response.text.trim()) this.pushContext("assistant", response.text);

    const directives = this.normalizeDirectives(response);
    this.setState("executing");
    for (const directive of directives) {
      this.callbacks.onDirective(directive, response);
    }

    this.startWakeListening();
    if (this.state !== "speaking") this.setState("waiting_for_wake_word");

    if (response.text.trim()) {
      this.tts.speak(
        response.text,
        () => {
          if (gen === this.generation) this.setState("speaking");
        },
        () => {
          if (gen === this.generation) this.setState("waiting_for_wake_word");
        },
      );
    }
  }

  private normalizeDirectives(response: VoiceCommandResponse): DeviceDirective[] {
    const directives = response.directives ? [...response.directives] : [];
    const hasAction = (action: string): boolean => directives.some((directive) => directive.action === action);
    if (response.action === "start_navigation" && !hasAction("start_navigation")) {
      directives.push({
        action: "start_navigation",
        value: response.navigation_destination || "",
        parameters: { destination: response.navigation_destination || "" },
      });
    }
    for (const action of ["start_scan", "stop_scan", "switch_camera", "mute", "unmute", "sos", "search_web", "open_screen", "open_external", "call", "message", "phone_control"]) {
      if (response.action === action && !hasAction(action)) {
        directives.push({ action });
      }
    }
    return directives;
  }

  private async returnToWakeAndSpeak(text: string): Promise<void> {
    if (this.disposed) return;
    this.startWakeListening();
    this.tts.speak(text);
    this.setState("speaking");
    this.after(3500, () => {
      if (this.state === "speaking") this.setState("waiting_for_wake_word");
    });
  }

  private interruptProcessing(): void {
    this.generation += 1;
    this.commandInFlight = false;
    this.abortController?.abort();
    this.abortController = null;
    this.tts.stop();
    this.clearTimers();
  }

  private handleWakeError(error: string | undefined): void {
    if (this.disposed || !this.enabled) return;
    if (error === "not-allowed" || error === "service-not-allowed") {
      this.handleMicDenied();
      return;
    }
    if (error === "no-speech") return;
    if (error === "aborted") return;
    this.scheduleWakeRestart(error);
  }

  private handleMicDenied(): void {
    if (this.disposed) return;
    this.enabled = false;
    this.stopActiveRecognizer();
    this.clearTimers();
    this.setState("error");
    this.callbacks.onError("Microphone permission was not granted. Tap the voice button to try again.");
  }

  private handleWakeEnd(): void {
    if (this.disposed) return;
    if (!this.enabled) return;
    if (this.recognizerMode === "capture") return;
    this.scheduleWakeRestart("listener-stopped");
  }

  private scheduleWakeRestart(reason: string | undefined): void {
    if (!this.enabled || this.disposed) return;
    const now = Date.now();
    if (now - this.lastRestartAt < RESTART_COOLDOWN_MS) return;
    this.lastRestartAt = now;
    this.after(this.disposed ? 0 : 250, () => {
      if (this.enabled && !this.disposed && this.recognizerMode === "wake") {
        if (reason !== "listener-stopped") this.callbacks.onError(`Microphone recovered from: ${reason}`);
        this.startWakeListening();
      }
    });
  }
}