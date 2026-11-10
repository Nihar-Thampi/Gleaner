import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { AppWindow, Play, Plus, Spline } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { DomainBadge, EmptyState, HealthBadge, Loading, PageHeader } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { useAuth } from "@/context/AuthContext"
import { fmtAgo, fmtIn, fmtNumber, scheduleLabel } from "@/lib/format"
import type { RunBrief, Scraper } from "@/types"

export function useRunNow() {
  const qc = useQueryClient()
  const navigate = useNavigate()
  return useMutation({
    mutationFn: async (id: string) => (await api.post<RunBrief>(`/scrapers/${id}/runs`)).data,
    onSuccess: (run) => {
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      qc.invalidateQueries({ queryKey: ["scraper", run.scraper_id] })
      toast.success(`Run #${run.number} queued`, { action: { label: "Watch", onClick: () => navigate(`/runs/${run.id}`) } })
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
}

export default function ScrapersPage() {
  const navigate = useNavigate()
  const { canEdit } = useAuth()
  const runNow = useRunNow()
  const { data, isLoading } = useQuery({
    queryKey: ["scrapers"],
    queryFn: async () => (await api.get<Scraper[]>("/scrapers")).data,
    refetchInterval: (q) => (q.state.data?.some((s) => s.health === "running") ? 3000 : 20_000),
  })

  return (
    <div>
      <PageHeader
        title="Scrapers"
        description="Each scraper turns one website's pages into rows of data, on a schedule or on demand."
        actions={
          canEdit && (
            <Button onClick={() => navigate("/scrapers/new")}>
              <Plus /> New scraper
            </Button>
          )
        }
      />
      {isLoading ? (
        <Loading />
      ) : !data?.length ? (
        <EmptyState title="No scrapers yet" icon={Spline}>
          Create one: paste a URL and describe the data you want.
        </EmptyState>
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {data.map((s) => (
            <Card key={s.id} className="flex flex-col transition-colors hover:border-primary/40">
              <CardContent className="flex flex-1 flex-col gap-3 p-4">
                <div className="flex items-start justify-between gap-2">
                  <Link to={`/scrapers/${s.id}`} className="min-w-0 font-semibold leading-snug hover:text-link">
                    {s.name}
                  </Link>
                  <HealthBadge health={s.health} />
                </div>
                <div className="flex flex-wrap items-center gap-1.5 text-xs text-muted-foreground">
                  {s.hosts.map((h) => (
                    <span key={h} className="inline-flex items-center gap-1.5">
                      <span className="font-mono">{h}</span>
                      {s.domain_status[h] !== "approved" && <DomainBadge status={s.domain_status[h]} />}
                    </span>
                  ))}
                  {s.render === "browser" && (
                    <span className="inline-flex items-center gap-1" title="Rendered in a headless browser">
                      <AppWindow className="size-3" /> browser
                    </span>
                  )}
                </div>
                <dl className="grid grid-cols-3 gap-2 text-sm">
                  <div>
                    <dt className="text-xs text-muted-foreground">Items</dt>
                    <dd className="font-medium tabular-nums">{fmtNumber(s.item_count)}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Last run</dt>
                    <dd>{s.last_run ? fmtAgo(s.last_run.finished_at ?? s.last_run.created_at) : "never"}</dd>
                  </div>
                  <div>
                    <dt className="text-xs text-muted-foreground">Schedule</dt>
                    <dd title={s.next_run_at ? `Next run ${fmtIn(s.next_run_at)}` : undefined}>
                      {s.enabled ? scheduleLabel(s.schedule_minutes) : "Paused"}
                    </dd>
                  </div>
                </dl>
                {s.last_run?.headline && <p className="line-clamp-2 text-sm text-muted-foreground">{s.last_run.headline}</p>}
                {s.last_run?.error && <p className="line-clamp-2 text-sm text-destructive">{s.last_run.error}</p>}
                <div className="mt-auto flex gap-2 pt-1">
                  <Button variant="outline" size="sm" asChild>
                    <Link to={`/scrapers/${s.id}?tab=data`}>View data</Link>
                  </Button>
                  {canEdit && (
                    <Button
                      variant="ghost"
                      size="sm"
                      disabled={s.health === "running" || runNow.isPending}
                      onClick={() => runNow.mutate(s.id)}
                    >
                      <Play /> Run now
                    </Button>
                  )}
                </div>
              </CardContent>
            </Card>
          ))}
        </div>
      )}
    </div>
  )
}
