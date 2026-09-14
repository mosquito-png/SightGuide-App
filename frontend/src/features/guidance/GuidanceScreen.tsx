import { FormEvent, RefObject, useEffect, useRef, useState, useCallback } from "react";
import { App } from "@capacitor/app";
import { Capacitor } from "@capacitor/core";
import {
  describeScene,
  detectObstacles,
  readTextFromImage,
  openVoiceSocket,
  sendVoiceCommand,
  apiBaseUrl,
  getCustomApiBaseUrl,
  setCustomApiBaseUrl,
  type DetectedObstacle,
  type GuidanceResponse,
  type OCRReadTextResponse,
  type VisionDetectionResponse,
} from "../../core/api";
import { NavigationScreen, type LocationStatus, type NavigationHint } from "./NavigationScreen";
import { EmergencyScreen } from "./EmergencyScreen";
import {
  isNativeSpeechRecognitionAvailable,
  NativeSpeechRecognizer,
} from "../../voice/recognizer";
import { TextToSpeech } from "../../voice/tts";
import { captureOptimizedFrame, hasFrameSignificantlyChanged } from "../../voice/vision";
import {
  executeDeviceDirective,
  loadEmergencyContact,
  saveEmergencyContact,
  getDefaultEmergencyContact,
  loadContactsList,
  addContact,
  removeContact,
  type EmergencyContact,
  type SavedContact,
} from "../../voice/deviceActions";
import { requestAllAppStartupPermissions } from "../../voice/telephony";
import { getDeviceLocation } from "../../voice/geolocation";
import type { DeviceDirective } from "../../voice/voiceTypes";
import {
  checkAccessibilityServiceStatus,
  openAndroidAccessibilitySettings,
  setAccessibilityOverlay,
  setAccessibilitySafetyConfirmation,
  isNativeAccessibilityAvailable,
} from "../../voice/phoneAccessibility";

type AppMode = "idle" | "wake_word" | "listening" | "processing" | "response" | "speaking";
type ServiceStatus = "connecting" | "connected" | "offline";
type Screen = "home" | "vision" | "navigation" | "emergency" | "history" | "settings";
type VoicePayload = GuidanceResponse & {
  type?: string;
  state?: string;
  action?: string;
  navigation_destination?: string;
  answer?: string;
  obstacles?: DetectedObstacle[];
  text?: string;
  extracted_text?: string;
  reading_type?: string;
  directives?: DeviceDirective[];
  needs_frame?: boolean;
};
type MicState = "inactive" | "requesting" | "active" | "unsupported" | "denied";
type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  continuous: boolean;
  start: () => void;
  stop: () => void;
  onstart: (() => void) | null;
  onend: (() => void) | null;
  onerror: ((event: unknown) => void) | null;
  onresult: ((event: { results: Array<Array<{ transcript: string }>> }) => void) | null;
};
type SpeechRecognitionCtor = new () => SpeechRecognitionLike;
type VoiceWindow = Window & typeof globalThis & {
  SpeechRecognition?: SpeechRecognitionCtor;
  webkitSpeechRecognition?: SpeechRecognitionCtor;
};

const modeLabels: Record<AppMode, string> = {
  idle: "IDLE",
  wake_word: "WAKE WORD DETECTED",
  listening: "LISTENING",
  processing: "PROCESSING",
  response: "COMMAND RECOGNIZED",
  speaking: "SPEAKING",
};

function useVoiceSocket(onResponse: (payload: VoicePayload) => void, onState: (state: string) => void) {
  const socketRef = useRef<WebSocket | null>(null);
  const responseRef = useRef(onResponse);
  const stateRef = useRef(onState);
  const reconnectTimerRef = useRef<number | null>(null);
  responseRef.current = onResponse;
  stateRef.current = onState;

  useEffect(() => {
    let disposed = false;
    let retryDelay = 1000;

    const connect = () => {
      if (disposed) return;
      let socket: WebSocket;
      try {
        socket = openVoiceSocket();
      } catch (error) {
        console.warn("Voice WebSocket is unavailable:", error);
        stateRef.current("offline");
        return;
      }
      socketRef.current = socket;

      socket.onopen = () => {
        retryDelay = 1000;
        stateRef.current("connected");
      };

      socket.onclose = () => {
        if (disposed) return;
        stateRef.current("offline");
        reconnectTimerRef.current = window.setTimeout(connect, retryDelay);
        retryDelay = Math.min(retryDelay * 2, 15000);
      };

      socket.onerror = () => {
        if (socket.readyState !== WebSocket.OPEN) stateRef.current("offline");
      };

      socket.onmessage = (event) => {
        try {
          const payload = JSON.parse(String(event.data)) as VoicePayload;
          if (
            payload.type === "response" ||
            payload.type === "vision_response" ||
            payload.type === "assistant_response" ||
            payload.type === "ocr_response"
          ) {
            if (payload.type === "assistant_response" && !payload.message) payload.message = payload.answer ?? "";
            if (payload.type === "ocr_response" && !payload.message && payload.text) {
              payload.message = `The text reads: ${payload.text}`;
            }
            responseRef.current(payload);
          }
          if (payload.type === "state" && payload.state) stateRef.current(payload.state);
        } catch {
          stateRef.current("offline");
        }
      };
    };

    connect();

    return () => {
      disposed = true;
      if (reconnectTimerRef.current !== null) window.clearTimeout(reconnectTimerRef.current);
      socketRef.current?.close();
      socketRef.current = null;
    };
  }, []);
  return socketRef;
}

async function copyTextToClipboard(text: string): Promise<boolean> {
  if (!text) return false;
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall back below.
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

export function GuidanceScreen() {
  const [screen, setScreen] = useState<Screen>("home");
  const [mode, setMode] = useState<AppMode>("idle");
  const [serviceStatus, setServiceStatus] = useState<ServiceStatus>("connecting");
  const [message, setMessage] = useState("Ready when you are.");
  const [scene, setScene] = useState("");
  const [priority, setPriority] = useState("normal");
  const [error, setError] = useState("");
  const [commandOpen, setCommandOpen] = useState(false);
  const [cameraState, setCameraState] = useState<"inactive" | "requesting" | "active" | "denied">("inactive");
  const [micState, setMicState] = useState<MicState>("inactive");
  const [navigationRequest, setNavigationRequest] = useState<NavigationHint | null>(null);
  const [gpsStatus, setGpsStatus] = useState<LocationStatus>("locating");
  const [extractedText, setExtractedText] = useState<string | null>(null);
  const [readingType, setReadingType] = useState<string | null>(null);
  const [copiedText, setCopiedText] = useState<boolean>(false);
  const [obstacles, setObstacles] = useState<DetectedObstacle[]>([]);
  const [isAnalyzing, setIsAnalyzing] = useState<boolean>(false);
  const [isOnline, setIsOnline] = useState<boolean>(typeof navigator !== "undefined" ? navigator.onLine : true);

  // Proactively request ALL device permissions (Camera, Microphone, GPS Location, Calling, SMS) on app launch
  useEffect(() => {
    void requestAllAppStartupPermissions();
    void getDeviceLocation(6000);
  }, []);

  const isActivatingCameraRef = useRef(false);
  const isStartingVoiceRef = useRef(false);
  const isAnalyzingRef = useRef(false);
  isAnalyzingRef.current = isAnalyzing;

  const videoRef = useRef<HTMLVideoElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const micStreamRef = useRef<MediaStream | null>(null);
  const recognitionRef = useRef<SpeechRecognitionLike | null>(null);
  const nativeRecognitionRef = useRef<NativeSpeechRecognizer | null>(null);
  const nativeTtsRef = useRef<TextToSpeech | null>(null);
  const speechRef = useRef<SpeechSynthesisUtterance | null>(null);
  const userStoppedRef = useRef<boolean>(false);
  const analysisAbortRef = useRef<AbortController | null>(null);

  const socketRef = useVoiceSocket(
    (payload) => {
      setMode("speaking");
      setMessage(payload.message || "Guidance received.");
      setPriority(payload.priority || "normal");
      setError("");
      if (payload.obstacles) setObstacles(payload.obstacles);
      if (payload.text) setExtractedText(payload.text);
      if (payload.extracted_text) setExtractedText(payload.extracted_text);
      if (payload.reading_type) setReadingType(payload.reading_type);
      speak(payload.message || payload.text || "");

      if (payload.directives && payload.directives.length > 0) {
        for (const directive of payload.directives) {
          void executeDeviceDirective(directive, {
            speak,
            onEmergency: () => selectScreen("emergency"),
            onNavigate: (dest) => {
              setNavigationRequest({ key: Date.now(), query: dest });
              selectScreen("navigation");
            },
            onScreenChange: (nextScreen) => {
              const validScreens: Screen[] = ["home", "vision", "navigation", "emergency", "history", "settings"];
              if (validScreens.includes(nextScreen as Screen)) selectScreen(nextScreen as Screen);
            },
            onSearch: (query) => setMessage(`Searching online for: ${query}`),
            onOpenExternal: (_url, name) => setMessage(`Opened ${name}.`),
            onMessageSent: (recipient) => setMessage(`Opened messaging for ${recipient}.`),
            onCameraSwitch: () => void activateCamera(cameraFacing === "environment" ? "user" : "environment"),
            onScanChange: (scanning) => {
              if (scanning && cameraState === "active") void performObstacleScan();
            },
          });
        }
      }

      if (payload.action === "start_navigation" && payload.navigation_destination) {
        setNavigationRequest({ key: Date.now(), query: payload.navigation_destination });
        setScreen("navigation");
      }
      if (payload.action === "sos" || payload.type === "sos") {
        setScreen("emergency");
      }
    },
    (state) => {
      setServiceStatus(state !== "offline" ? "connected" : "offline");
      if (state === "listening") setMode("listening");
    },
  );

  useEffect(() => {
    let disposed = false;
    let appStateListener: { remove: () => Promise<void> } | null = null;
    void App.addListener("appStateChange", ({ isActive }) => {
      if (isActive || disposed) return;
      userStoppedRef.current = true;
      recognitionRef.current?.stop();
      void nativeRecognitionRef.current?.stop();
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
      streamRef.current?.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
      if (videoRef.current) videoRef.current.srcObject = null;
      nativeTtsRef.current?.stop();
      if ("speechSynthesis" in window) window.speechSynthesis.cancel();
      setCameraState("inactive");
      setMicState("inactive");
      setMode("idle");
    }).then((handle) => {
      if (disposed) void handle.remove();
      else appStateListener = handle;
    });
    return () => {
      disposed = true;
      void appStateListener?.remove();
      streamRef.current?.getTracks().forEach((track) => track.stop());
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      recognitionRef.current?.stop();
      void nativeRecognitionRef.current?.stop();
      nativeTtsRef.current?.dispose();
    };
  }, []);

  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      setError("");
    };
    const handleOffline = () => {
      setIsOnline(false);
      setError("Device is offline. Some AI services may be limited.");
    };
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  useEffect(() => {
    const video = videoRef.current;
    const stream = streamRef.current;
    if (cameraState !== "active" || !video || !stream) return;
    video.srcObject = stream;
    video.muted = true;
    video.playsInline = true;
    void video.play().catch(() => {
      setError("Camera preview could not start. Tap Enable Camera to try again.");
    });
  }, [cameraState]);

  function speak(text: string) {
    if (!text) return;
    const isNative = Capacitor.isNativePlatform();
    if (isNative || !("speechSynthesis" in window)) {
      const tts = nativeTtsRef.current ?? new TextToSpeech();
      nativeTtsRef.current = tts;
      tts.speak(
        text,
        () => setMode("speaking"),
        () => {
          setMode("idle");
        },
      );
      return;
    }
    window.speechSynthesis.cancel();
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.lang = "en-US";
    utterance.onstart = () => setMode("speaking");
    utterance.onend = () => {
      setMode("idle");
    };
    utterance.onerror = () => {
      setMode("idle");
    };
    speechRef.current = utterance;
    window.speechSynthesis.speak(utterance);
  }

  // Optimized mode-aware frame capture from video stream using reusable canvas
  const captureFrameBase64 = useCallback((mode: "perception" | "ocr" = "perception"): string | null => {
    return captureOptimizedFrame(videoRef.current, mode);
  }, []);

  // Perform Vision Obstacle Scan (throttled, deduplicated, and cancelable)
  async function performObstacleScan(force = true) {
    if (isAnalyzingRef.current) return;
    if (!force && !hasFrameSignificantlyChanged(videoRef.current)) {
      return;
    }
    const frame = captureFrameBase64("perception");
    if (!frame) {
      setError("Camera frame not ready. Please activate the camera.");
      return;
    }
    analysisAbortRef.current?.abort();
    const controller = new AbortController();
    analysisAbortRef.current = controller;

    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setMode("processing");
    setError("");
    try {
      const result: VisionDetectionResponse = await detectObstacles(frame, "navigation", undefined, controller.signal);
      if (controller.signal.aborted) return;
      setMessage(result.summary);
      setPriority(result.priority);
      setObstacles(result.obstacles || []);
      if (result.extracted_text) setExtractedText(result.extracted_text);
      speak(result.summary);
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg = err instanceof Error ? err.message : "Obstacle detection failed.";
      setError(msg);
      setMode("idle");
      speak(msg);
    } finally {
      if (analysisAbortRef.current === controller) {
        isAnalyzingRef.current = false;
        setIsAnalyzing(false);
      }
    }
  }

  // Perform OCR Text Reading Scan (throttled, deduplicated, and cancelable)
  async function performOCRScan(promptOverride?: string | unknown) {
    if (isAnalyzingRef.current) return;
    const cleanPrompt = typeof promptOverride === "string" ? promptOverride : undefined;
    const frame = captureFrameBase64("ocr");
    if (!frame) {
      setError("Camera frame not ready. Please activate the camera to read text.");
      return;
    }
    analysisAbortRef.current?.abort();
    const controller = new AbortController();
    analysisAbortRef.current = controller;

    isAnalyzingRef.current = true;
    setIsAnalyzing(true);
    setMode("processing");
    setError("");
    try {
      const ocrRes: OCRReadTextResponse = await readTextFromImage(frame, undefined, cleanPrompt, controller.signal);
      if (controller.signal.aborted) return;
      setMessage(ocrRes.summary);
      setExtractedText(ocrRes.text);
      setReadingType(ocrRes.reading_type);
      setPriority(ocrRes.priority);
      speak(ocrRes.summary);
    } catch (err) {
      if (controller.signal.aborted) return;
      const msg = err instanceof Error ? err.message : "OCR text reading failed.";
      setError(msg);
      setMode("idle");
      speak(msg);
    } finally {
      if (analysisAbortRef.current === controller) {
        isAnalyzingRef.current = false;
        setIsAnalyzing(false);
      }
    }
  }

  async function startVoiceInput() {
    if (isStartingVoiceRef.current) return;
    isStartingVoiceRef.current = true;
    userStoppedRef.current = false;

    const browserWindow = window as VoiceWindow;
    const SpeechRecognitionImpl = browserWindow.SpeechRecognition ?? browserWindow.webkitSpeechRecognition;
    const useNativeRecognition = !SpeechRecognitionImpl && isNativeSpeechRecognitionAvailable();
    if (!SpeechRecognitionImpl && !useNativeRecognition) {
      setMicState("unsupported");
      setError("Speech recognition is not supported in this browser.");
      isStartingVoiceRef.current = false;
      return;
    }

    if (!useNativeRecognition && !navigator.mediaDevices?.getUserMedia) {
      setMicState("unsupported");
      setError("Microphone access is not available in this browser.");
      isStartingVoiceRef.current = false;
      return;
    }

    setMicState("requesting");
    setError("");

    try {
      if (useNativeRecognition) {
        await nativeRecognitionRef.current?.stop();
        const nativeRecognition = new NativeSpeechRecognizer();
        nativeRecognitionRef.current = nativeRecognition;
        const started = await nativeRecognition.start({
          onstart: () => {
            setMicState("active");
            setMode("listening");
            setMessage("Listening for your command.");
          },
          onresult: (records) => {
            const transcript = records.find((record) => record.isFinal)?.transcript.trim();
            if (transcript) void handleTranscript(transcript);
          },
          onerror: (error) => {
            userStoppedRef.current = error === "not-allowed";
            setMicState(error === "not-allowed" ? "denied" : "inactive");
            setMode("idle");
            setError(
              error === "not-allowed"
                ? "Microphone permission was not granted."
                : "Microphone input could not be started.",
            );
          },
          onend: () => {
            setMicState("inactive");
            setMode((currentMode) => (currentMode === "speaking" || currentMode === "processing" ? currentMode : "idle"));
          },
        });
        if (!started) {
          if (!userStoppedRef.current) {
            setMicState("unsupported");
            setMode("idle");
            setError("Android speech recognition is unavailable on this device.");
          }
        }
        return;
      }

      if (recognitionRef.current) {
        try {
          recognitionRef.current.onstart = null;
          recognitionRef.current.onresult = null;
          recognitionRef.current.onerror = null;
          recognitionRef.current.onend = null;
          recognitionRef.current.stop();
        } catch {
          // ignore
        }
      }

      const recognition = new (SpeechRecognitionImpl as SpeechRecognitionCtor)();
      recognition.lang = "en-US";
      recognition.interimResults = false;
      recognition.continuous = false;
      recognitionRef.current = recognition;

      recognition.onstart = () => {
        setMicState("active");
        setMode("listening");
        setMessage("Listening for your command.");
      };

      recognition.onresult = async (event) => {
        const transcript = event.results?.[0]?.[0]?.transcript?.trim();
        if (!transcript) return;
        await handleTranscript(transcript);
      };

      recognition.onerror = (event: any) => {
        if (event?.error === "not-allowed") {
          userStoppedRef.current = true;
          setMicState("denied");
          setError("Microphone permission was not granted.");
        } else {
          setMicState("inactive");
          setError(event?.error ? `Microphone input error: ${event.error}` : "Microphone input could not be started.");
        }
        setMode("idle");
      };

      recognition.onend = () => {
        setMicState("inactive");
        setMode((currentMode) => (currentMode === "speaking" || currentMode === "processing" ? currentMode : "idle"));
      };

      recognition.start();
    } catch (err) {
      console.error("Microphone access error:", err);
      userStoppedRef.current = true;
      setMicState("denied");
      setMode("idle");
      setError("Microphone permission was not granted.");
    } finally {
      isStartingVoiceRef.current = false;
    }

    async function handleTranscript(transcript: string): Promise<void> {
      setMode("processing");
      const lower = transcript.toLowerCase();

      // 0. Emergency intent
      const isEmergencyIntent =
        lower.includes("emergency") ||
        lower.includes("sos") ||
        lower.includes("help me") ||
        lower.includes("i need help") ||
        lower.includes("need help") ||
        lower.includes("call 911") ||
        lower.includes("call emergency") ||
        lower.includes("ambulance");

      if (isEmergencyIntent) {
        selectScreen("emergency");
        return;
      }

      // 1. Reading intent
      const isReadingIntent =
        lower.includes("written") ||
        lower.includes("read this") ||
        lower.includes("read text") ||
        lower.includes("read sign") ||
        lower.includes("read label") ||
        lower.includes("what does this say");

      if (isReadingIntent) {
        if (cameraState !== "active") {
          selectScreen("vision");
          await activateCamera();
        }
        await performOCRScan(transcript);
        return;
      }

      // 2. Obstacle / Hazard intent
      const isObstacleIntent =
        lower.includes("obstacle") ||
        lower.includes("hazard") ||
        lower.includes("what is in front") ||
        lower.includes("what's in front") ||
        lower.includes("scan view") ||
        lower.includes("check surroundings");

      if (isObstacleIntent && cameraState === "active") {
        await performObstacleScan();
        return;
      }

      // 3. WebSocket path if connected
      const socket = socketRef.current;
      if (socket && socket.readyState === WebSocket.OPEN) {
        socket.send(JSON.stringify({ type: "speech", text: transcript }));
        return;
      }

      // 4. HTTP Voice Command Pipeline
      try {
        analysisAbortRef.current?.abort();
        const controller = new AbortController();
        analysisAbortRef.current = controller;

        let frame: string | null = null;
        if (cameraState === "active" && (isObstacleIntent || lower.includes("look") || lower.includes("see"))) {
          frame = captureFrameBase64("perception");
        }

        let cmdRes = await sendVoiceCommand(transcript, {
          imageBase64: frame,
          signal: controller.signal,
        });

        if (cmdRes.needs_frame && cameraState === "active") {
          const isReading = lower.includes("read") || lower.includes("written") || lower.includes("sign") || lower.includes("text") || lower.includes("document");
          frame = captureFrameBase64(isReading ? "ocr" : "perception");
          if (frame) {
            cmdRes = await sendVoiceCommand(transcript, { imageBase64: frame, signal: controller.signal });
          }
        }

        if (controller.signal.aborted) return;

        setMessage(cmdRes.text || "Command processed.");
        setPriority(cmdRes.priority || "normal");
        if (cmdRes.extracted_text) {
          setExtractedText(cmdRes.extracted_text);
        }
        speak(cmdRes.text || "");

        if (cmdRes.directives && cmdRes.directives.length > 0) {
          for (const directive of cmdRes.directives) {
            void executeDeviceDirective(directive, {
              speak,
              onEmergency: () => {
                selectScreen("emergency");
              },
              onNavigate: (dest) => {
                setNavigationRequest({ key: Date.now(), query: dest });
                selectScreen("navigation");
              },
              onScreenChange: (nextScreen) => {
                const validScreens: Screen[] = ["home", "vision", "navigation", "emergency", "history", "settings"];
                if (validScreens.includes(nextScreen as Screen)) {
                  selectScreen(nextScreen as Screen);
                }
              },
              onSearch: (query) => {
                setMessage(`Searching online for: ${query}`);
              },
              onOpenExternal: (_url, name) => {
                setMessage(`Opened ${name}.`);
              },
              onMessageSent: (recipient) => {
                setMessage(`Opened messaging for ${recipient}.`);
              },
              onCameraSwitch: () => {
                void activateCamera(cameraFacing === "environment" ? "user" : "environment");
              },
              onScanChange: (scanning) => {
                if (scanning && cameraState === "active") void performObstacleScan();
              },
            });
          }
        }

        if (cmdRes.action === "start_navigation" && cmdRes.navigation_destination) {
          setNavigationRequest({ key: Date.now(), query: cmdRes.navigation_destination });
          setScreen("navigation");
        }
        if (cmdRes.action === "sos" || (cmdRes as any).intent === "sos") {
          selectScreen("emergency");
        }
      } catch (err: unknown) {
        setMode("idle");
        const msg = err instanceof Error ? err.message : "Voice assistant request failed.";
        setError(msg);
        speak(msg);
      }
    }
  }

  function sendVoiceEvent(type: "wake_word" | "speech_start" | "stop") {
    if (type === "stop" && "speechSynthesis" in window) {
      window.speechSynthesis.cancel();
      setMode("idle");
    }
    if (type === "stop") {
      userStoppedRef.current = true;
      recognitionRef.current?.stop();
      void nativeRecognitionRef.current?.stop();
      micStreamRef.current?.getTracks().forEach((track) => track.stop());
      micStreamRef.current = null;
      setMicState("inactive");
    }
    if (type === "speech_start") {
      userStoppedRef.current = false;
    }
    const socket = socketRef.current;
    if (!socket || socket.readyState !== WebSocket.OPEN) {
      if (type === "speech_start") void startVoiceInput();
      return;
    }
    socket.send(JSON.stringify({ type }));
    setError("");
    if (type === "wake_word") {
      setMode("wake_word");
      setMessage("Wake word detected. Say your command.");
    }
    if (type === "speech_start") {
      void startVoiceInput();
    }
  }

  async function submitScene(event: FormEvent) {
    event.preventDefault();
    if (!scene.trim()) return;
    setMode("processing");
    setError("");
    try {
      const result = await describeScene(scene.trim());
      setMessage(result.message);
      setPriority(result.priority);
      speak(result.message);
    } catch (requestError) {
      setMode("idle");
      setError(requestError instanceof Error ? requestError.message : "The guidance service is unavailable.");
    }
  }

  const [cameraFacing, setCameraFacing] = useState<"environment" | "user">("environment");

  async function activateCamera(facing: "environment" | "user" = cameraFacing) {
    if (isActivatingCameraRef.current) return;
    isActivatingCameraRef.current = true;
    if (!navigator.mediaDevices?.getUserMedia) {
      setCameraState("denied");
      setError("Camera is not available in this browser. Please use Chrome, Edge, Safari, or Firefox.");
      isActivatingCameraRef.current = false;
      return;
    }
    setCameraState("requesting");
    setError("");
    try {
      if (streamRef.current) {
        streamRef.current.getTracks().forEach((track) => track.stop());
        streamRef.current = null;
      }
      let stream: MediaStream;
      try {
        stream = await navigator.mediaDevices.getUserMedia({
          video: {
            facingMode: { ideal: facing },
            width: { ideal: 1280 },
            height: { ideal: 720 },
          },
          audio: false,
        });
      } catch {
        stream = await navigator.mediaDevices.getUserMedia({ video: true, audio: false });
      }
      streamRef.current = stream;
      setCameraFacing(facing);
      setCameraState("active");
      if (videoRef.current) {
        videoRef.current.srcObject = stream;
        videoRef.current.play().catch(() => {});
      }
    } catch (err) {
      console.error("Camera access failed:", err);
      setCameraState("denied");
      setError("Camera permission was denied or camera is in use by another application.");
    } finally {
      isActivatingCameraRef.current = false;
    }
  }

  function stopCamera() {
    if (streamRef.current) {
      streamRef.current.getTracks().forEach((track) => track.stop());
      streamRef.current = null;
    }
    if (videoRef.current) {
      videoRef.current.srcObject = null;
    }
    setCameraState("inactive");
  }

  // Keyboard accessibility shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (["INPUT", "TEXTAREA"].includes((e.target as HTMLElement)?.tagName)) return;
      if (isAnalyzingRef.current) return;
      if (e.key === "v" || e.key === "V") {
        e.preventDefault();
        sendVoiceEvent("speech_start");
      } else if (e.key === "r" || e.key === "R") {
        e.preventDefault();
        if (cameraState === "active") void performOCRScan();
        else {
          selectScreen("vision");
          void activateCamera();
        }
      } else if (e.code === "Space") {
        e.preventDefault();
        if (cameraState === "active") void performObstacleScan();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [cameraState]);

  const hazard = priority.toLowerCase() === "urgent" || /stairs|hazard|warning|caution|danger/i.test(message);
  const selectScreen = (next: Screen) => {
    analysisAbortRef.current?.abort();
    // Stop camera tracks when navigating away from vision to save battery and camera processing
    if (screen === "vision" && next !== "vision") {
      stopCamera();
    }
    setScreen(next);
    if (next === "vision" && cameraState === "inactive") void activateCamera();
  };

  return (
    <main className={`app-shell screen-${screen} ${hazard ? "has-hazard" : ""}`} aria-label="SightGuide AI">
      <header className="topbar">
        <button className="brand-mark" type="button" onClick={() => selectScreen("home")} aria-label="Go to SightGuide home">
          ◉
        </button>
        <h1>SightGuide AI</h1>
        <div className="top-status">
          <Status label="GPS" active={gpsStatus === "active"} />
          <Status label="Gemini" active={serviceStatus === "connected"} />
          <Status label={isOnline ? "Online" : "Offline"} active={isOnline} />
          <span className="battery" aria-label="Battery status">
            ▮
          </span>
        </div>
      </header>

      <div className="app-content">
        {screen === "home" ? (
          <Home
            mode={mode}
            message={message}
            onListen={() => sendVoiceEvent("speech_start")}
            onScreen={selectScreen}
            gpsActive={gpsStatus === "active"}
          />
        ) : null}
        {screen === "vision" ? (
          <Vision
            videoRef={videoRef}
            canvasRef={canvasRef}
            streamRef={streamRef}
            cameraState={cameraState}
            cameraFacing={cameraFacing}
            mode={mode}
            message={message}
            error={error}
            isAnalyzing={isAnalyzing}
            extractedText={extractedText}
            readingType={readingType}
            copiedText={copiedText}
            obstacles={obstacles}
            onCamera={() => activateCamera()}
            onToggleFacing={() => activateCamera(cameraFacing === "environment" ? "user" : "environment")}
            onStopCamera={stopCamera}
            onScanObstacles={() => void performObstacleScan()}
            onReadOCR={() => void performOCRScan()}
            onCopyText={() => {
              if (extractedText) {
                void copyTextToClipboard(extractedText).then((copied) => {
                  if (copied) {
                    setCopiedText(true);
                    setTimeout(() => setCopiedText(false), 2000);
                  }
                });
              }
            }}
            onSpeakText={() => {
              if (extractedText) speak(`The text reads: ${extractedText}`);
            }}
          />
        ) : null}
        {screen === "navigation" ? (
          <NavigationScreen
            onListen={() => sendVoiceEvent("speech_start")}
            speak={speak}
            destinationRequest={navigationRequest}
            onLocationStatus={setGpsStatus}
          />
        ) : null}
        {screen === "emergency" ? (
          <EmergencyScreen
            speak={speak}
            onCancel={() => selectScreen("home")}
            onListen={() => sendVoiceEvent("speech_start")}
            autoStart={true}
          />
        ) : null}
        {screen === "history" ? (
          <EmptyScreen title="History" body="No activity history is available from the current backend." />
        ) : null}
        {screen === "settings" ? (
          <Settings
            serviceStatus={serviceStatus}
            cameraState={cameraState}
            micState={micState}
            onTestEmergency={() => selectScreen("emergency")}
          />
        ) : null}
      </div>

      <section className="persistent-voice" aria-live="polite">
        <div className={`voice-state state-${mode}`}>
          <span className="voice-state-dot" />
          <strong>{modeLabels[mode]}</strong>
          <span>{error || (mode === "speaking" ? "SightGuide is speaking" : "Voice guidance on")}</span>
        </div>
        <button className="speak-button" type="button" onClick={() => sendVoiceEvent("speech_start")}>
          <span>◉</span> Speak Command (V)
        </button>
        <button className="stop-button" type="button" onClick={() => sendVoiceEvent("stop")} aria-label="Stop voice guidance">
          Stop
        </button>
      </section>

      <nav className="bottom-nav" aria-label="Main navigation">
        <NavButton label="Home" active={screen === "home"} onClick={() => selectScreen("home")} />
        <NavButton label="Vision" active={screen === "vision"} onClick={() => selectScreen("vision")} />
        <NavButton label="Navigate" active={screen === "navigation"} onClick={() => selectScreen("navigation")} />
        <NavButton label="History" active={screen === "history"} onClick={() => selectScreen("history")} />
        <NavButton label="Settings" active={screen === "settings"} onClick={() => selectScreen("settings")} />
      </nav>

      {commandOpen ? (
        <form className="command-drawer" onSubmit={submitScene}>
          <label htmlFor="scene">Keyboard fallback for voice command / query</label>
          <textarea
            id="scene"
            value={scene}
            onChange={(event) => setScene(event.target.value)}
            placeholder="Type your question (e.g., What is in front of me? / Read text)..."
            autoFocus
          />
          <button type="submit" disabled={!scene.trim() || mode === "processing"}>
            Send to SightGuide
          </button>
        </form>
      ) : null}
      <button className="fallback-toggle" type="button" onClick={() => setCommandOpen((open) => !open)}>
        {commandOpen ? "Close keyboard fallback" : "Keyboard fallback"}
      </button>
    </main>
  );
}

function Home({
  mode,
  message,
  onListen,
  onScreen,
  gpsActive,
}: {
  mode: AppMode;
  message: string;
  onListen: () => void;
  onScreen: (screen: Screen) => void;
  gpsActive: boolean;
}) {
  return (
    <section className="home-screen">
      <div className="health-row">
        <Status label="Mic" active={mode !== "idle"} />
        <Status label="Camera" active={false} />
        <Status label="GPS" active={gpsActive} />
      </div>
      <div className="home-hero">
        <button className={`home-orb orb-${mode}`} type="button" onClick={onListen} aria-label="Activate voice assistant">
          <span>◉</span>
          <small>{modeLabels[mode]}</small>
        </button>
        <h2>How can I help you?</h2>
        <p>{message}</p>
        <p className="wake-prompt">
          Say <strong>&quot;Hey SightGuide&quot;</strong> or ask <em>&quot;What's written here?&quot;</em>
        </p>
      </div>
      <div className="quick-actions">
        <button type="button" onClick={() => onScreen("vision")}>
          📷 Open Vision & OCR
        </button>
        <button type="button" onClick={() => onScreen("navigation")}>
          🗺️ Open Navigation
        </button>
        <button type="button" onClick={() => onScreen("emergency")}>
          🆘 Emergency
        </button>
      </div>
    </section>
  );
}

function Vision({
  videoRef,
  canvasRef,
  streamRef,
  cameraState,
  cameraFacing,
  mode,
  message,
  error,
  isAnalyzing,
  extractedText,
  readingType,
  copiedText,
  obstacles,
  onCamera,
  onToggleFacing,
  onStopCamera,
  onScanObstacles,
  onReadOCR,
  onCopyText,
  onSpeakText,
}: {
  videoRef: RefObject<HTMLVideoElement | null>;
  canvasRef: RefObject<HTMLCanvasElement | null>;
  streamRef: RefObject<MediaStream | null>;
  cameraState: string;
  cameraFacing: "environment" | "user";
  mode: AppMode;
  message: string;
  error: string;
  isAnalyzing: boolean;
  extractedText: string | null;
  readingType: string | null;
  copiedText: boolean;
  obstacles: DetectedObstacle[];
  onCamera: () => void;
  onToggleFacing: () => void;
  onStopCamera: () => void;
  onScanObstacles: () => void;
  onReadOCR: () => void;
  onCopyText: () => void;
  onSpeakText: () => void;
}) {
  useEffect(() => {
    if (cameraState === "active" && videoRef.current && streamRef.current) {
      if (videoRef.current.srcObject !== streamRef.current) {
        videoRef.current.srcObject = streamRef.current;
      }
      videoRef.current.play().catch(() => {});
    }
  }, [cameraState, streamRef]);

  return (
    <section className="vision-screen">
      <div className="vision-feed">
        {cameraState === "active" ? (
          <>
            <video
              ref={(node) => {
                if (videoRef) {
                  (videoRef as any).current = node;
                }
                if (node && streamRef.current && node.srcObject !== streamRef.current) {
                  node.srcObject = streamRef.current;
                  node.play().catch(() => {});
                }
              }}
              autoPlay
              muted
              playsInline
              style={{ width: "100%", height: "100%", minHeight: "50vh", objectFit: "cover" }}
              aria-label="Live camera preview"
            />
            <canvas ref={canvasRef} style={{ display: "none" }} />
          </>
        ) : (
          <div className="camera-empty">
            <span>◌</span>
            <strong>{cameraState === "requesting" ? "Starting camera..." : "Camera inactive"}</strong>
            <p>{error || "Enable the camera to begin live AI perception and OCR."}</p>
            <button type="button" onClick={onCamera}>
              Enable Camera
            </button>
          </div>
        )}
        <span className="vision-label">{modeLabels[mode]} / AI MULTIMODAL PERCEPTION</span>
      </div>

      {cameraState === "active" && (
        <div className="vision-actions-bar" style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", margin: "1rem 0" }}>
          <button
            type="button"
            className="btn-primary-scan"
            onClick={onScanObstacles}
            disabled={isAnalyzing}
            style={{ flex: "1 1 180px", minHeight: "48px", background: "#e3e2e7", color: "#121317", fontWeight: 700, borderRadius: "8px" }}
          >
            {isAnalyzing ? "Scanning..." : "⚡ Scan Hazards (Space)"}
          </button>
          <button
            type="button"
            className="btn-control-toggle active-continuous"
            onClick={onReadOCR}
            disabled={isAnalyzing}
            style={{ flex: "1 1 180px", minHeight: "48px", background: "#00d2ff", color: "#121317", fontWeight: 700, borderRadius: "8px" }}
          >
            {isAnalyzing ? "Reading..." : "📖 Read Text / OCR (R)"}
          </button>
          <button
            type="button"
            onClick={onToggleFacing}
            style={{ minHeight: "48px", padding: "0 14px", background: "#1e1f23", border: "1px solid #444748", color: "#e3e2e7", borderRadius: "8px" }}
            title="Switch front/back camera"
          >
            🔄 {cameraFacing === "environment" ? "Back Camera" : "Front Camera"}
          </button>
          <button
            type="button"
            onClick={onStopCamera}
            style={{ minHeight: "48px", padding: "0 14px", background: "#1e1f23", border: "1px solid #444748", color: "#c4c7c7", borderRadius: "8px" }}
            title="Turn camera off"
          >
            ⏹ Turn Off
          </button>
        </div>
      )}

      <div className="vision-response">
        <span className="eyebrow">Scene Understanding & Spoken Guidance</span>
        <h2>{message}</h2>
        <p>Press <strong>R</strong> to read signs/labels, <strong>Space</strong> to scan obstacles, or <strong>V</strong> to speak.</p>

        {extractedText && (
          <div className="extracted-ocr-card">
            <div className="ocr-card-header">
              <div className="ocr-badge">
                <span className="ocr-icon">📖</span>
                <span>TEXT READOUT {readingType ? `• ${readingType.toUpperCase()}` : ""}</span>
              </div>
              <div className="ocr-card-actions">
                <button type="button" className="btn-ocr-action" onClick={onSpeakText}>
                  🔊 Read Aloud
                </button>
                <button type="button" className="btn-ocr-action" onClick={onCopyText}>
                  {copiedText ? "✓ Copied!" : "📋 Copy"}
                </button>
              </div>
            </div>
            <div className="ocr-text-content">
              <pre className="ocr-verbatim-text">{extractedText}</pre>
            </div>
          </div>
        )}

        {obstacles.length > 0 && (
          <div className="detected-obstacles-section" style={{ marginTop: "1rem" }}>
            <h3 style={{ fontSize: "0.9rem", color: "#94a3b8", marginBottom: "0.5rem" }}>
              Detected Obstacles ({obstacles.length})
            </h3>
            <ul className="obstacles-list">
              {obstacles.map((item, idx) => (
                <li key={idx} className={`obstacle-card hazard-${item.hazard_level}`}>
                  <div className="obstacle-header">
                    <span className="obstacle-label">{item.label}</span>
                    <span className={`hazard-chip hazard-chip-${item.hazard_level}`}>{item.hazard_level.toUpperCase()}</span>
                  </div>
                  <div className="obstacle-details">
                    <div className="detail-item">
                      <span className="detail-icon">🧭</span>
                      <span className="detail-val">{item.location_clock}</span>
                    </div>
                    <div className="detail-item">
                      <span className="detail-icon">📏</span>
                      <span className="detail-val">{item.distance}</span>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  );
}

function Settings({
  serviceStatus,
  cameraState,
  micState,
  onTestEmergency,
}: {
  serviceStatus: string;
  cameraState: string;
  micState: string;
  onTestEmergency?: () => void;
}) {
  const [customUrl, setCustomUrl] = useState<string>(getCustomApiBaseUrl() || "");
  const [savedNotice, setSavedNotice] = useState<string>("");

  // Emergency Contact state
  const defaultContact = getDefaultEmergencyContact();
  const [contactName, setContactName] = useState<string>(() => loadEmergencyContact()?.name || "");
  const [contactPhone, setContactPhone] = useState<string>(() => loadEmergencyContact()?.phone || "");
  const [contactRelation, setContactRelation] = useState<string>(() => loadEmergencyContact()?.relationship || "");
  const [contactNotice, setContactNotice] = useState<string>("");

  // Saved Contacts (Mom, Dad, etc.) state
  const [contactsList, setContactsList] = useState<SavedContact[]>(() => loadContactsList());
  const [newContactName, setNewContactName] = useState<string>("");
  const [newContactPhone, setNewContactPhone] = useState<string>("");
  const [savedContactNotice, setSavedContactNotice] = useState<string>("");

  const handleAddGeneralContact = (e: FormEvent) => {
    e.preventDefault();
    if (!newContactName.trim() || !newContactPhone.trim()) return;
    addContact(newContactName, newContactPhone);
    setContactsList(loadContactsList());
    setSavedContactNotice(`Added contact: ${newContactName.trim()}`);
    setNewContactName("");
    setNewContactPhone("");
    setTimeout(() => setSavedContactNotice(""), 3000);
  };

  const handleRemoveGeneralContact = (name: string) => {
    removeContact(name);
    setContactsList(loadContactsList());
    setSavedContactNotice(`Removed contact: ${name}`);
    setTimeout(() => setSavedContactNotice(""), 3000);
  };

  const handleSaveUrl = (e: FormEvent) => {
    e.preventDefault();
    setCustomApiBaseUrl(customUrl);
    setSavedNotice("Backend URL updated. Restart or reload the app to take effect.");
    setTimeout(() => setSavedNotice(""), 4000);
  };

  const handleSaveContact = (e: FormEvent) => {
    e.preventDefault();
    const cleanPhone = contactPhone.trim();
    const cleanName = contactName.trim();
    if (!cleanPhone && !cleanName) {
      saveEmergencyContact(null);
      setContactNotice("Emergency contact reset to default (112).");
    } else {
      const contact: EmergencyContact = {
        name: cleanName || "Emergency Contact",
        phone: cleanPhone || defaultContact.phone,
        relationship: contactRelation.trim() || undefined,
      };
      saveEmergencyContact(contact);
      setContactNotice(`Saved emergency contact: ${contact.name} (${contact.phone}).`);
    }
    setTimeout(() => setContactNotice(""), 4000);
  };

  // Whole-Phone Voice Accessibility state
  const [a11yStatus, setA11yStatus] = useState<{ enabled: boolean; running: boolean }>({ enabled: false, running: false });
  const [overlayActive, setOverlayActive] = useState<boolean>(true);
  const [safetyConfirmActive, setSafetyConfirmActive] = useState<boolean>(true);
  const [a11yNotice, setA11yNotice] = useState<string>("");

  useEffect(() => {
    let mounted = true;
    const refreshA11y = async () => {
      if (isNativeAccessibilityAvailable()) {
        const status = await checkAccessibilityServiceStatus();
        if (mounted) setA11yStatus(status);
      }
    };
    void refreshA11y();
    const interval = setInterval(refreshA11y, 4000);
    return () => {
      mounted = false;
      clearInterval(interval);
    };
  }, []);

  const handleOpenA11ySettings = async () => {
    const opened = await openAndroidAccessibilitySettings();
    if (opened) {
      setA11yNotice("Opening Android Accessibility Settings. Look for 'SightGuide Voice Accessibility' and switch it ON.");
    } else {
      setA11yNotice("Whole-phone accessibility is active on native Android devices. When running on Android, enable the service in Settings.");
    }
    setTimeout(() => setA11yNotice(""), 6000);
  };

  const handleToggleOverlay = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.checked;
    setOverlayActive(val);
    await setAccessibilityOverlay(val);
  };

  const handleToggleSafety = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = e.target.checked;
    setSafetyConfirmActive(val);
    await setAccessibilitySafetyConfirmation(val);
  };

  const currentContact = loadEmergencyContact();

  return (
    <section className="feature-screen">
      <span className="eyebrow">Configuration</span>
      <h2>Settings</h2>

      {/* Whole-Phone Voice Accessibility Card */}
      <div className="settings-card a11y-settings-card" style={{ marginTop: "1.5rem", padding: "1.25rem", background: "#1a1b1f", border: "1px solid #444748", borderRadius: "12px", textAlign: "left" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", flexWrap: "wrap", gap: "0.5rem", marginBottom: "0.75rem" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.25rem", color: "#ffe171" }}>📱 Whole-Phone Voice Accessibility</h3>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
              Control any Android app hands-free using natural voice commands via the Android Accessibility Service.
            </p>
          </div>
          <span
            style={{
              padding: "0.3rem 0.65rem",
              borderRadius: "999px",
              fontSize: "0.75rem",
              fontWeight: 700,
              background: a11yStatus.running ? "rgba(74, 222, 128, 0.15)" : (a11yStatus.enabled ? "rgba(250, 204, 21, 0.15)" : "rgba(255, 255, 255, 0.08)"),
              color: a11yStatus.running ? "#4ade80" : (a11yStatus.enabled ? "#facc15" : "#94a3b8"),
              border: `1px solid ${a11yStatus.running ? "rgba(74, 222, 128, 0.3)" : (a11yStatus.enabled ? "rgba(250, 204, 21, 0.3)" : "rgba(255, 255, 255, 0.15)")}`,
            }}
          >
            {a11yStatus.running ? "● Active Across All Apps" : (a11yStatus.enabled ? "● Service Enabled" : "○ Service Disabled in Android Settings")}
          </span>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: "0.75rem", alignItems: "center", marginBottom: "1rem" }}>
          <button
            type="button"
            onClick={handleOpenA11ySettings}
            style={{
              padding: "0.5rem 0.9rem",
              borderRadius: "8px",
              background: "#ffe171",
              color: "#121317",
              fontWeight: 700,
              border: "none",
              fontSize: "0.85rem",
              cursor: "pointer",
            }}
          >
            ⚙️ Open Android Accessibility Settings
          </button>
        </div>

        {a11yNotice && (
          <div style={{ padding: "0.6rem 0.8rem", marginBottom: "1rem", borderRadius: "8px", background: "rgba(255, 225, 113, 0.1)", border: "1px solid #ffe171", fontSize: "0.8rem", color: "#ffe171" }}>
            {a11yNotice}
          </div>
        )}

        {/* Accessibility Preferences Toggles */}
        <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))", gap: "0.75rem", marginBottom: "1.25rem", padding: "0.75rem", background: "#0d0e12", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.06)" }}>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", color: "#e3e2e7", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={overlayActive}
              onChange={handleToggleOverlay}
              style={{ width: "16px", height: "16px", accentColor: "#ffe171" }}
            />
            <span>Show Floating Mic Bubble over other apps</span>
          </label>
          <label style={{ display: "flex", alignItems: "center", gap: "0.5rem", fontSize: "0.85rem", color: "#e3e2e7", cursor: "pointer" }}>
            <input
              type="checkbox"
              checked={safetyConfirmActive}
              onChange={handleToggleSafety}
              style={{ width: "16px", height: "16px", accentColor: "#ffe171" }}
            />
            <span>Confirm before sensitive actions (Delete, Pay)</span>
          </label>
        </div>

        {/* Voice Commands Guide for Blind Users */}
        <div style={{ padding: "0.75rem", background: "rgba(255, 255, 255, 0.03)", borderRadius: "8px", border: "1px solid rgba(255,255,255,0.06)" }}>
          <strong style={{ display: "block", fontSize: "0.85rem", color: "#e3e2e7", marginBottom: "0.4rem" }}>
            🗣️ Voice Commands You Can Speak Anytime:
          </strong>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))", gap: "0.5rem", fontSize: "0.8rem", color: "#cbd5e1" }}>
            <div>
              <span style={{ color: "#ffe171", fontWeight: 600 }}>Apps & Media:</span>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.2rem" }}>
                <li>&quot;Open YouTube&quot;</li>
                <li>&quot;Search for Minecraft&quot;</li>
                <li>&quot;Open the first video&quot;</li>
                <li>&quot;Play&quot; / &quot;Pause&quot;</li>
              </ul>
            </div>
            <div>
              <span style={{ color: "#ffe171", fontWeight: 600 }}>Messaging:</span>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.2rem" }}>
                <li>&quot;Open WhatsApp&quot;</li>
                <li>&quot;Type: I&apos;ll call you later&quot;</li>
                <li>&quot;Send&quot;</li>
              </ul>
            </div>
            <div>
              <span style={{ color: "#ffe171", fontWeight: 600 }}>System Navigation:</span>
              <ul style={{ margin: "2px 0 0", paddingLeft: "1.2rem" }}>
                <li>&quot;Scroll down&quot; / &quot;Scroll up&quot;</li>
                <li>&quot;Go back&quot; / &quot;Go home&quot;</li>
                <li>&quot;Recent apps&quot;</li>
                <li>&quot;What is on my screen?&quot;</li>
              </ul>
            </div>
          </div>
        </div>
      </div>

      {/* Saved Contacts Section for Call & SMS commands */}
      <div className="settings-card general-contacts-card" style={{ marginTop: "1.5rem", padding: "1.25rem", background: "#1a1b1f", border: "1px solid #444748", borderRadius: "12px", textAlign: "left" }}>
        <div style={{ marginBottom: "1rem" }}>
          <h3 style={{ margin: 0, fontSize: "1.2rem", color: "#e3e2e7" }}>👥 Saved Phone Contacts</h3>
          <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
            Used for voice commands like <em>&quot;Call Mom&quot;</em> or <em>&quot;Text Dad on my way&quot;</em>.
          </p>
        </div>

        {/* Existing Contacts List */}
        <div style={{ display: "flex", flexDirection: "column", gap: "0.5rem", marginBottom: "1rem" }}>
          {contactsList.length === 0 ? (
            <span style={{ fontSize: "0.85rem", color: "#64748b" }}>No custom contacts added yet.</span>
          ) : (
            contactsList.map((item) => (
              <div
                key={item.name}
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "center",
                  padding: "0.5rem 0.75rem",
                  background: "#0d0e12",
                  border: "1px solid rgba(255,255,255,0.08)",
                  borderRadius: "8px",
                }}
              >
                <div>
                  <strong style={{ textTransform: "capitalize", color: "#e3e2e7", fontSize: "0.95rem" }}>{item.name}</strong>
                  <span style={{ marginLeft: "0.5rem", color: "#ffe171", fontSize: "0.85rem" }}>{item.phone}</span>
                </div>
                <div style={{ display: "flex", gap: "0.4rem", alignItems: "center" }}>
                  <a
                    href={`tel:${item.phone}`}
                    style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem", background: "rgba(255,255,255,0.08)", borderRadius: "6px", color: "#e2e8f0", textDecoration: "none" }}
                  >
                    📞 Call
                  </a>
                  <a
                    href={`sms:${item.phone}`}
                    style={{ padding: "0.25rem 0.6rem", fontSize: "0.75rem", background: "rgba(56,189,248,0.15)", borderRadius: "6px", color: "#38bdf8", textDecoration: "none" }}
                  >
                    💬 Text
                  </a>
                  <button
                    type="button"
                    onClick={() => handleRemoveGeneralContact(item.name)}
                    style={{ padding: "0.25rem 0.5rem", fontSize: "0.75rem", background: "rgba(239,68,68,0.15)", border: "none", borderRadius: "6px", color: "#f87171" }}
                    title={`Delete ${item.name}`}
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Add Contact Form */}
        <form onSubmit={handleAddGeneralContact} style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}>
          <input
            type="text"
            value={newContactName}
            onChange={(e) => setNewContactName(e.target.value)}
            placeholder="Name (e.g. Mom / Sarah)"
            style={{ flex: "1 1 120px", padding: "0.45rem 0.65rem", borderRadius: "6px", background: "#0d0e12", border: "1px solid #444748", color: "#e3e2e7", fontSize: "0.85rem" }}
          />
          <input
            type="tel"
            value={newContactPhone}
            onChange={(e) => setNewContactPhone(e.target.value)}
            placeholder="Phone (e.g. +1-555-123-4567)"
            style={{ flex: "1 1 160px", padding: "0.45rem 0.65rem", borderRadius: "6px", background: "#0d0e12", border: "1px solid #444748", color: "#e3e2e7", fontSize: "0.85rem" }}
          />
          <button
            type="submit"
            style={{ padding: "0.45rem 0.85rem", borderRadius: "6px", background: "#ffe171", color: "#121317", fontWeight: 700, border: "none", fontSize: "0.85rem" }}
          >
            + Add Contact
          </button>
        </form>
        {savedContactNotice && <span style={{ display: "block", marginTop: "0.5rem", fontSize: "0.8rem", color: "#4ade80" }}>{savedContactNotice}</span>}
      </div>

      {/* Emergency Contact Card */}
      <div className="settings-card emergency-settings-card" style={{ marginTop: "1.5rem", padding: "1.25rem", background: "#1a1b1f", border: "1px solid #444748", borderRadius: "12px", textAlign: "left" }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: "1rem" }}>
          <div>
            <h3 style={{ margin: 0, fontSize: "1.2rem", color: "#e3e2e7" }}>🚨 Emergency Contact</h3>
            <p style={{ margin: "4px 0 0", fontSize: "0.85rem", color: "#94a3b8" }}>
              Active Contact: <strong style={{ color: "#ffe171" }}>{currentContact ? `${currentContact.name} (${currentContact.phone})` : "Default (112 - Emergency Services)"}</strong>
            </p>
          </div>
          {onTestEmergency && (
            <button
              type="button"
              onClick={onTestEmergency}
              style={{ padding: "0.4rem 0.8rem", fontSize: "0.85rem", background: "rgba(255, 225, 113, 0.15)", border: "1px solid #caa900", color: "#ffe171", borderRadius: "8px", fontWeight: 700 }}
            >
              Test Workflow
            </button>
          )}
        </div>

        <form onSubmit={handleSaveContact} style={{ display: "flex", flexDirection: "column", gap: "0.75rem" }}>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: "0.75rem" }}>
            <div>
              <label htmlFor="contact-name-input" style={{ display: "block", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "4px", fontWeight: 600 }}>
                Contact Name / Caregiver
              </label>
              <input
                id="contact-name-input"
                type="text"
                value={contactName}
                onChange={(e) => setContactName(e.target.value)}
                placeholder="e.g. Jane Doe / Mom"
                style={{ width: "100%", padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#0d0e12", border: "1px solid #444748", color: "#e3e2e7" }}
              />
            </div>
            <div>
              <label htmlFor="contact-phone-input" style={{ display: "block", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "4px", fontWeight: 600 }}>
                Phone Number (with Country Code)
              </label>
              <input
                id="contact-phone-input"
                type="tel"
                value={contactPhone}
                onChange={(e) => setContactPhone(e.target.value)}
                placeholder="e.g. +1 (555) 012-3456"
                style={{ width: "100%", padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#0d0e12", border: "1px solid #444748", color: "#e3e2e7" }}
              />
            </div>
          </div>
          <div>
            <label htmlFor="contact-rel-input" style={{ display: "block", fontSize: "0.8rem", color: "#94a3b8", marginBottom: "4px", fontWeight: 600 }}>
              Relationship / Notes (Optional)
            </label>
            <input
              id="contact-rel-input"
              type="text"
              value={contactRelation}
              onChange={(e) => setContactRelation(e.target.value)}
              placeholder="e.g. Primary Caregiver / Family"
              style={{ width: "100%", padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#0d0e12", border: "1px solid #444748", color: "#e3e2e7" }}
            />
          </div>

          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginTop: "0.25rem" }}>
            <button
              type="submit"
              style={{ padding: "0.5rem 1.25rem", borderRadius: "6px", background: "#e3e2e7", color: "#121317", fontWeight: 700, border: "none" }}
            >
              Save Emergency Contact
            </button>
            {contactNotice && <span style={{ fontSize: "0.85rem", color: "#4ade80" }}>{contactNotice}</span>}
          </div>
        </form>
      </div>

      <div className="settings-list">
        <Setting label="Active API URL" value={apiBaseUrl} />
        <Setting label="Voice backend" value={serviceStatus} />
        <Setting label="Microphone permission" value={micState} />
        <Setting label="Camera permission" value={cameraState} />
        <Setting label="Gemini Multimodal OCR" value="Active (Optimized for Android)" />
        <Setting label="Network status" value={typeof navigator !== "undefined" && navigator.onLine ? "Online" : "Offline"} />
      </div>

      <form onSubmit={handleSaveUrl} style={{ marginTop: "1.5rem", display: "flex", flexDirection: "column", gap: "0.5rem", textAlign: "left" }}>
        <label htmlFor="custom-api-input" style={{ fontSize: "0.85rem", color: "#94a3b8", fontWeight: 600 }}>
          Custom Backend Server URL (for Wi-Fi / Physical Device Testing):
        </label>
        <div style={{ display: "flex", gap: "0.5rem" }}>
          <input
            id="custom-api-input"
            type="text"
            value={customUrl}
            onChange={(e) => setCustomUrl(e.target.value)}
            placeholder="https://web-production-430eb.up.railway.app/api"
            style={{ flex: 1, padding: "0.5rem 0.75rem", borderRadius: "6px", background: "#1e1f23", border: "1px solid #444748", color: "#e3e2e7" }}
          />
          <button type="submit" style={{ padding: "0.5rem 1rem", borderRadius: "6px", background: "#e3e2e7", color: "#121317", fontWeight: 700, border: "none" }}>
            Save
          </button>
        </div>
        {savedNotice && <span style={{ fontSize: "0.8rem", color: "#4ade80" }}>{savedNotice}</span>}
      </form>
    </section>
  );
}

function Setting({ label, value }: { label: string; value: string }) {
  return (
    <div className="setting-row">
      <strong>{label}</strong>
      <span>{value}</span>
    </div>
  );
}

function EmptyScreen({ title, body }: { title: string; body: string }) {
  return (
    <section className="feature-screen">
      <span className="eyebrow">SightGuide</span>
      <h2>{title}</h2>
      <p>{body}</p>
      <div className="unavailable-panel">
        <strong>No data available</strong>
        <span>The current backend does not expose this service.</span>
      </div>
    </section>
  );
}

function Status({ label, active }: { label: string; active: boolean }) {
  return (
    <span className={`status-chip ${active ? "active" : ""}`}>
      <i />
      {label}
    </span>
  );
}

function NavButton({ label, active, onClick }: { label: string; active: boolean; onClick: () => void }) {
  return (
    <button type="button" className={active ? "active" : ""} onClick={onClick}>
      {label}
    </button>
  );
}
