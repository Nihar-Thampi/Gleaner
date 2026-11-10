import { useState } from "react"
import { Link, useNavigate } from "react-router-dom"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2 } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { ChangeBadge, EmptyState, FieldDiff, RunStatusBadge } from "@/components/common"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { ALERT_KIND_LABELS, CHANGE_LABELS, fmtAgo, fmtDateTime, fmtDuration, fmtNumber } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { AlertKind, Change, Column, RunBrief } from "@/types"

const FURROW: Record<Change["kind"], { mark: string; bar: string; sign: string }> = {
  new: { mark: "+", bar: "bg-new", sign: "text-new-ink" },
  returned: { mark: "+", bar: "bg-new", sign: "text-new-ink" },
  changed: { mark: "~", bar: "bg-changed", sign: "text-changed-ink" },
  removed: { mark: "−", bar: "bg-removed", sign: "text-removed-ink" },
}

export function ChangesList({
  changes,
  showScraper,
  onOpenItem,
}: {
  changes: Change[]
  showScraper?: boolean
  onOpenItem?: (c: Change) => void
}) {
  if (!changes.length) return <EmptyState title="No changes">Changes are recorded from a scraper's second run on.</EmptyState>
  return (
    <ul className="divide-y">
      {changes.map((c) => (
        <li key={c.id} className="relative flex flex-wrap items-start gap-x-3 gap-y-1 py-3 pl-9">
          {/* The furrow: a gutter in the change's colour with its diff sign, like a diff view. */}
          <span
            aria-hidden="true"
            className={cn(
              "absolute inset-y-2 left-0 w-[3px] rounded-full",
              FURROW[c.kind].bar
            )}
          />
          <span aria-hidden="true" className={cn("absolute left-3 top-3 font-mono text-sm font-medium leading-6", FURROW[c.kind].sign)}>
            {FURROW[c.kind].mark}
          </span>
          {/* On phones the furrow's sign and colour carry the kind; the badge returns from sm up. */}
          <div className="hidden w-24 shrink-0 pt-0.5 sm:block">
            <ChangeBadge kind={c.kind} />
          </div>
          <span className="sr-only sm:hidden">{CHANGE_LABELS[c.kind]}:</span>
          <div className="min-w-0 flex-1">
            {onOpenItem ? (
              <button type="button" className="text-left font-medium underline-offset-4 hover:underline" onClick={() => onOpenItem(c)}>
                {c.item.label}
              </button>
            ) : (
              <Link to={`/scrapers/${c.scraper_id}?tab=data&item=${c.item.id}`} className="font-medium underline-offset-4 hover:underline">
                {c.item.label}
              </Link>
            )}
            {showScraper && <div className="text-xs text-muted-foreground">{c.scraper_name}</div>}
            {c.kind === "changed" && (
              <div className="mt-1 flex flex-col gap-0.5">
                {Object.entries(c.changes).map(([field, v]) => {
                  const [a, b] = v as [unknown, unknown]
                  return <FieldDiff key={field} field={field} before={a} after={b} />
                })}
              </div>
            )}
          </div>
          <span className="text-xs text-muted-foreground" title={fmtDateTime(c.at)}>
            {fmtAgo(c.at)}
          </span>
        </li>
      ))}
    </ul>
  )
}

export function RunsTable({ runs, showScraper }: { runs: RunBrief[]; showScraper?: boolean }) {
  const navigate = useNavigate()
  if (!runs.length) return <EmptyState title="No runs yet" />
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b text-left text-xs text-muted-foreground">
            <th className="py-2 pr-3 font-medium">Run</th>
            <th className="py-2 pr-3 font-medium">Status</th>
            <th className="py-2 pr-3 text-right font-medium">Items</th>
            <th className="py-2 pr-3 text-right font-medium">New</th>
            <th className="py-2 pr-3 text-right font-medium">Changed</th>
            <th className="py-2 pr-3 text-right font-medium">Removed</th>
            <th className="py-2 pr-3 text-right font-medium">Pages</th>
            <th className="py-2 pr-3 text-right font-medium">Took</th>
            <th className="py-2 text-right font-medium">Started</th>
          </tr>
        </thead>
        <tbody>
          {runs.map((r) => (
            <tr key={r.id} className="cursor-pointer border-b last:border-0 hover:bg-accent/40" onClick={() => navigate(`/runs/${r.id}`)}>
              <td className="py-2 pr-3">
                {showScraper && <div className="font-medium">{r.scraper_name}</div>}
                <div className={showScraper ? "text-xs text-muted-foreground" : "font-medium"}>
                  #{r.number} · {r.trigger}
                </div>
              </td>
              <td className="py-2 pr-3">
                <div className="flex items-center gap-1.5">
                  <RunStatusBadge status={r.status} />
                  {r.anomaly_count > 0 && <span className="text-xs text-warning">{r.anomaly_count} flag{r.anomaly_count > 1 ? "s" : ""}</span>}
                </div>
              </td>
              <td className="py-2 pr-3 text-right tabular-nums">{fmtNumber(r.items_extracted)}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.items_new || "—"}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.items_changed || "—"}</td>
              <td className="py-2 pr-3 text-right tabular-nums">{r.items_removed || "—"}</td>
              <td className="py-2 pr-3 text-right tabular-nums">
                {r.pages_fetched}
                {r.pages_failed > 0 && <span className="text-destructive"> ({r.pages_failed} failed)</span>}
              </td>
              <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">{fmtDuration(r.duration_ms)}</td>
              <td className="py-2 text-right text-xs text-muted-foreground" title={fmtDateTime(r.created_at)}>
                {fmtAgo(r.created_at)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

/** Create an alert rule for one scraper. */
export function RuleDialog({ scraperId, columns, onClose }: { scraperId: string; columns: Column[]; onClose: () => void }) {
  const qc = useQueryClient()
  const numeric = columns.filter((c) => ["number", "integer", "price"].includes(c.type) && !c.multiple)
  const [kind, setKind] = useState<AlertKind>("field_change")
  const [field, setField] = useState(numeric[0]?.name ?? columns[0]?.name ?? "")
  const [direction, setDirection] = useState<"any" | "up" | "down">("down")
  const [minPercent, setMinPercent] = useState(10)
  const [contains, setContains] = useState("")
  const [name, setName] = useState("")

  const autoName =
    kind === "field_change"
      ? `${field} ${direction === "down" ? "drops" : direction === "up" ? "rises" : "changes"}${minPercent ? ` ${minPercent}%+` : ""}`
      : kind === "new_item" && contains
        ? `New items with “${contains}”`
        : ALERT_KIND_LABELS[kind]

  const create = useMutation({
    mutationFn: async () => {
      const params =
        kind === "field_change"
          ? { field, direction, min_percent: minPercent }
          : kind === "new_item" && contains
            ? { field, contains }
            : {}
      return (await api.post(`/scrapers/${scraperId}/alert-rules`, { name: name || autoName, kind, params })).data
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["rules"] })
      toast.success("Alert rule added")
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>New alert rule</DialogTitle>
          <DialogDescription>Alerts show up in Gleaner and are sent to any webhook subscribed to “alert fired”.</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>Alert me when</Label>
            <Select value={kind} onValueChange={(v) => setKind(v as AlertKind)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ALERT_KIND_LABELS) as AlertKind[]).map((k) => (
                  <SelectItem key={k} value={k}>
                    {ALERT_KIND_LABELS[k]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {(kind === "field_change" || kind === "new_item") && (
            <div className="space-y-1.5">
              <Label>Field</Label>
              <Select value={field} onValueChange={setField}>
                <SelectTrigger>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {(kind === "field_change" ? columns : columns.filter((c) => c.type === "string")).map((c) => (
                    <SelectItem key={c.name} value={c.name}>
                      {c.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {kind === "field_change" && (
            <div className="grid grid-cols-2 gap-3">
              <div className="space-y-1.5">
                <Label>Direction</Label>
                <Select value={direction} onValueChange={(v) => setDirection(v as "any" | "up" | "down")}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="down">Goes down</SelectItem>
                    <SelectItem value="up">Goes up</SelectItem>
                    <SelectItem value="any">Any change</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-1.5">
                <Label>By at least (%)</Label>
                <Input type="number" min={0} value={minPercent} onChange={(e) => setMinPercent(Number(e.target.value))} />
              </div>
            </div>
          )}
          {kind === "new_item" && (
            <div className="space-y-1.5">
              <Label>Only if it contains (optional)</Label>
              <Input value={contains} onChange={(e) => setContains(e.target.value)} placeholder="e.g. tent" />
            </div>
          )}
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={name} onChange={(e) => setName(e.target.value)} placeholder={autoName} />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending}>
            {create.isPending && <Loader2 className="animate-spin" />} Add rule
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
