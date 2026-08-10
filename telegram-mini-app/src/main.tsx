import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { startAdminActionsEnhancer } from "./adminActions";
import { startUiLocalization } from "./i18n";
import { startNavigationAccessibility } from "./navigationAccessibility";
import { initTelegram } from "./telegram";
import "./styles.css";
import "./admin-actions.css";
import "./navigation-redesign.css";
import "./design-audit.css";

initTelegram();
startUiLocalization();
startAdminActionsEnhancer();
startNavigationAccessibility();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
