import { Link, useNavigate } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import { format, parseISO } from "date-fns"
import { Bell, Plus } from "lucide-react"

import { api } from "@/api/client"
import { HBarChart, MiniTable, StackedDays } from "@/components/charts"
import {
  ChangeBadge,
  ChartCard,
  EmptyState,
  FieldDiff,
  HealthBadge,
  LegendItem,
  Loading,
  PageHeader,
  RunStatusBadge,
  StatStrip,
  StatTile,
} from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { useAuth } from "@/context/AuthContext"
import { fmtAgo, fmtDuration, fmtNumber, fmtPercent } from "@/lib/format"
import type { Dashboard } from "@/types"

const RUN_SERIES = [
  { key: "succeeded", label: "Succeeded", color: "var(--chart-1)" },
  { key: "failed", label: "Failed", color: "var(--chart-neg)" },
]
const CHANGE_SERIES = [
  { key: "changed", label: "Changed", color: "var(--changed)" },
  { key: "new", label: "New", color: "var(--new)" },
  { key: "removed", label: "Removed", color: "var(--removed)" },
]

const day = (d: string) => format(parseISO(d), "EEE d MMM")

export default function DashboardPage() {
  const navigate = useNavigate()
  const { canEdit } = useAuth()
  const { data, isLoading } = useQuery({
    queryKey: ["dashboard"],
    queryFn: async () => (await api.get<Dashboard>("/dashboard")).data,
    refetchInterval: 15_000,
  })
  if (isLoading || !data) return <Loading />
  const k = data.kpis

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboard"
        description="What your scrapers collected, what changed and what needs attention."
        actions={
          canEdit && (
            <Button onClick={() => navigate("/scrapers/new")}>
              <Plus /> New scraper
            </Button>
          )
        }
      />

      <StatStrip>
        <StatTile label="Items tracked" value={fmtNumber(k.items_tracked)} hint={`across ${k.scrapers} scrapers`} onClick={() => navigate("/scrapers")} />
        <StatTile label="Changes, last 24 h" value={fmtNumber(k.changes_24h)} hint={`${fmtNumber(k.changes_7d)} in 7 days`} onClick={() => navigate("/changes")} />
        <StatTile
          label="Run success, 7 days"
          value={fmtPercent(k.success_rate_7d)}
          hint={`${k.runs_7d} finished runs`}
          tone={k.success_rate_7d !== null && k.success_rate_7d < 0.9 ? "warning" : undefined}
          onClick={() => navigate("/runs")}
        />
        <StatTile label="Pages fetched, 7 days" value={fmtNumber(k.pages_7d)} hint={`${k.blocked_7d} skipped by robots.txt or policy`} />
        <StatTile
          label="Unread alerts"
          value={k.unread_alerts}
          tone={k.unread_alerts ? "warning" : undefined}
          hint="price drops, new items, failures"
          onClick={() => navigate("/alerts")}
        />
      </StatStrip>

      {data.attention.length > 0 && (
        <Card className="border-warning/40">
          <CardHeader className="p-5 pb-2">
            <CardTitle className="text-base">Needs attention</CardTitle>
          </CardHeader>
          <CardContent className="divide-y p-5 pt-0">
            {data.attention.map((s) => (
              <Link key={s.id} to={`/scrapers/${s.id}`} className="flex flex-wrap items-center gap-3 py-2.5 hover:text-link">
                <HealthBadge health={s.health} />
                <span className="font-medium">{s.name}</span>
                <span className="min-w-0 flex-1 truncate text-sm text-muted-foreground">
                  {s.last_run?.error ?? (s.last_run?.anomaly_count ? `${s.last_run.anomaly_count} data-quality flag(s) on the last run` : "")}
                </span>
                <span className="text-xs text-muted-foreground">{fmtAgo(s.last_run?.finished_at ?? s.last_run?.created_at)}</span>
              </Link>
            ))}
          </CardContent>
        </Card>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <ChartCard
          title="Changes detected per day"
          description="Items that changed, appeared or disappeared, last 14 days"
          legend={CHANGE_SERIES.map((s) => <LegendItem key={s.key} color={s.color} label={s.label} />)}
          table={<MiniTable head={["Day", "Changed", "New", "Removed"]} rows={data.changes_by_day.map((d) => [day(d.date), d.changed, d.new, d.removed])} />}
        >
          <StackedDays data={data.changes_by_day} series={CHANGE_SERIES} />
        </ChartCard>
        <ChartCard
          title="Runs per day"
          description="Finished runs by outcome, last 14 days"
          legend={RUN_SERIES.map((s) => <LegendItem key={s.key} color={s.color} label={s.label} />)}
          table={<MiniTable head={["Day", "Succeeded", "Failed"]} rows={data.runs_by_day.map((d) => [day(d.date), d.succeeded, d.failed])} />}
        >
          <StackedDays data={data.runs_by_day} series={RUN_SERIES} />
        </ChartCard>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
            <CardTitle className="text-base">Latest changes</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/changes">All changes</Link>
            </Button>
          </CardHeader>
          <CardContent className="p-5 pt-0">
            {data.recent_changes.length === 0 ? (
              <EmptyState title="No changes yet">Changes appear after a scraper's second run.</EmptyState>
            ) : (
              <ul className="divide-y">
                {data.recent_changes.map((c) => (
                  <li key={c.id} className="flex flex-wrap items-start gap-x-3 gap-y-1 py-2.5">
                    <ChangeBadge kind={c.kind} />
                    <div className="min-w-0 flex-1">
                      <Link to={`/scrapers/${c.scraper_id}?tab=data&item=${c.item.id}`} className="font-medium hover:text-link">
                        {c.item.label}
                      </Link>
                      <div className="text-xs text-muted-foreground">{c.scraper_name}</div>
                      {c.kind === "changed" && (
                        <div className="mt-1 flex flex-col gap-0.5">
                          {Object.entries(c.changes)
                            .slice(0, 3)
                            .map(([field, v]) => {
                              const [a, b] = v as [unknown, unknown]
                              return <FieldDiff key={field} field={field} before={a} after={b} />
                            })}
                        </div>
                      )}
                    </div>
                    <span className="text-xs text-muted-foreground">{fmtAgo(c.at)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
            <CardTitle className="text-base">Recent alerts</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/alerts">All alerts</Link>
            </Button>
          </CardHeader>
          <CardContent className="p-5 pt-0">
            {data.recent_alerts.length === 0 ? (
              <EmptyState title="No alerts" icon={Bell} />
            ) : (
              <ul className="space-y-3">
                {data.recent_alerts.map((a) => (
                  <li key={a.id} className="text-sm">
                    <div className="flex items-center gap-1.5">
                      {!a.read && <span className="size-1.5 rounded-full bg-destructive" aria-label="Unread" />}
                      <span className="font-medium">{a.rule_name}</span>
                      <span className="ml-auto text-xs text-muted-foreground">{fmtAgo(a.at)}</span>
                    </div>
                    <p className="text-muted-foreground">{a.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
            <CardTitle className="text-base">Recent runs</CardTitle>
            <Button variant="ghost" size="sm" asChild>
              <Link to="/runs">All runs</Link>
            </Button>
          </CardHeader>
          <CardContent className="overflow-x-auto p-5 pt-0">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b text-left text-xs text-muted-foreground">
                  <th className="py-2 font-medium">Scraper</th>
                  <th className="py-2 font-medium">Status</th>
                  <th className="py-2 text-right font-medium">Items</th>
                  <th className="py-2 text-right font-medium">Changes</th>
                  <th className="py-2 text-right font-medium">Took</th>
                  <th className="py-2 text-right font-medium">When</th>
                </tr>
              </thead>
              <tbody>
                {data.recent_runs.map((r) => (
                  <tr key={r.id} className="cursor-pointer border-b last:border-0 hover:bg-accent/40" onClick={() => navigate(`/runs/${r.id}`)}>
                    <td className="py-2">
                      <div className="font-medium">{r.scraper_name}</div>
                      <div className="text-xs text-muted-foreground">Run #{r.number}</div>
                    </td>
                    <td className="py-2">
                      <RunStatusBadge status={r.status} />
                    </td>
                    <td className="py-2 text-right tabular-nums">{fmtNumber(r.items_extracted)}</td>
                    <td className="py-2 text-right tabular-nums">{r.items_new + r.items_changed + r.items_removed}</td>
                    <td className="py-2 text-right tabular-nums text-muted-foreground">{fmtDuration(r.duration_ms)}</td>
                    <td className="py-2 text-right text-xs text-muted-foreground">{fmtAgo(r.created_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </CardContent>
        </Card>
        <ChartCard
          title="Pages fetched by site"
          description="Last 7 days, within each site's rate limit"
          table={<MiniTable head={["Site", "Pages"]} rows={data.pages_by_host.map((p) => [p.host, p.pages])} />}
        >
          {data.pages_by_host.length ? (
            <HBarChart data={data.pages_by_host.map((p) => ({ label: p.host, value: p.pages }))} valueLabel="Pages" />
          ) : (
            <EmptyState title="No traffic this week" />
          )}
        </ChartCard>
      </div>
    </div>
  )
}
