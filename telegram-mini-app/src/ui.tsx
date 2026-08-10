import type { ReactNode } from "react";
import { impact } from "./telegram";
import type {
  Exchange,
  FvgSymbolSettings,
  FvgTimeframe,
  Language,
} from "./types";

export const exchangeLabels: Record<Exchange, string> = {
  bitunix: "Bitunix",
  binance: "Binance",
  bybit: "Bybit",
  bingx: "BingX",
  bitget: "Bitget",
  gate: "Gate",
};
export const exchangeOrder = Object.keys(exchangeLabels) as Exchange[];
export const timeframeOrder: FvgTimeframe[] = ["15m", "1h", "4h", "1d"];

export const tx = (language: Language, ru: string, en: string) => (
  language === "en" ? en : ru
);

export type IconName =
  | "home" | "fvg" | "funding" | "bell" | "settings" | "user"
  | "chevron" | "plus" | "edit" | "trash" | "filter" | "check"
  | "database" | "server" | "shield" | "refresh" | "save" | "alert"
  | "language" | "message" | "chart";

const paths: Record<IconName, ReactNode> = {
  home: <><path d="M3 10.8 12 3l9 7.8"/><path d="M5.5 9.8V21h13V9.8"/><path d="M9.5 21v-6h5v6"/></>,
  fvg: <><path d="M4 7h7v5H4z"/><path d="M13 12h7v5h-7z"/><path d="M4 17h7"/><path d="M13 7h7"/></>,
  funding: <><path d="M4 7h16"/><path d="M4 12h16"/><path d="M4 17h16"/><path d="m16 4 4 3-4 3"/><path d="m8 14-4 3 4 3"/></>,
  bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9"/><path d="M10 21h4"/></>,
  settings: <><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1-2.8 2.8-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.6V21h-4v-.1A1.7 1.7 0 0 0 9 19.4a1.7 1.7 0 0 0-1.9.3l-.1.1L4.2 17l.1-.1A1.7 1.7 0 0 0 4.6 15 1.7 1.7 0 0 0 3 14H3v-4h.1A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.3-1.9L4.2 7 7 4.2l.1.1A1.7 1.7 0 0 0 9 4.6 1.7 1.7 0 0 0 10 3V3h4v.1A1.7 1.7 0 0 0 15 4.6a1.7 1.7 0 0 0 1.9-.3l.1-.1L19.8 7l-.1.1A1.7 1.7 0 0 0 19.4 9 1.7 1.7 0 0 0 21 10h.1v4H21a1.7 1.7 0 0 0-1.6 1Z"/></>,
  user: <><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></>,
  chevron: <path d="m9 18 6-6-6-6"/>,
  plus: <><path d="M12 5v14"/><path d="M5 12h14"/></>,
  edit: <><path d="M4 20h4l11-11-4-4L4 16v4Z"/><path d="m13.5 6.5 4 4"/></>,
  trash: <><path d="M4 7h16"/><path d="M9 7V4h6v3"/><path d="m7 7 1 14h8l1-14"/></>,
  filter: <><path d="M4 5h16l-6 7v6l-4 2v-8L4 5Z"/></>,
  check: <path d="m5 12 4 4L19 6"/>,
  database: <><ellipse cx="12" cy="5" rx="8" ry="3"/><path d="M4 5v7c0 1.7 3.6 3 8 3s8-1.3 8-3V5"/><path d="M4 12v7c0 1.7 3.6 3 8 3s8-1.3 8-3v-7"/></>,
  server: <><rect x="3" y="4" width="18" height="6" rx="2"/><rect x="3" y="14" width="18" height="6" rx="2"/><path d="M7 7h.01M7 17h.01"/></>,
  shield: <><path d="M12 3 20 6v6c0 5-3.4 8-8 9-4.6-1-8-4-8-9V6l8-3Z"/><path d="m8.5 12 2.3 2.3L16 9"/></>,
  refresh: <><path d="M20 7v5h-5"/><path d="M4 17v-5h5"/><path d="M6.1 9A7 7 0 0 1 18.5 7L20 12"/><path d="M17.9 15A7 7 0 0 1 5.5 17L4 12"/></>,
  save: <><path d="M5 3h12l4 4v14H3V3h2Z"/><path d="M7 3v6h10V3"/><path d="M7 21v-7h10v7"/></>,
  alert: <><path d="M12 3 2.5 20h19L12 3Z"/><path d="M12 9v5"/><path d="M12 17h.01"/></>,
  language: <><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c2.5 2.5 3.8 5.5 3.8 9S14.5 18.5 12 21c-2.5-2.5-3.8-5.5-3.8-9S9.5 5.5 12 3Z"/></>,
  message: <><path d="M4 5h16v11H8l-4 4V5Z"/><path d="M8 9h8M8 12h5"/></>,
  chart: <><path d="M4 19V5"/><path d="M4 19h16"/><path d="m7 15 4-4 3 2 5-6"/></>,
};

export function Icon({ name, size = 20 }: { name: IconName; size?: number }) {
  return <svg className="tb-icon" width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[name]}</svg>;
}

export function Toggle({ checked, onChange, label }: { checked: boolean; onChange: (value: boolean) => void; label: string }) {
  return <button type="button" className={`tb-toggle ${checked ? "on" : ""}`} aria-label={label} aria-pressed={checked} onClick={() => { impact("light"); onChange(!checked); }}><span /></button>;
}

export function StatusBadge({ active, children }: { active: boolean; children: ReactNode }) {
  return <span className={`status-badge ${active ? "positive" : "neutral"}`}><i />{children}</span>;
}

export function Section({ title, subtitle, action, children, className = "" }: { title?: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`panel ${className}`}>{title || action ? <header className="panel-header"><div>{title ? <h2>{title}</h2> : null}{subtitle ? <p>{subtitle}</p> : null}</div>{action}</header> : null}{children}</section>;
}

export function PageHeader({ eyebrow, title, description, trailing }: { eyebrow?: string; title: string; description?: string; trailing?: ReactNode }) {
  return <div className="page-heading"><div>{eyebrow ? <span>{eyebrow}</span> : null}<h1>{title}</h1>{description ? <p>{description}</p> : null}</div>{trailing}</div>;
}

export function Chip({ active = false, children, onClick, tone = "default", disabled = false }: { active?: boolean; children: ReactNode; onClick?: () => void; tone?: "default" | "positive" | "negative"; disabled?: boolean }) {
  return <button type="button" className={`chip ${active ? "active" : ""} ${tone}`} aria-pressed={onClick ? active : undefined} disabled={disabled} onClick={() => { impact("light"); onClick?.(); }}>{active ? <Icon name="check" size={14} /> : null}{children}</button>;
}

export function PriceChange({ value }: { value: number | null | undefined }) {
  if (value === null || value === undefined || !Number.isFinite(value)) return <strong className="price-change unavailable">—</strong>;
  const tone = value > 0 ? "up" : value < 0 ? "down" : "flat";
  const sign = value > 0 ? "+" : "";
  return <strong className={`price-change ${tone}`}>{sign}{value.toFixed(2)}%</strong>;
}

export function Metric({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return <div className="metric"><span>{label}</span><strong>{value}</strong>{hint ? <small>{hint}</small> : null}</div>;
}

export function EmptyState({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon name="chart" size={22} /></div><strong>{title}</strong>{description ? <p>{description}</p> : null}{action}</div>;
}

export function formatInterval(minutes: number, language: Language): string {
  if (minutes < 60) return `${minutes} ${tx(language, "мин", "min")}`;
  const hours = Math.floor(minutes / 60);
  const rest = minutes % 60;
  if (!rest) return `${hours} ${tx(language, "ч", "h")}`;
  return `${hours} ${tx(language, "ч", "h")} ${rest} ${tx(language, "мин", "min")}`;
}

export function formatBytes(value: number): string {
  let amount = Math.max(0, Number(value) || 0);
  const units = ["B", "KB", "MB", "GB", "TB"];
  let index = 0;
  while (amount >= 1024 && index < units.length - 1) { amount /= 1024; index += 1; }
  return index === 0 ? `${Math.round(amount)} ${units[index]}` : `${amount.toFixed(1)} ${units[index]}`;
}

export function formatDate(value: string | null, language: Language): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleString(language === "en" ? "en-US" : "ru-RU", { dateStyle: "short", timeStyle: "short" });
}

export function activeFilterCount(instrument: FvgSymbolSettings): number {
  return Number(instrument.priceFilter.enabled) + Number(instrument.sizeFilter.enabled);
}