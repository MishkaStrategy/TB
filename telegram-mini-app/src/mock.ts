import type { AppSettings, Exchange, FvgSymbolSettings } from "./types";

const defaultScope = {
  confirmedFvg: true,
  bullish: true,
  bearish: true,
};

function instrument(exchange: Exchange, symbol: string, key: string = `${exchange}|${symbol}`): FvgSymbolSettings {
  return {
    key,
    exchange,
    symbol,
    timeframes: ["15m", "1h", "4h", "1d"],
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
  };
}

export const mockSettings: AppSettings = {
  general: {
    language: "en",
    messageMode: "compact",
  },
  fvg: {
    enabled: true,
    notifyConfirmedFvg: true,
    bullishEnabled: true,
    bearishEnabled: true,
    symbols: [
      instrument("bitunix", "BTCUSDT", "BTCUSDT"),
      instrument("bybit", "ETHUSDT"),
      instrument("binance", "SOLUSDT"),
      instrument("gate", "XRPUSDT"),
      instrument("bingx", "DOGEUSDT"),
    ],
  },
  funding: {
    enabled: true,
    intervalMinutes: 30,
    threshold: "0.25",
    notifyPositive: true,
    notifyNegative: true,
    exchanges: ["binance", "bybit", "bingx", "bitget"],
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
      release: "1.3.9",
      gitCommit: "visual-audit",
      pythonVersion: "3.12.8",
    },
  },
};
