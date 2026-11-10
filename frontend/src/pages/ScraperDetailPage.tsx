import { useState } from "react"
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ArrowDown,
  ArrowUp,
  Download,
  Loader2,
  Pause,
  Pencil,
  Play,
  Plus,
  Search,
  Trash2,
  WandSparkles,
} from "lucide-react"
import { toast } from "sonner"

import { api, download, errorMessage, params } from "@/api/client"
import { MiniTable, StackedDays } from "@/components/charts"
import {
  AiBadge,
  ChartCard,
  DomainBadge,
  EmptyState,
  ErrorNote,
  Field,
  FillBar,
  HealthBadge,
  LegendItem,
  Loading,
  Note,
  PageHeader,
  Pager,
  RunStatusBadge,
  ValueCell,
} from "@/components/common"
import { ItemDialog } from "@/components/ItemDialog"
import { ChangesList, RuleDialog, RunsTable } from "@/components/lists"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"
import { Input } from "@/components/ui/input"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useAuth } from "@/context/AuthContext"
import { ALERT_KIND_LABELS, CHANGE_LABELS, fmtAgo, fmtDateTime, fmtIn, fmtNumber, scheduleLabel } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { AlertEvent, AlertRule, Change, Column, Item, Page, Run, RunBrief, Scraper, SuggestResult } from "@/types"
import { useRunNow } from "@/pages/ScrapersPage"

const TABS = ["overview", "data", "changes", "runs", "alerts", "settings"] as const

export default function ScraperDetailPage() {
  const { id = "" } = useParams()
  const [search, setSearch] = useSearchParams()
  const tab = (TABS as readonly string[]).includes(search.get("tab") ?? "") ? search.get("tab")! : "overview"
  const openItem = search.get("item")
  const { canEdit } = useAuth()
  const qc = useQueryClient()
  const runNow = useRunNow()
  const [repairOpen, setRepairOpen] = useState(false)

  const { data: s, isLoading } = useQuery({
    queryKey: ["scraper", id],
    queryFn: async () => (await api.get<Scraper>(`/scrapers/${id}`)).data,
    refetchInterval: (q) => (q.state.data?.health === "running" ? 2500 : 30_000),
  })

  const toggle = useMutation({
    mutationFn: async (enabled: boolean) => (await api.patch<Scraper>(`/scrapers/${id}`, { enabled })).data,
    onSuccess: (d) => {
      qc.setQueryData(["scraper", id], d)
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      toast.success(d.enabled ? "Scraper resumed" : "Scraper paused")
    },
  })

  if (isLoading || !s) return <Loading />
  const setTab = (t: string) => setSearch((p) => (p.set("tab", t), p.delete("item"), p), { replace: true })
  const setItem = (itemId: string | null) =>
    setSearch((p) => {
      if (itemId) p.set("item", itemId)
      else p.delete("item")
      return p
    })
  const running = s.health === "running"
  const unapproved = s.hosts.filter((h) => s.domain_status[h] !== "approved")

  return (
    <div>
      <PageHeader
        title={
          <span className="flex flex-wrap items-center gap-3">
            {s.name} <HealthBadge health={s.health} />
          </span>
        }
        description={
          <span className="flex flex-wrap items-center gap-x-3 gap-y-1">
            {s.hosts.map((h) => (
              <span key={h} className="font-mono text-xs">
                {h}
              </span>
            ))}
            <span>{s.enabled ? scheduleLabel(s.schedule_minutes) : "Paused"}</span>
            {s.enabled && s.next_run_at && <span>next run {fmtIn(s.next_run_at)}</span>}
            {s.render === "browser" && <span>headless browser</span>}
          </span>
        }
        actions={
          canEdit && (
            <>
              {(s.health === "failing" || s.health === "warning") && (
                <Button variant="outline" onClick={() => setRepairOpen(true)}>
                  <WandSparkles /> Fix with AI
                </Button>
              )}
              <Button variant="outline" asChild>
                <Link to={`/scrapers/${s.id}/edit`}>
                  <Pencil /> Edit
                </Link>
              </Button>
              <Button variant="outline" onClick={() => toggle.mutate(!s.enabled)} disabled={toggle.isPending}>
                {s.enabled ? <Pause /> : <Play />} {s.enabled ? "Pause" : "Resume"}
              </Button>
              <Button onClick={() => runNow.mutate(s.id)} disabled={running || runNow.isPending || unapproved.length > 0}>
                {running ? <Loader2 className="animate-spin" /> : <Play />} {running ? "Running…" : "Run now"}
              </Button>
            </>
          )
        }
      />

      {unapproved.length > 0 && (
        <div className="mb-4">
          <Note tone="warning">
            This scraper can't run until {unapproved.join(", ")} {unapproved.length > 1 ? "are" : "is"} approved under{" "}
            <Link to="/domains" className="font-medium underline">
              Domains
            </Link>
            .
          </Note>
        </div>
      )}

      <Tabs value={tab} onValueChange={setTab}>
        <TabsList className="mb-4 flex-wrap">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="data">Data ({fmtNumber(s.item_count)})</TabsTrigger>
          <TabsTrigger value="changes">Changes</TabsTrigger>
          <TabsTrigger value="runs">Runs</TabsTrigger>
          <TabsTrigger value="alerts">Alerts</TabsTrigger>
          <TabsTrigger value="settings">Configuration</TabsTrigger>
        </TabsList>
        <TabsContent value="overview">
          <Overview scraper={s} onRepair={() => setRepairOpen(true)} />
        </TabsContent>
        <TabsContent value="data">
          <DataTab scraper={s} onOpenItem={setItem} />
        </TabsContent>
        <TabsContent value="changes">
          <ChangesTab scraperId={s.id} onOpenItem={setItem} />
        </TabsContent>
        <TabsContent value="runs">
          <RunsTab scraperId={s.id} running={running} />
        </TabsContent>
        <TabsContent value="alerts">
          <AlertsTab scraper={s} />
        </TabsContent>
        <TabsContent value="settings">
          <ConfigTab scraper={s} />
        </TabsContent>
      </Tabs>

      {openItem && <ItemDialog scraperId={s.id} itemId={openItem} onClose={() => setItem(null)} />}
      {repairOpen && <RepairDialog scraper={s} onClose={() => setRepairOpen(false)} />}
    </div>
  )
}

// ---- overview ----

function Overview({ scraper, onRepair }: { scraper: Scraper; onRepair: () => void }) {
  const lastId = scraper.last_run?.status === "running" || scraper.last_run?.status === "queued" ? null : scraper.last_run?.id
  const { data: last } = useQuery({
    queryKey: ["run", lastId],
    queryFn: async () => (await api.get<Run>(`/runs/${lastId}`)).data,
    enabled: !!lastId,
  })
  const { data: runs } = useQuery({
    queryKey: ["scraper-runs", scraper.id],
    queryFn: async () => (await api.get<RunBrief[]>(`/scrapers/${scraper.id}/runs`, { params: { limit: 30 } })).data,
  })
  const history = [...(runs ?? [])]
    .reverse()
    .filter((r) => r.status === "succeeded" || r.status === "partial")
    .map((r) => ({ date: r.created_at.slice(0, 10), label: `#${r.number}`, changed: r.items_changed, new: r.items_new, removed: r.items_removed }))
  const series = [
    { key: "changed", label: CHANGE_LABELS.changed, color: "var(--changed)" },
    { key: "new", label: CHANGE_LABELS.new, color: "var(--new)" },
    { key: "removed", label: CHANGE_LABELS.removed, color: "var(--removed)" },
  ]
  const { canEdit } = useAuth()

  return (
    <div className="space-y-4">
      {scraper.last_run?.status === "running" && <LiveRunBanner run={scraper.last_run} />}
      {last?.status === "failed" && (
        <Card className="border-destructive/40">
          <CardContent className="flex flex-wrap items-start gap-3 p-4">
            <div className="min-w-0 flex-1">
              <p className="font-medium text-destructive">Last run failed</p>
              <p className="text-sm text-muted-foreground">{last.error}</p>
            </div>
            {canEdit && (
              <Button variant="outline" onClick={onRepair}>
                <WandSparkles /> Fix with AI
              </Button>
            )}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
            <CardTitle className="text-base">Latest run</CardTitle>
            {last && (
              <Button variant="ghost" size="sm" asChild>
                <Link to={`/runs/${last.id}`}>Run #{last.number} details</Link>
              </Button>
            )}
          </CardHeader>
          <CardContent className="space-y-4 p-5 pt-0">
            {!last ? (
              <p className="text-sm text-muted-foreground">{scraper.last_run ? "Running now…" : "Not run yet."}</p>
            ) : (
              <>
                <dl className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                  <Field label="Status">
                    <RunStatusBadge status={last.status} />
                  </Field>
                  <Field label="Finished">{fmtAgo(last.finished_at)}</Field>
                  <Field label="Items">{fmtNumber(last.items_extracted)}</Field>
                  <Field label="Changes">
                    {last.items_new} new · {last.items_changed} changed · {last.items_removed} removed
                  </Field>
                </dl>
                {last.ai_summary && (
                  <div className="rounded-md border bg-muted/30 p-3">
                    <div className="mb-1 flex items-center gap-2">
                      <AiBadge provider={last.ai_summary.provider} />
                      <span className="text-xs text-muted-foreground">Run summary</span>
                    </div>
                    <p className="font-medium">{last.ai_summary.headline}</p>
                    {last.ai_summary.highlights.length > 0 && (
                      <ul className="mt-1 list-disc space-y-0.5 pl-5 text-sm text-muted-foreground">
                        {last.ai_summary.highlights.map((h) => (
                          <li key={h}>{h}</li>
                        ))}
                      </ul>
                    )}
                    {last.ai_summary.watch.length > 0 && (
                      <ul className="mt-2 space-y-0.5 text-sm text-warning">
                        {last.ai_summary.watch.map((w) => (
                          <li key={w}>⚠ {w}</li>
                        ))}
                      </ul>
                    )}
                  </div>
                )}
                {last.quality?.baseline && (
                  <Note>First run: these {fmtNumber(last.items_extracted)} items are the baseline. Later runs report changes against it.</Note>
                )}
              </>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-5 pb-2">
            <CardTitle className="text-base">Data quality</CardTitle>
            <p className="text-xs text-muted-foreground">How often each field was filled in the latest run</p>
          </CardHeader>
          <CardContent className="space-y-1.5 p-5 pt-0">
            {last?.quality ? (
              Object.entries(last.quality.fill_rates).map(([name, rate]) => (
                <div key={name} className="flex items-center justify-between gap-2 text-sm">
                  <span className="truncate font-mono text-xs">{name}</span>
                  <FillBar rate={rate} />
                </div>
              ))
            ) : (
              <p className="text-sm text-muted-foreground">Available after a successful run.</p>
            )}
            {last?.quality && last.quality.rows_invalid > 0 && (
              <p className="pt-1 text-xs text-warning">{last.quality.rows_invalid} rows rejected for missing required fields</p>
            )}
          </CardContent>
        </Card>
      </div>

      {history.length > 1 && (
        <ChartCard
          title="Changes per run"
          description={`Last ${history.length} successful runs`}
          legend={series.map((x) => <LegendItem key={x.key} color={x.color} label={x.label} />)}
          table={<MiniTable head={["Run", "Day", "Changed", "New", "Removed"]} rows={history.map((h) => [h.label, h.date, h.changed, h.new, h.removed])} />}
        >
          <StackedDays data={history} series={series} height={200} />
        </ChartCard>
      )}
    </div>
  )
}

export function LiveRunBanner({ run }: { run: RunBrief }) {
  return (
    <Card className="border-primary/40">
      <CardContent className="flex flex-wrap items-center gap-3 p-4 text-sm">
        <Loader2 className="size-4 animate-spin text-link" />
        <span className="font-medium">Run #{run.number} in progress</span>
        <span className="text-muted-foreground">
          {run.pages_fetched} pages · {fmtNumber(run.items_extracted)} items so far
        </span>
        <Button variant="link" size="sm" className="ml-auto h-auto p-0" asChild>
          <Link to={`/runs/${run.id}`}>Watch live</Link>
        </Button>
      </CardContent>
    </Card>
  )
}

// ---- data ----

function DataTab({ scraper, onOpenItem }: { scraper: Scraper; onOpenItem: (id: string) => void }) {
  const [q, setQ] = useState("")
  const [view, setView] = useState<"current" | "all" | "removed">("current")
  const [sort, setSort] = useState<string | null>(null)
  const [offset, setOffset] = useState(0)
  const limit = 50
  const query = { q: q || null, include_removed: view === "all", only_removed: view === "removed", sort, limit, offset }
  const { data, isLoading } = useQuery({
    queryKey: ["items", scraper.id, query],
    queryFn: async () => (await api.get<Page<Item> & { columns: Column[] }>(`/scrapers/${scraper.id}/items`, { params: params(query) })).data,
    placeholderData: keepPreviousData,
  })
  const columns = data?.columns ?? []
  const sortBy = (name: string) => {
    setOffset(0)
    setSort((cur) => (cur === `-${name}` ? name : cur === name ? null : `-${name}`))
  }
  const exportAs = (format: string) =>
    download(`/scrapers/${scraper.id}/export`, { format, q: q || null, include_removed: view !== "current" }).catch((e) => toast.error(errorMessage(e)))

  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-56 flex-1">
            <Search className="absolute top-2.5 left-2.5 size-4 text-muted-foreground" />
            <Input
              className="pl-8"
              placeholder="Search all fields"
              value={q}
              onChange={(e) => {
                setQ(e.target.value)
                setOffset(0)
              }}
            />
          </div>
          <Select
            value={view}
            onValueChange={(v) => {
              setView(v as typeof view)
              setOffset(0)
            }}
          >
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="current">Current items</SelectItem>
              <SelectItem value="all">Including removed</SelectItem>
              <SelectItem value="removed">Removed only</SelectItem>
            </SelectContent>
          </Select>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline">
                <Download /> Export
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => exportAs("csv")}>CSV</DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportAs("xlsx")}>Excel (.xlsx)</DropdownMenuItem>
              <DropdownMenuItem onClick={() => exportAs("json")}>JSON</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {isLoading ? (
          <Loading />
        ) : !data?.items.length ? (
          <EmptyState title={q ? "Nothing matches that search" : "No data yet"}>{!q && "Run the scraper to collect data."}</EmptyState>
        ) : (
          <>
            <div className="overflow-x-auto rounded-md border">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr className="text-left text-xs text-muted-foreground">
                    {columns.map((c) => (
                      <th key={c.name} className="whitespace-nowrap px-3 py-2 font-medium">
                        <button type="button" className="inline-flex items-center gap-1 font-mono hover:text-foreground" onClick={() => sortBy(c.name)}>
                          {c.name}
                          {sort === c.name && <ArrowUp className="size-3" />}
                          {sort === `-${c.name}` && <ArrowDown className="size-3" />}
                        </button>
                      </th>
                    ))}
                    <th className="whitespace-nowrap px-3 py-2 font-medium">
                      <button type="button" className="inline-flex items-center gap-1 hover:text-foreground" onClick={() => sortBy("last_changed_at")}>
                        Last changed
                        {sort === "last_changed_at" && <ArrowUp className="size-3" />}
                        {sort === "-last_changed_at" && <ArrowDown className="size-3" />}
                      </button>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((item) => (
                    <tr
                      key={item.id}
                      className={cn("cursor-pointer border-t hover:bg-accent/40", item.removed_at && "text-muted-foreground")}
                      onClick={() => onOpenItem(item.id)}
                    >
                      {columns.map((c) => (
                        <td key={c.name} className="max-w-64 truncate px-3 py-2" title={String(item.data[c.name] ?? "")}>
                          <span onClick={(e) => c.type === "url" && e.stopPropagation()}>
                            <ValueCell value={item.data[c.name]} type={c.type} />
                          </span>
                        </td>
                      ))}
                      <td className="whitespace-nowrap px-3 py-2 text-xs text-muted-foreground">
                        {item.removed_at ? <Badge variant="outline">Removed</Badge> : fmtAgo(item.last_changed_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />
          </>
        )}
      </CardContent>
    </Card>
  )
}

// ---- changes ----

function ChangesTab({ scraperId, onOpenItem }: { scraperId: string; onOpenItem: (id: string) => void }) {
  const [kind, setKind] = useState<string>("all")
  const [offset, setOffset] = useState(0)
  const limit = 50
  const { data, isLoading } = useQuery({
    queryKey: ["changes", scraperId, kind, offset],
    queryFn: async () =>
      (await api.get<Page<Change>>(`/scrapers/${scraperId}/changes`, { params: params({ kind: kind === "all" ? null : kind, limit, offset }) })).data,
    placeholderData: keepPreviousData,
  })
  return (
    <Card>
      <CardContent className="p-4">
        <div className="mb-2 flex items-center gap-2">
          <Select
            value={kind}
            onValueChange={(v) => {
              setKind(v)
              setOffset(0)
            }}
          >
            <SelectTrigger className="w-44">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All changes</SelectItem>
              {Object.entries(CHANGE_LABELS).map(([k, l]) => (
                <SelectItem key={k} value={k}>
                  {l}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {data && <span className="text-sm text-muted-foreground">{fmtNumber(data.total)} changes</span>}
        </div>
        {isLoading || !data ? <Loading /> : <ChangesList changes={data.items} onOpenItem={(c) => onOpenItem(c.item.id)} />}
        {data && <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />}
      </CardContent>
    </Card>
  )
}

// ---- runs ----

function RunsTab({ scraperId, running }: { scraperId: string; running: boolean }) {
  const { data } = useQuery({
    queryKey: ["scraper-runs", scraperId],
    queryFn: async () => (await api.get<RunBrief[]>(`/scrapers/${scraperId}/runs`, { params: { limit: 100 } })).data,
    refetchInterval: running ? 2500 : false,
  })
  return (
    <Card>
      <CardContent className="p-4">{data ? <RunsTable runs={data} /> : <Loading />}</CardContent>
    </Card>
  )
}

// ---- alerts ----

function AlertsTab({ scraper }: { scraper: Scraper }) {
  const { canEdit } = useAuth()
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const { data: rules } = useQuery({
    queryKey: ["rules", scraper.id],
    queryFn: async () => (await api.get<AlertRule[]>(`/scrapers/${scraper.id}/alert-rules`)).data,
  })
  const { data: events } = useQuery({
    queryKey: ["alerts", "scraper", scraper.id],
    queryFn: async () => (await api.get<Page<AlertEvent>>("/alerts", { params: { scraper_id: scraper.id, limit: 20 } })).data,
  })
  const update = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => (await api.patch(`/alert-rules/${id}`, { enabled })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  })
  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/alert-rules/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  })
  const columns: Column[] = (scraper.config?.fields ?? []).map((f) => ({ name: f.name, type: f.type, multiple: f.multiple }))

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
          <CardTitle className="text-base">Rules</CardTitle>
          {canEdit && (
            <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
              <Plus /> Rule
            </Button>
          )}
        </CardHeader>
        <CardContent className="p-5 pt-0">
          {!rules?.length ? (
            <EmptyState title="No alert rules">Get told when prices drop, items appear or a run fails.</EmptyState>
          ) : (
            <ul className="divide-y">
              {rules.map((r) => (
                <li key={r.id} className="flex items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{r.name}</div>
                    <div className="text-xs text-muted-foreground">{ALERT_KIND_LABELS[r.kind]}</div>
                  </div>
                  {canEdit && (
                    <>
                      <Switch checked={r.enabled} onCheckedChange={(enabled) => update.mutate({ id: r.id, enabled })} aria-label="Enabled" />
                      <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" onClick={() => remove.mutate(r.id)} aria-label="Delete rule">
                        <Trash2 />
                      </Button>
                    </>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="p-5 pb-2">
          <CardTitle className="text-base">Recent alerts</CardTitle>
        </CardHeader>
        <CardContent className="p-5 pt-0">
          {!events?.items.length ? (
            <p className="text-sm text-muted-foreground">None yet.</p>
          ) : (
            <ul className="space-y-2.5 text-sm">
              {events.items.map((e) => (
                <li key={e.id}>
                  <div className="flex justify-between gap-2 text-xs text-muted-foreground">
                    <span>{e.rule_name}</span>
                    <span>{fmtAgo(e.at)}</span>
                  </div>
                  <p>{e.message}</p>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      {creating && <RuleDialog scraperId={scraper.id} columns={columns} onClose={() => setCreating(false)} />}
    </div>
  )
}

// ---- configuration ----

function ConfigTab({ scraper }: { scraper: Scraper }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { canEdit } = useAuth()
  const [confirm, setConfirm] = useState(false)
  const config = scraper.config!
  const remove = useMutation({
    mutationFn: async () => api.delete(`/scrapers/${scraper.id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      toast.success("Scraper deleted")
      navigate("/scrapers")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <div className="grid gap-4 lg:grid-cols-3">
      <Card className="lg:col-span-2">
        <CardHeader className="p-5 pb-2">
          <CardTitle className="text-base">Fields</CardTitle>
        </CardHeader>
        <CardContent className="overflow-x-auto p-5 pt-0">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-xs text-muted-foreground">
                <th className="py-2 pr-3 font-medium">Name</th>
                <th className="py-2 pr-3 font-medium">Selector</th>
                <th className="py-2 pr-3 font-medium">Reads</th>
                <th className="py-2 pr-3 font-medium">Type</th>
                <th className="py-2 font-medium">Flags</th>
              </tr>
            </thead>
            <tbody>
              {config.fields.map((f) => (
                <tr key={f.name} className="border-b last:border-0">
                  <td className="py-2 pr-3 font-mono text-xs">{f.name}</td>
                  <td className="py-2 pr-3 font-mono text-xs">{f.selector || <span className="text-muted-foreground">(item)</span>}</td>
                  <td className="py-2 pr-3 text-xs">{f.attr === "text" ? "text" : `@${f.attr}`}</td>
                  <td className="py-2 pr-3 text-xs">{f.type}</td>
                  <td className="space-x-1 py-2 text-xs">
                    {config.key_fields.includes(f.name) && <Badge variant="outline">key</Badge>}
                    {f.required && <Badge variant="outline">required</Badge>}
                    {f.multiple && <Badge variant="outline">list</Badge>}
                    {f.source === "detail" && <Badge variant="outline">detail page</Badge>}
                    {f.regex && <Badge variant="outline">pattern</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </CardContent>
      </Card>
      <Card>
        <CardHeader className="p-5 pb-2">
          <CardTitle className="text-base">Crawl</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-5 pt-0">
          <Field label="Start URLs">
            {scraper.start_urls.map((u) => (
              <a key={u} href={u} target="_blank" rel="noreferrer" className="block truncate font-mono text-xs text-link hover:underline">
                {u}
              </a>
            ))}
          </Field>
          <Field label="Item selector">
            <span className="font-mono text-xs">{config.item_selector || "(whole page)"}</span>
          </Field>
          <Field label="Next page">
            <span className="font-mono text-xs">{config.next_page_selector ?? "—"}</span>
          </Field>
          <Field label="Detail pages">
            <span className="font-mono text-xs">{config.detail_link_selector ?? "—"}</span>
          </Field>
          <Field label="Limits">
            {config.max_pages} pages{config.max_items ? `, ${fmtNumber(config.max_items)} items` : ""}
          </Field>
          <Field label="Fetching">{config.render === "browser" ? "Headless browser" : "Static HTML"}</Field>
          <Field label="Domains">
            <div className="flex flex-col gap-1">
              {scraper.hosts.map((h) => (
                <span key={h} className="flex items-center gap-2">
                  <span className="font-mono text-xs">{h}</span> <DomainBadge status={scraper.domain_status[h]} />
                </span>
              ))}
            </div>
          </Field>
          <Field label="Created">{fmtDateTime(scraper.created_at)}</Field>
          {canEdit && (
            <div className="flex gap-2 pt-2">
              <Button variant="outline" size="sm" asChild>
                <Link to={`/scrapers/${scraper.id}/edit`}>
                  <Pencil /> Edit
                </Link>
              </Button>
              <Button variant="ghost" size="sm" className="text-destructive" onClick={() => setConfirm(true)}>
                <Trash2 /> Delete
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
      <Dialog open={confirm} onOpenChange={setConfirm}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Delete {scraper.name}?</DialogTitle>
            <DialogDescription>This removes the scraper, its {fmtNumber(scraper.item_count)} items, their history, runs and alert rules.</DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirm(false)}>
              Keep it
            </Button>
            <Button variant="destructive" onClick={() => remove.mutate()} disabled={remove.isPending}>
              {remove.isPending && <Loader2 className="animate-spin" />} Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

// ---- AI repair ----

function RepairDialog({ scraper, onClose }: { scraper: Scraper; onClose: () => void }) {
  const qc = useQueryClient()
  const { data, isLoading, error } = useQuery({
    queryKey: ["repair", scraper.id],
    queryFn: async () => (await api.post<SuggestResult>(`/ai/repair/${scraper.id}`)).data,
    staleTime: Infinity,
    gcTime: 0,
    retry: false,
  })
  const apply = useMutation({
    mutationFn: async () => (await api.patch<Scraper>(`/scrapers/${scraper.id}`, { config: data!.config })).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scraper", scraper.id] })
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      toast.success("Fix applied. Run the scraper to confirm.")
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const old = scraper.config!
  const changed = data?.valid
    ? [
        old.render !== data.config.render && ["Fetching", old.render, data.config.render],
        old.item_selector !== data.config.item_selector && ["Item selector", old.item_selector || "(page)", data.config.item_selector],
        ...data.config.fields
          .map((f) => {
            const o = old.fields.find((x) => x.name === f.name)
            return o && (o.selector !== f.selector || o.attr !== f.attr) ? [f.name, `${o.selector} @${o.attr}`, `${f.selector} @${f.attr}`] : false
          }),
      ].filter(Boolean) as string[][]
    : []

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-2xl">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <WandSparkles className="size-5 text-link" /> Fix {scraper.name}
          </DialogTitle>
          <DialogDescription>Reads the live page, proposes new settings and tests them before you apply anything.</DialogDescription>
        </DialogHeader>
        {isLoading ? (
          <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" /> Reading the page and testing a fix…
          </div>
        ) : error ? (
          <ErrorNote>{errorMessage(error)}</ErrorNote>
        ) : data ? (
          <div className="space-y-4">
            <div className="flex items-center gap-2">
              <AiBadge provider={data.provider} />
              <span className="text-sm text-muted-foreground">
                Finds <span className="font-medium text-foreground">{data.item_count}</span> items on the first page
              </span>
            </div>
            {data.notes.map((n) => (
              <Note key={n}>{n}</Note>
            ))}
            {changed.length > 0 ? (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-1.5 font-medium">Setting</th>
                    <th className="py-1.5 font-medium">Now</th>
                    <th className="py-1.5 font-medium">Proposed</th>
                  </tr>
                </thead>
                <tbody>
                  {changed.map(([k, a, b]) => (
                    <tr key={k} className="border-b last:border-0">
                      <td className="py-1.5 pr-2 font-mono text-xs">{k}</td>
                      <td className="py-1.5 pr-2 font-mono text-xs text-muted-foreground line-through">{a}</td>
                      <td className="py-1.5 font-mono text-xs">{b}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="text-sm text-muted-foreground">No setting changes needed.</p>
            )}
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Fill rates with the fix</p>
              <div className="grid gap-1 sm:grid-cols-2">
                {Object.entries(data.fill_rates).map(([n, r]) => (
                  <div key={n} className="flex items-center justify-between gap-2">
                    <span className="truncate font-mono text-xs">{n}</span>
                    <FillBar rate={r} />
                  </div>
                ))}
              </div>
            </div>
            {data.rows.length > 0 && (
              <div className="max-h-48 overflow-auto rounded-md border text-xs">
                <table className="w-full">
                  <tbody>
                    {data.rows.slice(0, 3).map((row, i) => (
                      <tr key={i} className="border-b last:border-0 align-top">
                        <td className="p-2">
                          {Object.entries(row)
                            .slice(0, 5)
                            .map(([k, v]) => (
                              <div key={k} className="truncate">
                                <span className="font-mono text-muted-foreground">{k}:</span> <ValueCell value={v} />
                              </div>
                            ))}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        ) : null}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => apply.mutate()} disabled={!data?.valid || !data.item_count || apply.isPending}>
            {apply.isPending && <Loader2 className="animate-spin" />} Apply fix
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
