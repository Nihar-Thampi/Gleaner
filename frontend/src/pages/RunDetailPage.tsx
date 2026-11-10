import { useEffect, useRef, useState } from "react"
import { Link, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AlertTriangle, CircleSlash, Info, Loader2, XCircle } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { AiBadge, Field, FillBar, Loading, Note, PageHeader, RunStatusBadge } from "@/components/common"
import { ChangesList } from "@/components/lists"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/context/AuthContext"
import { fmtBytes, fmtDateTime, fmtDuration, fmtNumber, fmtTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Change, Page, Run, RunLogEntry } from "@/types"

const ACTIVE = ["queued", "running"]

export default function RunDetailPage() {
  const { id = "" } = useParams()
  const { canEdit } = useAuth()
  const qc = useQueryClient()
  const { data: run } = useQuery({
    queryKey: ["run", id],
    queryFn: async () => (await api.get<Run>(`/runs/${id}`)).data,
    refetchInterval: (q) => (q.state.data && ACTIVE.includes(q.state.data.status) ? 1500 : false),
  })
  const active = !!run && ACTIVE.includes(run.status)
  const logs = useLiveLogs(id, active)
  const { data: changes } = useQuery({
    queryKey: ["changes", "run", id],
    queryFn: async () => (await api.get<Page<Change>>(`/scrapers/${run!.scraper_id}/changes`, { params: { run_id: id, limit: 100 } })).data,
    enabled: !!run && !active,
  })
  const cancel = useMutation({
    mutationFn: async () => (await api.post(`/runs/${id}/cancel`)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["run", id] })
      toast.success("Cancelling…")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  if (!run) return <Loading />
  const fill = run.quality?.fill_rates ?? {}
  const codes = Object.entries(run.status_codes).sort()

  return (
    <div className="space-y-4">
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            Run #{run.number} <RunStatusBadge status={run.status} />
          </span>
        }
        description={
          <>
            <Link to={`/scrapers/${run.scraper_id}`} className="font-medium text-foreground hover:text-link">
              {run.scraper_name}
            </Link>{" "}
            · {run.trigger === "schedule" ? "scheduled" : run.trigger === "api" ? "started from the API" : `started by ${run.triggered_by ?? "a user"}`} ·{" "}
            {fmtDateTime(run.created_at)}
          </>
        }
        actions={
          canEdit &&
          active && (
            <Button variant="outline" onClick={() => cancel.mutate()} disabled={cancel.isPending || run.cancel_requested}>
              <CircleSlash /> {run.cancel_requested ? "Cancelling…" : "Cancel run"}
            </Button>
          )
        }
      />

      {run.error && (
        <div className="flex items-start gap-2 rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
          <XCircle className="mt-0.5 size-4 shrink-0" /> {run.error}
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-4 lg:grid-cols-6">
        <Counter label="Pages fetched" value={run.pages_fetched} live={active} />
        <Counter label="Items found" value={run.items_extracted} live={active} />
        <Counter label="New" value={run.items_new} />
        <Counter label="Changed" value={run.items_changed} />
        <Counter label="Removed" value={run.items_removed} />
        <Counter label="Skipped (policy)" value={run.requests_blocked} tone={run.requests_blocked ? "warning" : undefined} />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <div className="space-y-4 lg:col-span-2">
          {run.ai_summary && (
            <Card>
              <CardContent className="space-y-2 p-5">
                <div className="flex items-center gap-2">
                  <AiBadge provider={run.ai_summary.provider} />
                  <span className="text-xs text-muted-foreground">Run summary</span>
                </div>
                <p className="font-medium">{run.ai_summary.headline}</p>
                {run.ai_summary.highlights.length > 0 && (
                  <ul className="list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                    {run.ai_summary.highlights.map((h) => (
                      <li key={h}>{h}</li>
                    ))}
                  </ul>
                )}
              </CardContent>
            </Card>
          )}
          {run.anomalies.length > 0 && (
            <Card className="border-warning/40">
              <CardHeader className="p-5 pb-2">
                <CardTitle className="text-base">Data-quality flags</CardTitle>
              </CardHeader>
              <CardContent className="space-y-2 p-5 pt-0">
                {run.anomalies.map((a, i) => (
                  <div key={i} className="flex items-start gap-2 text-sm">
                    <AlertTriangle className={cn("mt-0.5 size-4 shrink-0", a.severity === "critical" ? "text-destructive" : "text-warning")} />
                    <span>{a.message}</span>
                  </div>
                ))}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
              <CardTitle className="text-base">Log</CardTitle>
              {active && (
                <span className="flex items-center gap-1.5 text-xs text-link">
                  <Loader2 className="size-3 animate-spin" /> live
                </span>
              )}
            </CardHeader>
            <CardContent className="p-5 pt-0">
              <LogView entries={logs} follow={active} />
            </CardContent>
          </Card>

          {!active && changes && changes.total > 0 && (
            <Card>
              <CardHeader className="p-5 pb-0">
                <CardTitle className="text-base">What changed ({fmtNumber(changes.total)})</CardTitle>
              </CardHeader>
              <CardContent className="p-5 pt-0">
                <ChangesList changes={changes.items} />
              </CardContent>
            </Card>
          )}
        </div>

        <div className="space-y-4">
          <Card>
            <CardHeader className="p-5 pb-2">
              <CardTitle className="text-base">Requests</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-5 pt-0">
              <dl className="grid grid-cols-2 gap-3">
                <Field label="Duration">{fmtDuration(run.duration_ms)}</Field>
                <Field label="Downloaded">{fmtBytes(run.bytes_downloaded)}</Field>
                <Field label="Avg response">{run.avg_response_ms != null ? `${run.avg_response_ms} ms` : "—"}</Field>
                <Field label="Retries">{run.retries}</Field>
                <Field label="Failed pages">{run.pages_failed}</Field>
                <Field label="Fetching">{run.config.render === "browser" ? "Headless browser" : "Static HTML"}</Field>
              </dl>
              {codes.length > 0 && (
                <div>
                  <p className="text-xs text-muted-foreground">Status codes</p>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {codes.map(([code, n]) => (
                      <span key={code} className={cn("rounded border px-1.5 py-0.5 font-mono text-xs", Number(code) >= 400 && "border-destructive/40 text-destructive")}>
                        {code} × {n}
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {run.quality && (
            <Card>
              <CardHeader className="p-5 pb-2">
                <CardTitle className="text-base">Data quality</CardTitle>
              </CardHeader>
              <CardContent className="space-y-1.5 p-5 pt-0">
                {Object.entries(fill).map(([name, rate]) => (
                  <div key={name} className="flex items-center justify-between gap-2">
                    <span className="truncate font-mono text-xs">{name}</span>
                    <FillBar rate={rate} />
                  </div>
                ))}
                <p className="pt-2 text-xs text-muted-foreground">
                  {fmtNumber(run.quality.rows_valid)} valid rows · {run.quality.rows_invalid} rejected · {run.quality.duplicates} duplicates
                </p>
                {!run.quality.removal_check && (
                  <Note tone="warning">Not every listing page was read, so items missing from this run weren't marked removed.</Note>
                )}
                {run.quality.error_samples.length > 0 && (
                  <details className="text-xs">
                    <summary className="cursor-pointer text-muted-foreground">Sample problems</summary>
                    <ul className="mt-1 space-y-1">
                      {run.quality.error_samples.map((e, i) => (
                        <li key={i}>
                          {e.problem} <span className="break-all text-muted-foreground">({e.url})</span>
                        </li>
                      ))}
                    </ul>
                  </details>
                )}
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  )
}

function Counter({ label, value, live, tone }: { label: string; value: number; live?: boolean; tone?: "warning" }) {
  return (
    <Card>
      <CardContent className="p-3">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className={cn("mt-0.5 text-2xl font-semibold tabular-nums", tone === "warning" && "text-warning")}>
          {fmtNumber(value)}
          {live && <span className="ml-1 inline-block size-1.5 animate-pulse rounded-full bg-primary align-middle" />}
        </div>
      </CardContent>
    </Card>
  )
}

/** Fetches new log lines only (by id) while the run is active. */
function useLiveLogs(runId: string, active: boolean): RunLogEntry[] {
  const [entries, setEntries] = useState<RunLogEntry[]>([])
  const last = useRef(0)
  useEffect(() => {
    setEntries([])
    last.current = 0
  }, [runId])
  useQuery({
    queryKey: ["run-logs", runId, active],
    queryFn: async () => {
      const { data } = await api.get<RunLogEntry[]>(`/runs/${runId}/logs`, { params: { after: last.current } })
      if (data.length) {
        last.current = data[data.length - 1].id
        setEntries((cur) => {
          const max = cur.at(-1)?.id ?? 0
          return [...cur, ...data.filter((d) => d.id > max)]
        })
      }
      return data.length
    },
    refetchInterval: active ? 1500 : false,
  })
  return entries
}

const LEVEL_ICON = { info: Info, warning: AlertTriangle, error: XCircle }

function LogView({ entries, follow }: { entries: RunLogEntry[]; follow: boolean }) {
  const ref = useRef<HTMLDivElement>(null)
  const [level, setLevel] = useState<"all" | "warning">("all")
  useEffect(() => {
    if (follow && ref.current) ref.current.scrollTop = ref.current.scrollHeight
  }, [entries.length, follow])
  const shown = level === "all" ? entries : entries.filter((e) => e.level !== "info")
  return (
    <div>
      <div className="mb-2 flex gap-1 text-xs">
        {(["all", "warning"] as const).map((l) => (
          <button
            key={l}
            type="button"
            onClick={() => setLevel(l)}
            className={cn("rounded px-2 py-0.5", level === l ? "bg-accent font-medium" : "text-muted-foreground hover:bg-accent/50")}
          >
            {l === "all" ? `All (${entries.length})` : `Warnings & errors (${entries.filter((e) => e.level !== "info").length})`}
          </button>
        ))}
      </div>
      <div ref={ref} className="max-h-96 overflow-y-auto rounded-md border bg-muted/30 p-2 font-mono text-xs">
        {shown.length === 0 ? (
          <p className="p-2 text-muted-foreground">No log lines.</p>
        ) : (
          shown.map((e) => {
            const Icon = LEVEL_ICON[e.level]
            return (
              <div key={e.id} className="flex gap-2 py-0.5">
                <span className="shrink-0 text-muted-foreground">{fmtTime(e.at)}</span>
                <Icon
                  className={cn(
                    "mt-0.5 size-3 shrink-0",
                    e.level === "error" ? "text-destructive" : e.level === "warning" ? "text-warning" : "text-muted-foreground"
                  )}
                />
                <span className="min-w-0 break-words">
                  {e.message}
                  {e.url && <span className="block truncate text-muted-foreground">{e.url}</span>}
                </span>
              </div>
            )
          })
        )}
      </div>
    </div>
  )
}
