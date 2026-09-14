import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { GuidanceScreen } from "./features/guidance/GuidanceScreen";
import { ErrorBoundary } from "./core/ErrorBoundary";
import "./styles.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ErrorBoundary>
      <GuidanceScreen />
    </ErrorBoundary>
  </StrictMode>,
);
