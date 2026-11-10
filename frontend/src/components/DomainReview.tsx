import { useState } from "react"
import { useMutation, useQueryClient } from "@tanstack/react-query"
import { Loader2, ShieldCheck } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { Button } from "@/components/ui/button"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/context/AuthContext"
import type { Domain } from "@/types"

export const BASIS_EXAMPLES = [
  "Our own website.",
  "Written permission from the site owner (email on file).",
  "Public sandbox built for practising web scraping.",
  "Public, non-personal data; the terms don't prohibit automated access, and robots.txt is honoured.",
]

/**
 * Add a domain to the review list. Admins approve it in the same step; editors send it for
 * review. Either way, the reason scraping the site is acceptable is recorded.
 */
export function DomainReviewDialog({
  open,
  onOpenChange,
  url,
  existing,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  url: string
  existing?: Domain
}) {
  const { isAdmin } = useAuth()
  const qc = useQueryClient()
  const [basis, setBasis] = useState(existing?.basis ?? "")
  const [rpm, setRpm] = useState(existing?.requests_per_minute ?? 30)

  const save = useMutation({
    mutationFn: async () => {
      if (existing) {
        return (await api.patch<Domain>(`/domains/${existing.id}`, { status: "approved", basis, requests_per_minute: rpm })).data
      }
      return (await api.post<Domain>("/domains", { url, basis, requests_per_minute: rpm, approve: isAdmin })).data
    },
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["domains"] })
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      toast.success(d.status === "approved" ? `${d.host} approved` : `${d.host} sent to an admin for review`)
      onOpenChange(false)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  let host = url
  try {
    host = new URL(url.includes("://") ? url : `https://${url}`).host
  } catch {
    /* keep what was typed */
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{isAdmin ? `Approve ${host}` : `Request approval for ${host}`}</DialogTitle>
          <DialogDescription>
            Gleaner only fetches from sites an admin has reviewed. Check the site's terms of use first, and don't collect
            personal data without a lawful basis.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label htmlFor="basis">Why is scraping this site acceptable?</Label>
            <Textarea id="basis" rows={3} value={basis} onChange={(e) => setBasis(e.target.value)} placeholder="e.g. written permission from the site owner" />
            <div className="flex flex-wrap gap-1.5">
              {BASIS_EXAMPLES.map((b) => (
                <button key={b} type="button" className="rounded-full border px-2 py-0.5 text-xs text-muted-foreground hover:bg-accent" onClick={() => setBasis(b)}>
                  {b.split(";")[0].replace(/\.$/, "")}
                </button>
              ))}
            </div>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="rpm">Maximum requests per minute</Label>
            <Input id="rpm" type="number" min={1} max={600} value={rpm} onChange={(e) => setRpm(Number(e.target.value))} className="w-32" />
            <p className="text-xs text-muted-foreground">If the site's robots.txt sets a slower Crawl-delay, that wins.</p>
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button onClick={() => save.mutate()} disabled={save.isPending || (isAdmin && !basis.trim())}>
            {save.isPending ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
            {isAdmin ? "Approve domain" : "Send for review"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
