import { format, formatDistanceToNowStrict } from "date-fns"

import type { AlertKind, ChangeKind, DomainStatus, FieldType, Health, Role, RunStatus } from "@/types"

export const ROLE_LABELS: Record<Role, string> = { admin: "Admin", editor: "Editor", viewer: "Viewer" }

export const RUN_STATUS_LABELS: Record<RunStatus, string> = {
  queued: "Queued",
  running: "Running",
  succeeded: "Succeeded",
  partial: "Partial",
  failed: "Failed",
  cancelled: "Cancelled",
}

export const HEALTH_LABELS: Record<Health, string> = {
  healthy: "Healthy",
  warning: "Needs a look",
  failing: "Failing",
  running: "Running",
  never_run: "Not run yet",
}

export const DOMAIN_STATUS_LABELS: Record<DomainStatus, string> = { pending: "Pending review", approved: "Approved", blocked: "Blocked" }

export const CHANGE_LABELS: Record<ChangeKind, string> = { new: "New", changed: "Changed", removed: "Removed", returned: "Back" }

export const ALERT_KIND_LABELS: Record<AlertKind, string> = {
  field_change: "A field changes",
  new_item: "A new item appears",
  item_removed: "An item is removed",
  run_failed: "A run fails",
  anomaly: "A data-quality check flags something",
}

export const FIELD_TYPE_LABELS: Record<FieldType, string> = {
  string: "Text",
  number: "Number",
  integer: "Whole number",
  price: "Price",
  url: "URL",
  boolean: "Yes / no",
}

export const FIELD_TYPES = Object.keys(FIELD_TYPE_LABELS) as FieldType[]

export const SCHEDULES: { value: number | null; label: string }[] = [
  { value: null, label: "Manual only" },
  { value: 60, label: "Every hour" },
  { value: 360, label: "Every 6 hours" },
  { value: 720, label: "Every 12 hours" },
  { value: 1440, label: "Daily" },
  { value: 10080, label: "Weekly" },
]

export function scheduleLabel(minutes: number | null): string {
  const preset = SCHEDULES.find((s) => s.value === minutes)
  if (preset) return preset.label
  if (!minutes) return "Manual only"
  return minutes % 60 === 0 ? `Every ${minutes / 60} hours` : `Every ${minutes} minutes`
}

export function fmtDate(d: string | null | undefined): string {
  return d ? format(new Date(d), "d MMM yyyy") : "—"
}

export function fmtDateTime(d: string | null | undefined): string {
  return d ? format(new Date(d), "d MMM yyyy, HH:mm") : "—"
}

export function fmtTime(d: string): string {
  return format(new Date(d), "HH:mm:ss")
}

export function fmtAgo(d: string | null | undefined): string {
  return d ? `${formatDistanceToNowStrict(new Date(d))} ago` : "never"
}

export function fmtIn(d: string | null | undefined): string {
  if (!d) return "—"
  const date = new Date(d)
  return date.getTime() <= Date.now() ? "due now" : `in ${formatDistanceToNowStrict(date)}`
}

export function fmtDuration(ms: number | null | undefined): string {
  if (ms == null) return "—"
  if (ms < 1000) return `${ms} ms`
  const s = Math.round(ms / 1000)
  return s < 60 ? `${s}s` : `${Math.floor(s / 60)}m ${s % 60}s`
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(0)} KB`
  return `${(n / 1024 ** 2).toFixed(1)} MB`
}

export const fmtNumber = (n: number) => n.toLocaleString("en-GB")

export function fmtPercent(rate: number | null | undefined, digits = 0): string {
  return rate == null ? "—" : `${(rate * 100).toFixed(digits)}%`
}

/** Display a scraped value. */
export function fmtValue(value: unknown, type?: FieldType): string {
  if (value === null || value === undefined || value === "") return "—"
  if (Array.isArray(value)) return value.length ? value.join(", ") : "—"
  if (typeof value === "boolean") return value ? "Yes" : "No"
  if (typeof value === "number") {
    if (type === "price") return value.toLocaleString("en-GB", { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    return value.toLocaleString("en-GB", { maximumFractionDigits: 3 })
  }
  return String(value)
}

export function initials(name: string): string {
  return name
    .split(/\s+/)
    .map((p) => p[0])
    .slice(0, 2)
    .join("")
    .toUpperCase()
}

export function pctChange(oldV: unknown, newV: unknown): number | null {
  if (typeof oldV !== "number" || typeof newV !== "number" || oldV === 0) return null
  return ((newV - oldV) / Math.abs(oldV)) * 100
}
