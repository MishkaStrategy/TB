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
      websocket: "connected",
      lastWebsocketMessage: new Date(Date.now() - 18_000).toISOString(),
      lastRestRecovery: new Date(Date.now() - 12 * 60_000).toISOString(),
      lastError: null,
      outbox: 2,
      deliveries: 12_480,
      deliveryFailures: 7,
      deliveryRetries: 19,
      deliveryPermanentFailures: 1,
      databases: "ok",
      fvgDatabaseStatus: "ok",
      fvgDatabaseBytes: 3_420_160,
      fundingDatabaseStatus: "ok",
      fundingDatabaseBytes: 921_600,
      jsonSettingsBytes: 48_128,
      processMemoryBytes: 118_489_088,
      loadAverage: [0.24, 0.31, 0.28],
      diskFreeBytes: 68_719_476_736,
      diskTotalBytes: 107_374_182_400,
      pid: 2481,
      release: "1.2.0",
      gitCommit: "demo7ac",
      pythonVersion: "3.12.8",
    },
  },
};
