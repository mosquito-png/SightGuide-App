import { Capacitor } from "@capacitor/core";
import { TextToSpeech as NativeTextToSpeech, QueueStrategy } from "@capacitor-community/text-to-speech";

const MAX_UTTERANCE_LENGTH = 240;

function preferredVoice(voices: SpeechSynthesisVoice[]): SpeechSynthesisVoice | null {
  const english = voices.filter((voice) => /^en(-|_|$)/.test(voice.lang || ""));
  if (english.length === 0) return voices[0] ?? null;
  const priority = ["samantha", "google us english", "karen", "moira", "daniel", "alex", "aria", "jenny", "zira", "nathan"];
  for (const name of priority) {
    const match = english.find((voice) => voice.name.toLowerCase().includes(name));
    if (match) return match;
  }
  return english[0];
}

function stripMarkers(text: string): string {
  return (text || "")
    .replace(/\*\*/g, "")
    .replace(/\*/g, "")
    .replace(/`/g, "")
    .replace(/^#+\s*/gm, "")
    .replace(/\s+/g, " ")
    .trim();
}

export class TextToSpeech {
  private supported: boolean;
  private voice: SpeechSynthesisVoice | null = null;
  private muted = false;
  private current: SpeechSynthesisUtterance | null = null;
  private disposed = false;
  private nativeSpeaking = false;

  constructor() {
    const hasWebSpeech =
      typeof window !== "undefined" && "speechSynthesis" in window && "SpeechSynthesisUtterance" in window;
    this.supported =
      hasWebSpeech || Capacitor.isNativePlatform();
    if (hasWebSpeech) {
      this.refreshVoice();
      const synthesis = window.speechSynthesis;
      synthesis.onvoiceschanged = () => this.refreshVoice();
    }
  }

  isSupported(): boolean {
    return this.supported;
  }

  isMuted(): boolean {
    return this.muted;
  }

  setMuted(muted: boolean): void {
    this.muted = muted;
  }

  setRate(rate: number): void {
    if (this.current) this.current.rate = rate;
  }

  private refreshVoice(): void {
    if (!this.supported || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    const voices = window.speechSynthesis.getVoices();
    if (voices.length === 0) return;
    this.voice = preferredVoice(voices);
  }

  isSpeaking(): boolean {
    if (Capacitor.isNativePlatform() && !("speechSynthesis" in window)) return this.nativeSpeaking;
    return this.supported && window.speechSynthesis.speaking;
  }

  stop(): void {
    this.current = null;
    if (Capacitor.isNativePlatform() && !("speechSynthesis" in window)) {
      this.nativeSpeaking = false;
      void NativeTextToSpeech.stop().catch(() => undefined);
      return;
    }
    if (!this.supported) return;
    try {
      window.speechSynthesis.cancel();
    } catch {
      /* no-op */
    }
  }

  resumeListeningAfterSpeak(): void {
    if (!this.supported || typeof window === "undefined" || !("speechSynthesis" in window)) return;
    try {
      if (window.speechSynthesis.paused) window.speechSynthesis.resume();
    } catch {
      /* no-op */
    }
  }

  /** Speak concise text. Returns false when TTS is unavailable or muted-queued. */
  speak(text: string, onStart?: () => void, onEnd?: () => void): boolean {
    if (!this.supported) return false;
    const clean = stripMarkers(text);
    if (!clean) {
      onEnd?.();
      return false;
    }

    this.stop();

    if (Capacitor.isNativePlatform() && !("speechSynthesis" in window)) {
      this.nativeSpeaking = true;
      onStart?.();
      void NativeTextToSpeech.speak({
        text: clean,
        lang: "en-US",
        rate: 1,
        pitch: 1,
        volume: 1,
        queueStrategy: QueueStrategy.Flush,
      })
        .catch(() => undefined)
        .finally(() => {
          this.nativeSpeaking = false;
          onEnd?.();
        });
      return true;
    }

    const chunks: string[] = [];
    if (clean.length <= MAX_UTTERANCE_LENGTH) {
      chunks.push(clean);
    } else {
      const sentences = clean.split(/(?<=[.!?])\s+/).filter(Boolean);
      let buffer = "";
      for (const sentence of sentences) {
        if (buffer.length + sentence.length > MAX_UTTERANCE_LENGTH && buffer) {
          chunks.push(buffer);
          buffer = sentence;
        } else {
          buffer = buffer ? `${buffer} ${sentence}` : sentence;
        }
      }
      if (buffer) chunks.push(buffer);
    }

    if (chunks.length === 0) {
      onEnd?.();
      return false;
    }

    let startedTriggered = false;
    for (let index = 0; index < chunks.length; index++) {
      const chunk = chunks[index];
      const isFirst = index === 0;
      const isLast = index === chunks.length - 1;

      if (this.disposed || this.muted) {
        onEnd?.();
        return false;
      }

      const utterance = new SpeechSynthesisUtterance(chunk);
      if (this.voice) utterance.voice = this.voice;
      utterance.lang = this.voice?.lang || "en-US";
      utterance.rate = 1.0;
      utterance.pitch = 1.0;

      utterance.onstart = () => {
        if (isFirst && !startedTriggered) {
          startedTriggered = true;
          onStart?.();
        }
      };

      utterance.onend = () => {
        if (isLast) {
          this.current = null;
          onEnd?.();
        }
      };

      utterance.onerror = () => {
        if (isLast) {
          this.current = null;
          onEnd?.();
        }
      };

      if (isLast) {
        this.current = utterance;
      }

      try {
        window.speechSynthesis.speak(utterance);
      } catch {
        if (isLast) {
          this.current = null;
          onEnd?.();
        }
      }
    }

    try {
      if (window.speechSynthesis.paused) {
        window.speechSynthesis.resume();
      }
    } catch {
      /* no-op */
    }

    return true;
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
  }
}
