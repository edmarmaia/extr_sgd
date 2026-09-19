export type Operation = "batch" | "single" | "schedule" | "monitor";
declare const __DEPARTMENTS__: string[];
export type Row = Record<string, unknown>;
export interface InputFile {
  path: string;
  name: string;
  count: number;
}
export interface JobState {
  status: "idle" | "running" | "waiting" | "completed" | "cancelled" | "error";
  operation: string;
  phase: string;
  completed: number;
  total: number;
  rows: Row[];
  logs: { time: string; message: string }[];
  error: string | null;
  input: InputFile | null;
  next_run: string | null;
  autosave_path?: string | null;
  results_updated_at?: string | null;
  cycle: number;
}
export interface Options {
  operation: Operation;
  include_reasons: boolean;
  number: string;
  department: string;
  start_date: string;
  end_date: string;
  identifier: string;
  company: string;
  interval_minutes: number;
  delay: number;
  timeout: number;
  reason_timeout: number;
  attempts: number;
  debug: boolean;
}
interface Result {
  ok: boolean;
  error?: string;
}
export interface Bridge {
  select_input(): Promise<Result & { input?: InputFile }>;
  get_state(): Promise<JobState>;
  start_job(options: Options): Promise<Result>;
  cancel_job(): Promise<Result>;
  export_results(): Promise<Result & { path?: string }>;
}
declare global {
  interface Window {
    pywebview?: { api?: Bridge };
  }
}
export const emptyState: JobState = {
  status: "idle",
  operation: "",
  phase: "",
  completed: 0,
  total: 0,
  rows: [],
  logs: [],
  error: null,
  input: null,
  next_run: null,
  results_updated_at: null,
  cycle: 0,
};
export const departments = __DEPARTMENTS__;
export const defaults = {
  theme: "light" as "light" | "dark",
  include_reasons: true,
  department: departments[0] || "",
  interval_minutes: 15,
  delay: 1,
  timeout: 30,
  reason_timeout: 120,
  attempts: 3,
  debug: false,
};
export type Preferences = typeof defaults;
export const preferenceKey = "sgd.preferences.v1";
export function loadPreferences(): Preferences {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(preferenceKey) || "{}",
    );
    if (!value || typeof value !== "object") return { ...defaults };
    const p = value as Record<string, unknown>;
    const number = (
      key: keyof Preferences,
      min: number,
      max: number,
      integer = false,
    ) => {
      const n = p[key];
      return typeof n === "number" &&
        Number.isFinite(n) &&
        n >= min &&
        n <= max &&
        (!integer || Number.isInteger(n))
        ? n
        : (defaults[key] as number);
    };
    return {
      theme: p.theme === "dark" ? "dark" : defaults.theme,
      include_reasons:
        typeof p.include_reasons === "boolean"
          ? p.include_reasons
          : defaults.include_reasons,
      department:
        typeof p.department === "string" && departments.includes(p.department)
          ? p.department
          : defaults.department,
      interval_minutes: number("interval_minutes", 1, 1440, true),
      delay: defaults.delay,
      timeout: defaults.timeout,
      reason_timeout: defaults.reason_timeout,
      attempts: defaults.attempts,
      debug: defaults.debug,
    };
  } catch {
    return { ...defaults };
  }
}
export function text(value: unknown): string {
  if (value == null) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}
export function dateTime(value: string | null): string {
  if (!value) return "Não informado";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? value
    : date.toLocaleString("pt-BR", {
        year: "numeric", month: "2-digit", day: "2-digit",
        hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false,
      });
}
export function errorMessage(error: unknown): string {
  return error instanceof Error
    ? error.message
    : String(error || "Erro inesperado. Tente novamente.");
}
