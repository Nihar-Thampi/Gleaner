export type Role = "admin" | "editor" | "viewer"
export type RunStatus = "queued" | "running" | "succeeded" | "partial" | "failed" | "cancelled"
export type Health = "healthy" | "warning" | "failing" | "running" | "never_run"
export type DomainStatus = "pending" | "approved" | "blocked"
export type ChangeKind = "new" | "changed" | "removed" | "returned"
export type FieldType = "string" | "number" | "integer" | "price" | "url" | "boolean"

export interface User {
  id: string
  email: string
  full_name: string
  role: Role
  is_active: boolean
  created_at: string
}

export interface Workspace {
  id: string
  name: string
  contact_email: string
  ai_run_summaries: boolean
}

export interface Me {
  user: User
  workspace: Workspace
}

export interface FieldSpec {
  name: string
  selector: string
  attr: string
  type: FieldType
  source: "list" | "detail"
  multiple: boolean
  required: boolean
  regex: string | null
  value_map: Record<string, string | number> | null
}

export interface ScraperConfig {
  item_selector: string
  fields: FieldSpec[]
  detail_link_selector: string | null
  next_page_selector: string | null
  max_pages: number
  max_items: number | null
  render: "static" | "browser"
  wait_for_selector: string | null
  key_fields: string[]
}

export interface RunBrief {
  id: string
  number: number
  scraper_id: string
  scraper_name: string
  status: RunStatus
  trigger: string
  triggered_by: string | null
  created_at: string
  started_at: string | null
  finished_at: string | null
  duration_ms: number | null
  items_extracted: number
  items_new: number
  items_changed: number
  items_removed: number
  items_invalid: number
  pages_fetched: number
  pages_failed: number
  requests_blocked: number
  anomaly_count: number
  error: string | null
  cancel_requested: boolean
  headline: string | null
}

export interface Anomaly {
  kind: string
  severity: "warning" | "critical"
  message: string
  field?: string
  item_id?: string
}

export interface AISummary {
  headline: string
  highlights: string[]
  watch: string[]
  provider: string
  model: string
}

export interface Quality {
  fill_rates: Record<string, number>
  type_errors: Record<string, number>
  rows_total: number
  rows_valid: number
  rows_invalid: number
  duplicates: number
  error_samples: { url: string; problem: string }[]
  removal_check: boolean
  baseline?: boolean
}

export interface Run extends RunBrief {
  items_unchanged: number
  retries: number
  bytes_downloaded: number
  avg_response_ms: number | null
  status_codes: Record<string, number>
  quality: Quality | null
  anomalies: Anomaly[]
  ai_summary: AISummary | null
  config: ScraperConfig & { start_urls: string[] }
}

export interface RunLogEntry {
  id: number
  at: string
  level: "info" | "warning" | "error"
  message: string
  url: string | null
}

export interface Scraper {
  id: string
  name: string
  description: string
  start_urls: string[]
  hosts: string[]
  domain_status: Record<string, DomainStatus | "unknown">
  schedule_minutes: number | null
  enabled: boolean
  next_run_at: string | null
  created_at: string
  updated_at: string
  item_count: number
  field_count: number
  render: "static" | "browser"
  last_run: RunBrief | null
  health: Health
  config?: ScraperConfig
}

export interface Column {
  name: string
  type: FieldType
  multiple: boolean
}

export interface Item {
  id: string
  key: string
  data: Record<string, unknown>
  source_url: string | null
  version: number
  first_seen_at: string
  last_seen_at: string
  last_changed_at: string
  removed_at: string | null
}

export interface Change {
  id: number
  kind: ChangeKind
  changes: Record<string, unknown>
  at: string
  run_id: string | null
  scraper_id: string
  scraper_name?: string
  item: { id: string; key: string; label: string; removed: boolean; source_url: string | null }
}

export interface Page<T> {
  total: number
  items: T[]
}

export interface Domain {
  id: string
  host: string
  status: DomainStatus
  basis: string
  requests_per_minute: number
  reviewed_by: string | null
  reviewed_at: string | null
  robots_status: number | null
  robots_fetched_at: string | null
  crawl_delay: number | null
  robots_summary: string
  scraper_count: number
  created_at: string
  robots_txt?: string | null
}

export type AlertKind = "field_change" | "new_item" | "item_removed" | "run_failed" | "anomaly"

export interface AlertRule {
  id: string
  scraper_id: string
  scraper_name: string
  name: string
  kind: AlertKind
  params: { field?: string; direction?: "any" | "up" | "down"; min_percent?: number; contains?: string }
  enabled: boolean
  created_at: string
  fired_7d: number
}

export interface AlertEvent {
  id: number
  rule_id: string
  rule_name: string
  kind: AlertKind
  scraper_id: string
  scraper_name: string
  run_id: string | null
  item_id: string | null
  message: string
  at: string
  read: boolean
}

export interface Delivery {
  id: number
  event: string
  status_code: number | null
  ok: boolean
  error: string | null
  duration_ms: number
  at: string
}

export interface Webhook {
  id: string
  url: string
  events: string[]
  enabled: boolean
  created_at: string
  secret_hint: string
  last_delivery: Delivery | null
  secret?: string
}

export interface ApiKey {
  id: string
  name: string
  prefix: string
  can_trigger_runs: boolean
  created_at: string
  last_used_at: string | null
  revoked_at: string | null
  key?: string
}

export interface AIStatus {
  provider: string
  model: string
  is_demo: boolean
}

export interface AIRequest {
  id: string
  feature: string
  provider: string
  model: string
  success: boolean
  error: string | null
  latency_ms: number
  input_tokens: number | null
  output_tokens: number | null
  created_at: string
  user_name: string | null
  input_preview: string
  input_text?: string
  output_text?: string
}

export interface PreviewResult {
  url?: string
  render: "static" | "browser"
  notes: string[]
  item_count: number
  rows: Record<string, unknown>[]
  fill_rates: Record<string, number>
  errors: string[]
  next_url: string | null
  detail_url?: string | null
}

export interface SuggestResult extends PreviewResult {
  valid: boolean
  error?: string
  config: ScraperConfig
  problems: string[]
  attempts?: number
  provider: string
  model: string
  symptoms?: string[]
}

export interface Dashboard {
  kpis: {
    scrapers: number
    scrapers_enabled: number
    items_tracked: number
    changes_24h: number
    changes_7d: number
    runs_7d: number
    success_rate_7d: number | null
    pages_7d: number
    blocked_7d: number
    unread_alerts: number
  }
  runs_by_day: { date: string; succeeded: number; failed: number }[]
  changes_by_day: { date: string; new: number; changed: number; removed: number }[]
  pages_by_host: { host: string; pages: number }[]
  attention: Scraper[]
  scrapers: Scraper[]
  recent_runs: RunBrief[]
  recent_alerts: AlertEvent[]
  recent_changes: Change[]
}
