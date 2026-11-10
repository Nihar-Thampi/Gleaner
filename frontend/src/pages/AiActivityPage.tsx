import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"
import { CheckCircle2, XCircle } from "lucide-react"

import { api, params } from "@/api/client"
import { AiBadge, Loading, PageHeader, Pager, StatTile } from "@/components/common"
import { Card, CardContent } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { fmtAgo, fmtDateTime, fmtNumber } from "@/lib/format"
import type { AIRequest, Page } from "@/types"

const FEATURES: Record<string, string> = { suggest: "Selector suggestion", repair: "Scraper repair", run_summary: "Run summary" }
const ALL = "__all__"

interface Log extends Page<AIRequest> {
  stats: { requests: number; avg_latency_ms: number; input_tokens: number; output_tokens: number; failures: number }
}

export default function AiActivityPage() {
  const [feature, setFeature] = useState(ALL)
  const [offset, setOffset] = useState(0)
  const [open, setOpen] = useState<string | null>(null)
  const limit = 50
  const { data } = useQuery({
    queryKey: ["ai-requests", feature, offset],
    queryFn: async () => (await api.get<Log>("/ai/requests", { params: params({ feature: feature === ALL ? null : feature, limit, offset }) })).data,
    placeholderData: keepPreviousData,
  })

  return (
    <div className="space-y-4">
      <PageHeader title="AI activity" description="Every AI call: what was sent, what came back, how long it took and which model answered." />
      {data && (
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <StatTile label="Requests" value={fmtNumber(data.stats.requests)} />
          <StatTile label="Average latency" value={`${(data.stats.avg_latency_ms / 1000).toFixed(1)}s`} />
          <StatTile label="Tokens in / out" value={`${fmtNumber(data.stats.input_tokens)} / ${fmtNumber(data.stats.output_tokens)}`} />
          <StatTile label="Fell back to rules" value={data.stats.failures} tone={data.stats.failures ? "warning" : undefined} />
        </div>
      )}
      <Card>
        <CardContent className="p-4">
          <div className="mb-3">
            <Select value={feature} onValueChange={(v) => (setFeature(v), setOffset(0))}>
              <SelectTrigger className="w-52">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All features</SelectItem>
                {Object.entries(FEATURES).map(([k, l]) => (
                  <SelectItem key={k} value={k}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {!data ? (
            <Loading />
          ) : !data.items.length ? (
            <p className="py-8 text-center text-sm text-muted-foreground">No AI requests yet. Try “Suggest selectors” on a new scraper.</p>
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="py-2 pr-3 font-medium">Feature</th>
                    <th className="py-2 pr-3 font-medium">Answered by</th>
                    <th className="py-2 pr-3 font-medium">Who</th>
                    <th className="py-2 pr-3 text-right font-medium">Latency</th>
                    <th className="py-2 pr-3 text-right font-medium">Tokens</th>
                    <th className="py-2 text-right font-medium">When</th>
                  </tr>
                </thead>
                <tbody>
                  {data.items.map((r) => (
                    <tr key={r.id} className="cursor-pointer border-b last:border-0 hover:bg-accent/40" onClick={() => setOpen(r.id)}>
                      <td className="py-2 pr-3">
                        <span className="inline-flex items-center gap-1.5">
                          {r.success ? <CheckCircle2 className="size-3.5 text-success" /> : <XCircle className="size-3.5 text-destructive" />}
                          {FEATURES[r.feature] ?? r.feature}
                        </span>
                      </td>
                      <td className="py-2 pr-3">
                        <AiBadge provider={r.provider} /> <span className="text-xs text-muted-foreground">{r.model}</span>
                      </td>
                      <td className="py-2 pr-3 text-muted-foreground">{r.user_name ?? "automatic"}</td>
                      <td className="py-2 pr-3 text-right tabular-nums">{(r.latency_ms / 1000).toFixed(1)}s</td>
                      <td className="py-2 pr-3 text-right tabular-nums text-muted-foreground">
                        {r.input_tokens != null ? `${fmtNumber(r.input_tokens)} / ${fmtNumber(r.output_tokens ?? 0)}` : "—"}
                      </td>
                      <td className="py-2 text-right text-xs text-muted-foreground" title={fmtDateTime(r.created_at)}>
                        {fmtAgo(r.created_at)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {data && <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />}
        </CardContent>
      </Card>
      {open && <RequestDialog id={open} onClose={() => setOpen(null)} />}
    </div>
  )
}

function RequestDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["ai-request", id], queryFn: async () => (await api.get<AIRequest>(`/ai/requests/${id}`)).data })
  let output = data?.output_text ?? ""
  try {
    output = JSON.stringify(JSON.parse(output), null, 2)
  } catch {
    /* not JSON */
  }
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90dvh] overflow-y-auto sm:max-w-3xl">
        <DialogHeader>
          <DialogTitle>{data ? FEATURES[data.feature] ?? data.feature : "AI request"}</DialogTitle>
          <DialogDescription>{data && `${data.model} · ${fmtDateTime(data.created_at)} · ${(data.latency_ms / 1000).toFixed(1)}s`}</DialogDescription>
        </DialogHeader>
        {!data ? (
          <Loading />
        ) : (
          <div className="space-y-3">
            {data.error && <p className="text-sm text-destructive">The local model call failed, so the rule-based fallback answered: {data.error}</p>}
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Sent</p>
              <pre className="max-h-72 overflow-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">{data.input_text}</pre>
            </div>
            <div>
              <p className="mb-1 text-xs font-medium text-muted-foreground">Returned</p>
              <pre className="max-h-72 overflow-auto rounded-md border bg-muted/40 p-3 text-xs whitespace-pre-wrap">{output}</pre>
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
