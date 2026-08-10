import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { startAdminActionsEnhancer } from "./adminActions";
import { startUiLocalization } from "./i18n";
import { initTelegram } from "./telegram";
import "./styles.css";
import "./admin-actions.css";

initTelegram();
startUiLocalization();
startAdminActionsEnhancer();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
