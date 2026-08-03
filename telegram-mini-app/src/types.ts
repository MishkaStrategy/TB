export type Language = "ru" | "en";
export type MessageMode = "compact" | "detailed";
export type FvgSizeUnit = "USD" | "PERCENT";
export type Exchange = "bitunix" | "binance" | "bybit" | "bingx" | "bitget" | "gate";
export type HealthStatus = "ok" | "warning" | "unknown";
export type WebsocketStatus = "connected" | "disconnected" | "unknown";

export interface FilterScope {
  preFvg: boolean;
  confirmedFvg: boolean;
  bullish: boolean;
  bearish: boolean;
}

export interface PriceFilter {
  enabled: boolean;
  min: string | null;
  max: string | null;
  scope: FilterScope;
}

export interface SizeFilter {
  enabled: boolean;
  unit: FvgSizeUnit;
  min: string | null;
  scope: FilterScope;
}

export interface FvgSymbolSettings {
  symbol: string;
  enabled: boolean;
  priceFilter: PriceFilter;
  sizeFilter: SizeFilter;
}

export interface GeneralSettings {
  language: Language;
  messageMode: MessageMode;
}

export interface FvgSettings {
  enabled: boolean;
  notifyConfirmedFvg: boolean;
  notifyPreFvg: boolean;
  bullishEnabled: boolean;
  bearishEnabled: boolean;
  symbols: FvgSymbolSettings[];
}

export interface FundingSettings {
  enabled: boolean;
  intervalMinutes: number;
  threshold: string;
  notifyPositive: boolean;
  notifyNegative: boolean;
  exchanges: Exchange[];
  nextCheckAt: string | null;
}

export interface AllowedUser {
  telegramId: number;
  name: string;
  username?: string;
  source: "env" | "runtime";
}

export interface AdminDiagnostics {
  websocket: WebsocketStatus;
  lastWebsocketMessage: string | null;
  lastRestRecovery: string | null;
  lastError: string | null;
  outbox: number;
  deliveries: number;
  deliveryFailures: number;
  deliveryRetries: number;
  deliveryPermanentFailures: number;
  databases: HealthStatus;
  fvgDatabaseStatus: HealthStatus;
  fvgDatabaseBytes: number;
  fundingDatabaseStatus: HealthStatus;
  fundingDatabaseBytes: number;
  jsonSettingsBytes: number;
  processMemoryBytes: number;
  loadAverage: number[] | null;
  diskFreeBytes: number;
  diskTotalBytes: number;
  pid: number;
  release: string;
  gitCommit: string;
  pythonVersion: string;
}

export interface AdminSettings {
  available: boolean;
  publicAccessEnabled: boolean;
  allowedUsers: AllowedUser[];
  diagnostics: AdminDiagnostics;
}

export interface AppSettings {
  general: GeneralSettings;
  fvg: FvgSettings;
  funding: FundingSettings;
  admin: AdminSettings;
}

export interface TelegramUserSummary {
  id: number | null;
  firstName: string;
  username?: string;
}

export interface SettingsLimits {
  maxFvgSymbols: number;
}

export interface SettingsEnvelope {
  settings: AppSettings;
  user: TelegramUserSummary;
  limits?: SettingsLimits;
  source: "api" | "mock";
  updatedAt: string;
}

export interface SaveSettingsRequest {
  settings: AppSettings;
}
