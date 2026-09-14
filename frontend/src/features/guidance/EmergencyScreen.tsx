import { useEffect, useRef, useState, useCallback } from "react";
import {
  executeEmergencyDispatch,
  copyToClipboard,
  type EmergencyProgress,
  type EmergencyStep,
} from "../../voice/emergency";
import {
  loadEmergencyContact,
  getDefaultEmergencyContact,
} from "../../voice/deviceActions";
import { requestTelephonyPermissions, addCallEndedListener } from "../../voice/telephony";

interface EmergencyScreenProps {
  speak: (text: string) => void;
  onCancel: () => void;
  onListen?: () => void;
  autoStart?: boolean;
}

const COUNTDOWN_SECONDS = 5;

export function EmergencyScreen({ speak, onCancel, onListen, autoStart = true }: EmergencyScreenProps) {
  const [step, setStep] = useState<EmergencyStep>(autoStart ? "countdown" : "idle");
  const [countdown, setCountdown] = useState<number>(COUNTDOWN_SECONDS);
  const [copied, setCopied] = useState<boolean>(false);
  const [progress, setProgress] = useState<EmergencyProgress>(() => {
    const saved = loadEmergencyContact();
    const contact = saved || getDefaultEmergencyContact();
    return {
      step: autoStart ? "countdown" : "idle",
      countdown: COUNTDOWN_SECONDS,
      location: null,
      locationStatus: "pending",
      contact,
      smsBody: "",
      smsUrl: "",
      callUrl: "",
      message: "Ready to activate emergency assistance.",
      isCustomContact: Boolean(saved),
    };
  });

  useEffect(() => {
    void requestTelephonyPermissions();

    const unsubscribe = addCallEndedListener(() => {
      speak("Emergency call ended. SightGuide assistant is active.");
      onCancel();
    });

    return () => {
      unsubscribe();
    };
  }, [speak, onCancel]);

  const countdownTimerRef = useRef<number | null>(null);
  const isCancelledRef = useRef<boolean>(false);
  const hasDispatchedRef = useRef<boolean>(false);

  // Trigger actual dispatch
  const handleDispatch = useCallback(async () => {
    if (isCancelledRef.current || hasDispatchedRef.current) return;
    hasDispatchedRef.current = true;
    if (countdownTimerRef.current) {
      window.clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }

    setStep("locating");
    try {
      const result = await executeEmergencyDispatch({
        speak,
        onProgress: (partial) => {
          setProgress((prev) => ({ ...prev, ...partial }));
          if (partial.step) setStep(partial.step);
        },
      });
      setProgress(result);
      setStep(result.step);
    } catch {
      setStep("error");
      speak("Emergency dispatch encountered an issue. Please dial 9341240360 directly.");
    }
  }, [speak]);

  // Cancel handler
  const handleCancel = useCallback(() => {
    isCancelledRef.current = true;
    if (countdownTimerRef.current) {
      window.clearInterval(countdownTimerRef.current);
      countdownTimerRef.current = null;
    }
    setStep("cancelled");
    speak("Emergency assistance cancelled.");
    onCancel();
  }, [onCancel, speak]);

  // Countdown timer effect
  useEffect(() => {
    if (step !== "countdown") return;
    isCancelledRef.current = false;
    hasDispatchedRef.current = false;
    setCountdown(COUNTDOWN_SECONDS);

    speak(`Emergency assistance will activate in ${COUNTDOWN_SECONDS} seconds. Say cancel or tap cancel to abort.`);

    let remaining = COUNTDOWN_SECONDS;
    const interval = window.setInterval(() => {
      remaining -= 1;
      setCountdown(remaining);
      if (remaining <= 0) {
        window.clearInterval(interval);
        countdownTimerRef.current = null;
        void handleDispatch();
      }
    }, 1000);

    countdownTimerRef.current = interval;

    return () => {
      window.clearInterval(interval);
      countdownTimerRef.current = null;
    };
  }, [step, handleDispatch, speak]);

  // Handle Copy SMS
  const handleCopySMS = async () => {
    if (!progress.smsBody) return;
    const success = await copyToClipboard(progress.smsBody);
    if (success) {
      setCopied(true);
      setTimeout(() => setCopied(false), 3000);
    }
  };

  const contact = progress.contact;
  const location = progress.location;

  return (
    <section className="feature-screen emergency-container" aria-label="Emergency Assistance">
      {/* Top Header */}
      <div className="emergency-header-bar">
        <div className="emergency-badge">
          <span className="emergency-icon-pulse">🚨</span>
          <span className="emergency-badge-text">EMERGENCY ASSISTANCE</span>
        </div>
        <div style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
          {onListen && (
            <button
              type="button"
              className="btn-emergency-cancel-top"
              onClick={onListen}
              aria-label="Speak voice command"
              title="Speak Voice Command (V)"
            >
              🎤 Speak (V)
            </button>
          )}
          <button
            type="button"
            className="btn-emergency-cancel-top"
            onClick={handleCancel}
            aria-label="Cancel emergency"
            title="Cancel Emergency"
          >
            ✕ Cancel
          </button>
        </div>
      </div>

      {/* Main Mode: Countdown */}
      {step === "countdown" && (
        <div className="emergency-countdown-card">
          <div className="countdown-visual-wrapper">
            <div className="countdown-pulse-ring ring-1" />
            <div className="countdown-pulse-ring ring-2" />
            <svg className="countdown-svg" viewBox="0 0 120 120" aria-hidden="true">
              <circle cx="60" cy="60" r="52" className="countdown-bg-track" />
              <circle
                cx="60"
                cy="60"
                r="52"
                className="countdown-progress-track"
                style={{
                  strokeDashoffset: `${(326.7 * (COUNTDOWN_SECONDS - countdown)) / COUNTDOWN_SECONDS}`,
                }}
              />
            </svg>
            <div className="countdown-number-core">
              <span className="countdown-digit">{countdown}</span>
              <span className="countdown-unit">SECONDS</span>
            </div>
          </div>

          <h2 className="emergency-title">EMERGENCY ACTIVATION</h2>
          <p className="emergency-subtitle">
            Activating emergency contact alert and location dispatch in {countdown} seconds.
          </p>

          <div className="emergency-target-chip">
            <span className="target-label">Target Contact:</span>
            <strong>{contact.name}</strong> ({contact.phone})
          </div>

          {/* Large Action Buttons */}
          <div className="emergency-countdown-actions">
            <button
              type="button"
              className="btn-emergency-confirm"
              onClick={() => void handleDispatch()}
              aria-label="Send Emergency Alert Now"
            >
              <span>⚡</span> YES, SEND NOW
            </button>
            <button
              type="button"
              className="btn-emergency-cancel"
              onClick={handleCancel}
              aria-label="Cancel Emergency Alert"
            >
              <span>✕</span> CANCEL (NO)
            </button>
          </div>

          {/* Status Preview Indicators */}
          <div className="emergency-status-list">
            <div className="status-step-item active">
              <span className="status-dot pulsing" />
              <span>Acquiring GPS Coordinates</span>
            </div>
            <div className="status-step-item">
              <span className="status-dot" />
              <span>Preparing Emergency SMS & Live Map</span>
            </div>
            <div className="status-step-item">
              <span className="status-dot" />
              <span>Initiating Direct Phone Call</span>
            </div>
          </div>
        </div>
      )}

      {/* Main Mode: Dispatching / Active / Completed */}
      {step !== "countdown" && step !== "cancelled" && (
        <div className="emergency-active-card">
          <div className="emergency-active-header">
            <span className="active-dispatch-icon">🆘</span>
            <h2>Emergency Dispatch Active</h2>
            <p className="emergency-status-msg">{progress.message}</p>
          </div>

          {/* Real-time Dispatch Steps Timeline */}
          <div className="dispatch-timeline">
            {/* Step 1: Location */}
            <div className={`timeline-item ${progress.locationStatus === "acquired" ? "completed" : progress.locationStatus === "unavailable" ? "warning" : "in-progress"}`}>
              <div className="timeline-icon">
                {progress.locationStatus === "acquired" ? "✓" : progress.locationStatus === "unavailable" ? "!" : "📍"}
              </div>
              <div className="timeline-content">
                <strong>1. Current Location</strong>
                {location ? (
                  <p>
                    GPS: {location.lat.toFixed(5)}, {location.lon.toFixed(5)}{" "}
                    <a
                      href={`https://maps.google.com/?q=${location.lat},${location.lon}`}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="emergency-maps-link"
                    >
                      (View on Map ↗)
                    </a>
                  </p>
                ) : progress.locationStatus === "unavailable" ? (
                  <p className="status-warn-text">Location unavailable (GPS timeout or permission denied).</p>
                ) : (
                  <p className="status-pending-text">Acquiring GPS satellite fix...</p>
                )}
              </div>
            </div>

            {/* Step 2: Emergency Contact */}
            <div className="timeline-item completed">
              <div className="timeline-icon">✓</div>
              <div className="timeline-content">
                <strong>2. Identified Contact</strong>
                <p>
                  {contact.name} — <a href={`tel:${contact.phone}`} className="phone-link">{contact.phone}</a>
                  {progress.isCustomContact ? " (Configured Contact)" : " (Default Emergency Line)"}
                </p>
              </div>
            </div>

            {/* Step 3: SMS Dispatch */}
            <div className={`timeline-item ${progress.smsBody ? "completed" : "in-progress"}`}>
              <div className="timeline-icon">{progress.smsBody ? "✓" : "💬"}</div>
              <div className="timeline-content">
                <strong>3. Emergency SMS Message</strong>
                <p>{progress.smsBody ? "Prepared & opened in messaging app." : "Preparing SMS content..."}</p>
              </div>
            </div>

            {/* Step 4: Phone Call */}
            <div className={`timeline-item ${step === "completed" || step === "calling" ? "completed" : "in-progress"}`}>
              <div className="timeline-icon">📞</div>
              <div className="timeline-content">
                <strong>4. Telephone Call</strong>
                <p>Calling {contact.name} ({contact.phone}).</p>
              </div>
            </div>
          </div>

          {/* Prepared SMS Text Card */}
          {progress.smsBody && (
            <div className="emergency-sms-preview-card">
              <div className="sms-card-header">
                <span className="sms-badge">💬 EMERGENCY SMS PREVIEW</span>
                <div className="sms-actions">
                  <button type="button" className="btn-sms-action" onClick={handleCopySMS}>
                    {copied ? "✓ Copied!" : "📋 Copy Text"}
                  </button>
                  <a href={progress.smsUrl} className="btn-sms-action btn-sms-primary">
                    💬 Open SMS App
                  </a>
                </div>
              </div>
              <pre className="sms-body-text">{progress.smsBody}</pre>
            </div>
          )}

          {/* Quick Call Action Buttons */}
          <div className="emergency-action-buttons">
            <a href={progress.callUrl || `tel:${contact.phone}`} className="btn-call-emergency">
              <span>📞</span> Call {contact.name} ({contact.phone})
            </a>
            {contact.phone !== "112" && (
              <a href="tel:112" className="btn-call-112">
                <span>🚨</span> Call Emergency 112
              </a>
            )}
          </div>

          {/* Bottom Secondary Controls */}
          <div className="emergency-footer-controls">
            <button
              type="button"
              className="btn-retry-dispatch"
              onClick={() => {
                hasDispatchedRef.current = false;
                void handleDispatch();
              }}
            >
              🔄 Re-send Emergency Alert
            </button>
            <button type="button" className="btn-return-home" onClick={onCancel}>
              ✕ Return to Main Screen
            </button>
          </div>
        </div>
      )}

      {/* Cancelled State */}
      {step === "cancelled" && (
        <div className="emergency-cancelled-card">
          <span className="cancelled-icon">✕</span>
          <h2>Emergency Alert Cancelled</h2>
          <p>No further emergency actions will be taken.</p>
          <div className="emergency-cancelled-actions">
            <button
              type="button"
              className="btn-emergency-confirm"
              onClick={() => {
                setStep("countdown");
              }}
            >
              Restart Emergency Assistance
            </button>
            <button type="button" className="btn-return-home" onClick={onCancel}>
              Return to Home
            </button>
          </div>
        </div>
      )}
    </section>
  );
}
