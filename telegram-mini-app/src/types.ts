export type Language = "ru" | "en";
export type MessageMode = "compact" | "detailed";
export type FvgSizeUnit = "USD" | "PERCENT";
export type Exchange = "bitunix" | "binance" | "bybit" | "bingx" | "bitget" | "gate";

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

export interface AdminSettings {
  available: boolean;
  publicAccessEnabled: boolean;
  allowedUsers: AllowedUser[];
  diagnostics: {
    websocket: "connected" | "disconnected" | "unknown";
    outbox: number;
    deliveryFailures: number;
    databases: "ok" | "warning" | "unknown";
    release: string;
  };
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

export interface SettingsEnvelope {
  settings: AppSettings;
  user: TelegramUserSummary;
  source: "api" | "mock";
  updatedAt: string;
}

export interface SaveSettingsRequest {
  settings: AppSettings;
}
