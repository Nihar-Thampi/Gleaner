import { useState } from "react"
import { Link } from "react-router-dom"
import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Bell, CheckCheck } from "lucide-react"

import { api, params } from "@/api/client"
import { EmptyState, Loading, PageHeader, Pager } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Switch } from "@/components/ui/switch"
import { useAuth } from "@/context/AuthContext"
import { ALERT_KIND_LABELS, fmtAgo, fmtDateTime } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { AlertEvent, AlertRule, Page } from "@/types"

export default function AlertsPage() {
  const qc = useQueryClient()
  const { canEdit } = useAuth()
  const [unreadOnly, setUnreadOnly] = useState(false)
  const [offset, setOffset] = useState(0)
  const limit = 50
  const { data } = useQuery({
    queryKey: ["alerts", "list", unreadOnly, offset],
    queryFn: async () => (await api.get<Page<AlertEvent> & { unread: number }>("/alerts", { params: params({ unread: unreadOnly, limit, offset }) })).data,
    placeholderData: keepPreviousData,
  })
  const { data: rules } = useQuery({
    queryKey: ["rules", "all"],
    queryFn: async () => (await api.get<{ items: AlertRule[] }>("/alert-rules")).data.items,
  })
  const markRead = useMutation({
    mutationFn: async (ids?: number[]) => (await api.post("/alerts/read", ids ?? null)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["alerts"] }),
  })
  const toggle = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => (await api.patch(`/alert-rules/${id}`, { enabled })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["rules"] }),
  })

  return (
    <div>
      <PageHeader
        title="Alerts"
        description="Fired by alert rules on each scraper. Webhooks subscribed to “alert fired” receive them too."
        actions={
          !!data?.unread && (
            <Button variant="outline" onClick={() => markRead.mutate(undefined)}>
              <CheckCheck /> Mark all read ({data.unread})
            </Button>
          )
        }
      />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
            <CardTitle className="text-base">Alerts</CardTitle>
            <label className="flex items-center gap-2 text-sm text-muted-foreground">
              <Switch checked={unreadOnly} onCheckedChange={(v) => (setUnreadOnly(v), setOffset(0))} /> Unread only
            </label>
          </CardHeader>
          <CardContent className="p-5 pt-0">
            {!data ? (
              <Loading />
            ) : !data.items.length ? (
              <EmptyState title={unreadOnly ? "All caught up" : "No alerts yet"} icon={Bell} />
            ) : (
              <ul className="divide-y">
                {data.items.map((a) => (
                  <li
                    key={a.id}
                    className={cn("flex items-start gap-3 py-3", !a.read && "cursor-pointer")}
                    onClick={() => !a.read && markRead.mutate([a.id])}
                  >
                    <span className={cn("mt-1.5 size-2 shrink-0 rounded-full", a.read ? "bg-transparent" : "bg-destructive")} aria-label={a.read ? undefined : "Unread"} />
                    <div className="min-w-0 flex-1">
                      <p className={cn("text-sm", !a.read && "font-medium")}>{a.message}</p>
                      <div className="mt-0.5 flex flex-wrap gap-x-2 text-xs text-muted-foreground">
                        <span>{a.rule_name}</span>·
                        <Link to={`/scrapers/${a.scraper_id}${a.item_id ? `?tab=data&item=${a.item_id}` : ""}`} className="hover:text-link" onClick={(e) => e.stopPropagation()}>
                          {a.scraper_name}
                        </Link>
                        {a.run_id && (
                          <>
                            ·
                            <Link to={`/runs/${a.run_id}`} className="hover:text-link" onClick={(e) => e.stopPropagation()}>
                              run
                            </Link>
                          </>
                        )}
                      </div>
                    </div>
                    <span className="shrink-0 text-xs text-muted-foreground" title={fmtDateTime(a.at)}>
                      {fmtAgo(a.at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
            {data && <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="p-5 pb-2">
            <CardTitle className="text-base">Rules</CardTitle>
            <p className="text-xs text-muted-foreground">Add rules from a scraper's Alerts tab.</p>
          </CardHeader>
          <CardContent className="p-5 pt-0">
            {!rules ? (
              <Loading />
            ) : (
              <ul className="divide-y">
                {rules.map((r) => (
                  <li key={r.id} className="flex items-center gap-3 py-2.5">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">{r.name}</div>
                      <div className="truncate text-xs text-muted-foreground">
                        <Link to={`/scrapers/${r.scraper_id}?tab=alerts`} className="hover:text-link">
                          {r.scraper_name}
                        </Link>{" "}
                        · {ALERT_KIND_LABELS[r.kind]}
                      </div>
                    </div>
                    {r.fired_7d > 0 && <Badge variant="outline">{r.fired_7d} this week</Badge>}
                    {canEdit && <Switch checked={r.enabled} onCheckedChange={(enabled) => toggle.mutate({ id: r.id, enabled })} aria-label="Enabled" />}
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  )
}
