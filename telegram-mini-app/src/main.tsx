import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { startUiLocalization } from "./i18n";
import { initTelegram } from "./telegram";
import "./styles.css";

initTelegram();
startUiLocalization();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
