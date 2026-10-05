import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./design/global.css";
import "./index.css";
import App from "./App.tsx";
import { ErrorBoundary } from "./components/common/ErrorBoundary";
import { ApiAccessGate } from "./components/common/ApiAccessGate";
import { JobEventsProvider } from "./context/JobContext";
import { KeyboardShortcuts } from "./components/KeyboardShortcuts";

createRoot(document.getElementById("root")!).render(
    <StrictMode>
        <ErrorBoundary>
            <ApiAccessGate>
                <JobEventsProvider>
                    <KeyboardShortcuts />
                    <App />
                </JobEventsProvider>
            </ApiAccessGate>
        </ErrorBoundary>
    </StrictMode>,
);
