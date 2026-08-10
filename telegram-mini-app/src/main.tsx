import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import TradingApp from "./TradingApp";
import { initTelegram } from "./telegram";
import "./trading-dashboard.css";
import "./ui-audit.css";

initTelegram();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <TradingApp />
  </StrictMode>,
);
