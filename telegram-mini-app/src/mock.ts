import type { AppSettings } from "./types";

const defaultScope = {
  preFvg: true,
  confirmedFvg: true,
  bullish: true,
  bearish: true,
};

export const mockSettings: AppSettings = {
  general: {
    language: "ru",
    messageMode: "detailed",
  },
  fvg: {
    enabled: false,
    notifyConfirmedFvg: true,
    notifyPreFvg: false,
    bullishEnabled: true,
    bearishEnabled: true,
    symbols: [
      {
        symbol: "BTCUSDT",
        enabled: true,
        priceFilter: {
          enabled: false,
          min: null,
          max: null,
          scope: { ...defaultScope },
        },
        sizeFilter: {
          enabled: false,
          unit: "USD",
          min: null,
          scope: { ...defaultScope },
        },
      },
    ],
  },
  funding: {
    enabled: false,
    intervalMinutes: 60,
    threshold: "0.1",
    notifyPositive: true,
    notifyNegative: true,
    exchanges: ["bitunix"],
    nextCheckAt: null,
  },
  admin: {
    available: true,
    publicAccessEnabled: false,
    allowedUsers: [],
    diagnostics: {
      websocket: "unknown",
      outbox: 0,
      deliveryFailures: 0,
      databases: "unknown",
      release: "1.2.0",
    },
  },
};
