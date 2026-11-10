import { useQuery } from "@tanstack/react-query"
import { Bell, ExternalLink } from "lucide-react"

import { api } from "@/api/client"
import { ValueHistoryChart } from "@/components/charts"
import { ChangeBadge, FieldDiff, Loading, ValueCell } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { fmtDateTime } from "@/lib/format"
import type { Change, Column, Item } from "@/types"

interface ItemDetail {
  item: Item
  columns: Column[]
  history: Change[]
  series: Record<string, { at: string; value: number }[]>
  alerts: { id: number; message: string; at: string; rule_name: string }[]
}

export function ItemDialog({ scraperId, itemId, onClose }: { scraperId: string; itemId: string; onClose: () => void }) {
  const { data } = useQuery({
    queryKey: ["item", scraperId, itemId],
    queryFn: async () => (await api.get<ItemDetail>(`/scrapers/${scraperId}/items/${itemId}`)).data,
  })
  const types = Object.fromEntries((data?.columns ?? []).map((c) => [c.name, c.type]))
  const title = data ? String(Object.values(data.item.data).find((v) => typeof v === "string" && v && !v.startsWith("http")) ?? data.item.key) : ""
  const chartable = Object.entries(data?.series ?? {}).filter(([, pts]) => new Set(pts.map((p) => p.value)).size > 1)

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        {!data ? (
          <Loading />
        ) : (
          <>
            <DialogHeader>
              <DialogTitle className="flex flex-wrap items-center gap-2 pr-6 leading-snug">
                {title}
                {data.item.removed_at && <Badge variant="outline">Removed {fmtDateTime(data.item.removed_at)}</Badge>}
              </DialogTitle>
              <DialogDescription>
                First seen {fmtDateTime(data.item.first_seen_at)} · last changed {fmtDateTime(data.item.last_changed_at)} · version{" "}
                {data.item.version}
                {data.item.source_url && (
                  <>
                    {" · "}
                    <a href={data.item.source_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-link hover:underline">
                      source page <ExternalLink className="size-3" />
                    </a>
                  </>
                )}
              </DialogDescription>
            </DialogHeader>

            <dl className="grid gap-x-6 gap-y-2 rounded-md border p-3 sm:grid-cols-2">
              {data.columns.map((c) => (
                <div key={c.name} className="min-w-0">
                  <dt className="font-mono text-xs text-muted-foreground">{c.name}</dt>
                  <dd className="truncate text-sm">
                    <ValueCell value={data.item.data[c.name]} type={c.type} />
                  </dd>
                </div>
              ))}
            </dl>

            {chartable.map(([field, points]) => (
              <section key={field}>
                <h3 className="mb-1 text-sm font-semibold">
                  <span className="font-mono">{field}</span> over time
                </h3>
                <ValueHistoryChart points={points} field={field} type={types[field] ?? "number"} />
              </section>
            ))}

            {data.alerts.length > 0 && (
              <section>
                <h3 className="mb-1 text-sm font-semibold">Alerts for this item</h3>
                <ul className="space-y-1 text-sm">
                  {data.alerts.map((a) => (
                    <li key={a.id} className="flex items-start gap-2">
                      <Bell className="mt-0.5 size-3.5 shrink-0 text-warning" />
                      <span className="flex-1">{a.message}</span>
                      <span className="text-xs text-muted-foreground">{fmtDateTime(a.at)}</span>
                    </li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="mb-1 text-sm font-semibold">History</h3>
              {data.history.length === 0 ? (
                <p className="text-sm text-muted-foreground">No changes since it was first recorded.</p>
              ) : (
                <ol className="relative space-y-3 border-l pl-4">
                  {data.history.map((c) => (
                    <li key={c.id}>
                      <span className="absolute -left-1.5 mt-1.5 size-3 rounded-full border-2 border-card bg-muted-foreground/40" />
                      <div className="flex items-center gap-2">
                        <ChangeBadge kind={c.kind} />
                        <span className="text-xs text-muted-foreground">{fmtDateTime(c.at)}</span>
                      </div>
                      {c.kind === "changed" && (
                        <div className="mt-1 flex flex-col gap-0.5">
                          {Object.entries(c.changes).map(([f, v]) => {
                            const [a, b] = v as [unknown, unknown]
                            return <FieldDiff key={f} field={f} before={a} after={b} type={types[f]} />
                          })}
                        </div>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </section>
          </>
        )}
      </DialogContent>
    </Dialog>
  )
}
