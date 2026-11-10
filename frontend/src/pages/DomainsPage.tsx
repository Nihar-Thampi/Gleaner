import { useState, type FormEvent } from "react"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Ban, CheckCircle2, FileText, Loader2, Plus, RefreshCw, ShieldCheck, XCircle } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { DomainBadge, Loading, PageHeader } from "@/components/common"
import { DomainReviewDialog } from "@/components/DomainReview"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/context/AuthContext"
import { fmtAgo, fmtDate } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Domain } from "@/types"

interface UrlCheck {
  url: string
  host: string
  domain_status: string | null
  allowed: boolean
  reason: string
  seconds_between_requests?: number
}

const RULES = [
  ["Approved sites only", "Nothing is fetched from a site until an admin approves it and records why that's acceptable."],
  ["robots.txt, always", "Every URL is checked against the site's robots.txt for GleanerBot, including Crawl-delay. There's no override."],
  ["Polite rate limits", "Requests to each site are spaced out, shared across all scrapers. 429 and 5xx responses back off and honour Retry-After."],
  ["Honest identity", "The User-Agent names GleanerBot and links to a page with a contact address and opt-out instructions."],
  ["No evasion", "No logging in to sites, no CAPTCHA solving, no proxy rotation to avoid blocks. Private network addresses are refused."],
]

export default function DomainsPage() {
  const { isAdmin, canEdit } = useAuth()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const [newUrl, setNewUrl] = useState("")
  const [review, setReview] = useState<Domain | null>(null)
  const [robotsFor, setRobotsFor] = useState<string | null>(null)

  const { data: domains } = useQuery({ queryKey: ["domains"], queryFn: async () => (await api.get<Domain[]>("/domains")).data })
  const setStatus = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: string }) => (await api.patch<Domain>(`/domains/${id}`, { status })).data,
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["domains"] })
      toast.success(`${d.host}: ${d.status}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  const order = { pending: 0, approved: 1, blocked: 2 }
  const sorted = [...(domains ?? [])].sort((a, b) => order[a.status] - order[b.status] || a.host.localeCompare(b.host))

  return (
    <div className="space-y-4">
      <PageHeader
        title="Domains & compliance"
        description="The sites this workspace may collect data from, why, and how fast."
        actions={
          canEdit && (
            <Button onClick={() => setAdding(true)}>
              <Plus /> Add domain
            </Button>
          )
        }
      />

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardContent className="overflow-x-auto p-0">
            {!domains ? (
              <Loading />
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b text-left text-xs text-muted-foreground">
                    <th className="px-4 py-2.5 font-medium">Domain</th>
                    <th className="px-4 py-2.5 font-medium">Basis</th>
                    <th className="px-4 py-2.5 font-medium">robots.txt</th>
                    <th className="px-4 py-2.5 text-right font-medium">Rate</th>
                    <th className="px-4 py-2.5" />
                  </tr>
                </thead>
                <tbody>
                  {sorted.map((d) => (
                    <tr key={d.id} className={cn("border-b align-top last:border-0", d.status === "pending" && "bg-warning/5")}>
                      <td className="px-4 py-3">
                        <div className="font-mono text-xs font-medium">{d.host}</div>
                        <div className="mt-1">
                          <DomainBadge status={d.status} />
                        </div>
                        <div className="mt-1 text-xs text-muted-foreground">
                          {d.scraper_count} scraper{d.scraper_count === 1 ? "" : "s"}
                        </div>
                      </td>
                      <td className="max-w-72 px-4 py-3">
                        <p className="text-sm">{d.basis || <span className="text-muted-foreground">Not recorded</span>}</p>
                        {d.reviewed_by && (
                          <p className="mt-1 text-xs text-muted-foreground">
                            {d.status === "blocked" ? "Blocked" : "Approved"} by {d.reviewed_by}, {fmtDate(d.reviewed_at)}
                          </p>
                        )}
                      </td>
                      <td className="max-w-56 px-4 py-3 text-xs">
                        <p>{d.robots_summary}</p>
                        {d.crawl_delay && <p className="mt-0.5 text-muted-foreground">Crawl-delay {d.crawl_delay}s</p>}
                        {d.robots_fetched_at && (
                          <button type="button" className="mt-1 inline-flex items-center gap-1 text-link hover:underline" onClick={() => setRobotsFor(d.id)}>
                            <FileText className="size-3" /> View · checked {fmtAgo(d.robots_fetched_at)}
                          </button>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-right text-xs tabular-nums">{d.requests_per_minute}/min</td>
                      <td className="px-4 py-3">
                        {isAdmin && (
                          <div className="flex justify-end gap-1">
                            {d.status !== "approved" && (
                              <Button size="sm" variant="outline" onClick={() => setReview(d)}>
                                <ShieldCheck /> Approve
                              </Button>
                            )}
                            {d.status !== "blocked" && (
                              <Button size="sm" variant="ghost" className="text-muted-foreground" onClick={() => setStatus.mutate({ id: d.id, status: "blocked" })}>
                                <Ban /> Block
                              </Button>
                            )}
                          </div>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <UrlChecker />
          <Card>
            <CardHeader className="p-5 pb-2">
              <CardTitle className="text-base">How Gleaner crawls</CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-5 pt-0">
              {RULES.map(([title, body]) => (
                <div key={title} className="flex gap-2 text-sm">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" />
                  <div>
                    <p className="font-medium">{title}</p>
                    <p className="text-muted-foreground">{body}</p>
                  </div>
                </div>
              ))}
              <a href="/bot" target="_blank" rel="noreferrer" className="inline-block text-sm text-link hover:underline">
                The crawler's public info page →
              </a>
            </CardContent>
          </Card>
        </div>
      </div>

      <Dialog open={adding} onOpenChange={setAdding}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Add a domain</DialogTitle>
            <DialogDescription>Enter any URL on the site, or just its host name.</DialogDescription>
          </DialogHeader>
          <form
            onSubmit={(e) => {
              e.preventDefault()
              if (newUrl.trim()) setAdding(false)
            }}
            className="space-y-2"
          >
            <Label htmlFor="new-domain">Site</Label>
            <Input id="new-domain" value={newUrl} onChange={(e) => setNewUrl(e.target.value)} placeholder="books.toscrape.com" autoFocus />
            <div className="flex justify-end pt-2">
              <Button type="submit" disabled={!newUrl.trim()}>
                Continue
              </Button>
            </div>
          </form>
        </DialogContent>
      </Dialog>
      {!adding && newUrl.trim() && (
        <DomainReviewDialog open onOpenChange={(o) => !o && setNewUrl("")} url={newUrl.trim()} />
      )}
      {review && <DomainReviewDialog open onOpenChange={(o) => !o && setReview(null)} url={review.host} existing={review} />}
      {robotsFor && <RobotsDialog domainId={robotsFor} onClose={() => setRobotsFor(null)} />}
    </div>
  )
}

function UrlChecker() {
  const [url, setUrl] = useState("")
  const check = useMutation({
    mutationFn: async () => (await api.post<UrlCheck>("/domains/check", { url: url.includes("://") ? url : `https://${url}` })).data,
    onError: (e) => toast.error(errorMessage(e)),
  })
  const submit = (e: FormEvent) => {
    e.preventDefault()
    check.mutate()
  }
  const r = check.data
  return (
    <Card>
      <CardHeader className="p-5 pb-2">
        <CardTitle className="text-base">Would GleanerBot fetch this?</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3 p-5 pt-0">
        <form onSubmit={submit} className="flex gap-2">
          <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://www.scrapethissite.com/lessons/" className="font-mono text-xs" />
          <Button type="submit" variant="outline" disabled={!url.trim() || check.isPending}>
            {check.isPending ? <Loader2 className="animate-spin" /> : "Check"}
          </Button>
        </form>
        {r && (
          <div className={cn("flex items-start gap-2 rounded-md border p-3 text-sm", r.allowed ? "border-success/40 bg-success/5" : "border-destructive/30 bg-destructive/5")}>
            {r.allowed ? <CheckCircle2 className="mt-0.5 size-4 shrink-0 text-success" /> : <XCircle className="mt-0.5 size-4 shrink-0 text-destructive" />}
            <div>
              <p className="font-medium">{r.allowed ? "Allowed" : "Not fetched"}</p>
              <p className="text-muted-foreground">{r.reason}</p>
              {r.allowed && r.seconds_between_requests !== undefined && (
                <p className="mt-1 text-xs text-muted-foreground">At most one request every {r.seconds_between_requests}s to {r.host}.</p>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  )
}

function RobotsDialog({ domainId, onClose }: { domainId: string; onClose: () => void }) {
  const qc = useQueryClient()
  const { canEdit } = useAuth()
  const { data } = useQuery({ queryKey: ["domain", domainId], queryFn: async () => (await api.get<Domain>(`/domains/${domainId}`)).data })
  const refresh = useMutation({
    mutationFn: async () => (await api.post<Domain>(`/domains/${domainId}/robots`)).data,
    onSuccess: (d) => {
      qc.setQueryData(["domain", domainId], d)
      qc.invalidateQueries({ queryKey: ["domains"] })
      toast.success("robots.txt refreshed")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <DialogHeader>
          <DialogTitle className="font-mono text-base">{data?.host}/robots.txt</DialogTitle>
          <DialogDescription>{data ? `${data.robots_summary} Checked ${fmtAgo(data.robots_fetched_at)}.` : "Loading…"}</DialogDescription>
        </DialogHeader>
        <pre className="max-h-80 overflow-auto rounded-md border bg-muted/40 p-3 font-mono text-xs whitespace-pre-wrap">
          {data?.robots_txt || "(no robots.txt: every path is allowed)"}
        </pre>
        {canEdit && (
          <div className="flex justify-end">
            <Button variant="outline" onClick={() => refresh.mutate()} disabled={refresh.isPending}>
              {refresh.isPending ? <Loader2 className="animate-spin" /> : <RefreshCw />} Fetch again
            </Button>
          </div>
        )}
      </DialogContent>
    </Dialog>
  )
}
