import { useState } from "react"
import { useSearchParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import { Copy, KeyRound, Loader2, Plus, Send, Trash2, Webhook as WebhookIcon } from "lucide-react"
import { toast } from "sonner"

import { api, errorMessage } from "@/api/client"
import { EmptyState, Loading, Note, PageHeader } from "@/components/common"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs"
import { useMe } from "@/context/AuthContext"
import { ROLE_LABELS, fmtAgo, fmtDate } from "@/lib/format"
import type { ApiKey, Delivery, Role, User, Webhook, Workspace } from "@/types"

function copy(text: string) {
  navigator.clipboard?.writeText(text).then(() => toast.success("Copied"), () => toast.error("Couldn't copy"))
}

function Secret({ label, value }: { label: string; value: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <div className="flex gap-2">
        <Input readOnly value={value} className="font-mono text-xs" onFocus={(e) => e.target.select()} />
        <Button variant="outline" size="icon" onClick={() => copy(value)} aria-label="Copy">
          <Copy />
        </Button>
      </div>
      <p className="text-xs text-warning">Copy it now. It won't be shown again.</p>
    </div>
  )
}

export default function SettingsPage() {
  const [search, setSearch] = useSearchParams()
  const tab = search.get("tab") ?? "workspace"
  return (
    <div>
      <PageHeader title="Settings" description="Workspace, team access and integrations." />
      <Tabs value={tab} onValueChange={(t) => setSearch({ tab: t }, { replace: true })}>
        <TabsList className="mb-4">
          <TabsTrigger value="workspace">Workspace</TabsTrigger>
          <TabsTrigger value="team">Team</TabsTrigger>
          <TabsTrigger value="api">API keys</TabsTrigger>
          <TabsTrigger value="webhooks">Webhooks</TabsTrigger>
        </TabsList>
        <TabsContent value="workspace">
          <WorkspaceTab />
        </TabsContent>
        <TabsContent value="team">
          <TeamTab />
        </TabsContent>
        <TabsContent value="api">
          <ApiKeysTab />
        </TabsContent>
        <TabsContent value="webhooks">
          <WebhooksTab />
        </TabsContent>
      </Tabs>
    </div>
  )
}

function WorkspaceTab() {
  const qc = useQueryClient()
  const { data: ws } = useQuery({ queryKey: ["workspace"], queryFn: async () => (await api.get<Workspace>("/workspace")).data })
  const [name, setName] = useState<string | null>(null)
  const [email, setEmail] = useState<string | null>(null)
  const save = useMutation({
    mutationFn: async (body: Partial<Workspace>) => (await api.patch<Workspace>("/workspace", body)).data,
    onSuccess: (d) => {
      qc.setQueryData(["workspace"], d)
      toast.success("Saved")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  if (!ws) return <Loading />
  const contact = email ?? ws.contact_email
  return (
    <Card className="max-w-2xl">
      <CardContent className="space-y-5 p-5">
        <div className="space-y-1.5">
          <Label htmlFor="ws-name">Workspace name</Label>
          <Input id="ws-name" value={name ?? ws.name} onChange={(e) => setName(e.target.value)} />
        </div>
        <div className="space-y-1.5">
          <Label htmlFor="ws-email">Crawler contact email</Label>
          <Input id="ws-email" type="email" value={contact} onChange={(e) => setEmail(e.target.value)} />
          <p className="text-xs text-muted-foreground">Sent with every request so site owners can reach you. It appears in the User-Agent as:</p>
          <code className="block rounded bg-muted px-2 py-1.5 text-xs break-all">
            Mozilla/5.0 (compatible; GleanerBot/1.0; +…/bot; contact: {contact})
          </code>
        </div>
        <label className="flex items-start gap-3">
          <Switch checked={ws.ai_run_summaries} onCheckedChange={(v) => save.mutate({ ai_run_summaries: v })} />
          <span className="text-sm">
            <span className="font-medium">AI run summaries</span>
            <span className="block text-muted-foreground">After each run with changes, write a short summary of what changed and what looks off.</span>
          </span>
        </label>
        <Button onClick={() => save.mutate({ name: name ?? ws.name, contact_email: contact })} disabled={save.isPending}>
          {save.isPending && <Loader2 className="animate-spin" />} Save
        </Button>
      </CardContent>
    </Card>
  )
}

function TeamTab() {
  const me = useMe()
  const qc = useQueryClient()
  const [adding, setAdding] = useState(false)
  const { data: users } = useQuery({ queryKey: ["users"], queryFn: async () => (await api.get<User[]>("/users")).data })
  const update = useMutation({
    mutationFn: async ({ id, ...body }: { id: string; role?: Role; is_active?: boolean }) => (await api.patch<User>(`/users/${id}`, body)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["users"] }),
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
        <div>
          <CardTitle className="text-base">Team</CardTitle>
          <p className="text-xs text-muted-foreground">Admins approve domains and manage integrations · editors build and run scrapers · viewers read and export.</p>
        </div>
        <Button size="sm" onClick={() => setAdding(true)}>
          <Plus /> Add person
        </Button>
      </CardHeader>
      <CardContent className="overflow-x-auto p-5 pt-0">
        {!users ? (
          <Loading />
        ) : (
          <table className="w-full text-sm">
            <tbody>
              {users.map((u) => (
                <tr key={u.id} className="border-b last:border-0">
                  <td className="py-2.5">
                    <div className="font-medium">{u.full_name}</div>
                    <div className="text-xs text-muted-foreground">{u.email}</div>
                  </td>
                  <td className="py-2.5">
                    <Select value={u.role} onValueChange={(role) => update.mutate({ id: u.id, role: role as Role })} disabled={u.id === me.user.id}>
                      <SelectTrigger className="h-8 w-32">
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                          <SelectItem key={r} value={r}>
                            {ROLE_LABELS[r]}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </td>
                  <td className="py-2.5 text-xs text-muted-foreground">Joined {fmtDate(u.created_at)}</td>
                  <td className="py-2.5 text-right">
                    {u.id !== me.user.id && (
                      <label className="inline-flex items-center gap-2 text-xs text-muted-foreground">
                        <Switch checked={u.is_active} onCheckedChange={(v) => update.mutate({ id: u.id, is_active: v })} /> Active
                      </label>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </CardContent>
      {adding && <AddUserDialog onClose={() => setAdding(false)} />}
    </Card>
  )
}

function AddUserDialog({ onClose }: { onClose: () => void }) {
  const qc = useQueryClient()
  const [form, setForm] = useState({ full_name: "", email: "", role: "editor" as Role, password: "" })
  const create = useMutation({
    mutationFn: async () => (await api.post("/users", form)).data,
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["users"] })
      toast.success(`${form.full_name} added`)
      onClose()
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Add a person</DialogTitle>
        </DialogHeader>
        <div className="space-y-3">
          <div className="space-y-1.5">
            <Label>Name</Label>
            <Input value={form.full_name} onChange={(e) => setForm({ ...form, full_name: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Email</Label>
            <Input type="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </div>
          <div className="space-y-1.5">
            <Label>Role</Label>
            <Select value={form.role} onValueChange={(r) => setForm({ ...form, role: r as Role })}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(Object.keys(ROLE_LABELS) as Role[]).map((r) => (
                  <SelectItem key={r} value={r}>
                    {ROLE_LABELS[r]}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="space-y-1.5">
            <Label>Initial password</Label>
            <Input type="password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} placeholder="8+ characters" />
          </div>
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button onClick={() => create.mutate()} disabled={create.isPending || !form.full_name || !form.email || form.password.length < 8}>
            {create.isPending && <Loader2 className="animate-spin" />} Add
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function ApiKeysTab() {
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState("")
  const [canRun, setCanRun] = useState(false)
  const [created, setCreated] = useState<ApiKey | null>(null)
  const { data: keys } = useQuery({ queryKey: ["api-keys"], queryFn: async () => (await api.get<ApiKey[]>("/api-keys")).data })
  const create = useMutation({
    mutationFn: async () => (await api.post<ApiKey>("/api-keys", { name, can_trigger_runs: canRun })).data,
    onSuccess: (k) => {
      qc.invalidateQueries({ queryKey: ["api-keys"] })
      setCreated(k)
      setName("")
      setCanRun(false)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const revoke = useMutation({
    mutationFn: async (id: string) => (await api.post(`/api-keys/${id}/revoke`)).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["api-keys"] }),
  })
  const origin = window.location.origin
  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
          <CardTitle className="text-base">API keys</CardTitle>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus /> New key
          </Button>
        </CardHeader>
        <CardContent className="p-5 pt-0">
          {!keys ? (
            <Loading />
          ) : !keys.length ? (
            <EmptyState title="No API keys" icon={KeyRound}>
              Let other systems read your scraped data.
            </EmptyState>
          ) : (
            <ul className="divide-y">
              {keys.map((k) => (
                <li key={k.id} className="flex flex-wrap items-center gap-3 py-2.5">
                  <div className="min-w-0 flex-1">
                    <div className="font-medium">{k.name}</div>
                    <div className="text-xs text-muted-foreground">
                      <span className="font-mono">{k.prefix}…</span> · created {fmtDate(k.created_at)} · {k.last_used_at ? `used ${fmtAgo(k.last_used_at)}` : "never used"}
                    </div>
                  </div>
                  <Badge variant="outline">{k.can_trigger_runs ? "read + run" : "read only"}</Badge>
                  {k.revoked_at ? (
                    <Badge variant="outline" className="text-muted-foreground">
                      Revoked
                    </Badge>
                  ) : (
                    <Button size="sm" variant="ghost" className="text-destructive" onClick={() => revoke.mutate(k.id)}>
                      Revoke
                    </Button>
                  )}
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader className="p-5 pb-2">
          <CardTitle className="text-base">Using the data API</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-5 pt-0 text-sm">
          <p className="text-muted-foreground">Send the key in the X-API-Key header.</p>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{`# list scrapers
curl -H "X-API-Key: $KEY" ${origin}/api/v1/scrapers

# items changed since a date
curl -H "X-API-Key: $KEY" \\
  "${origin}/api/v1/scrapers/<id>/items?updated_since=2026-10-01"

# start a run (keys with run access)
curl -X POST -H "X-API-Key: $KEY" \\
  ${origin}/api/v1/scrapers/<id>/runs`}</pre>
          <a href="/docs" target="_blank" rel="noreferrer" className="text-link hover:underline">
            Full API reference (OpenAPI) →
          </a>
        </CardContent>
      </Card>

      <Dialog open={creating} onOpenChange={(o) => (setCreating(o), !o && setCreated(null))}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{created ? "Your new API key" : "New API key"}</DialogTitle>
            <DialogDescription>Keys are stored hashed. Revoke one any time.</DialogDescription>
          </DialogHeader>
          {created?.key ? (
            <Secret label={created.name} value={created.key} />
          ) : (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Name</Label>
                <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. BI dashboard" />
              </div>
              <label className="flex items-center gap-2 text-sm">
                <Checkbox checked={canRun} onCheckedChange={(v) => setCanRun(!!v)} /> Can also start runs
              </label>
            </div>
          )}
          <DialogFooter>
            {created ? (
              <Button onClick={() => (setCreating(false), setCreated(null))}>Done</Button>
            ) : (
              <Button onClick={() => create.mutate()} disabled={!name.trim() || create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" />} Create key
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  )
}

const EVENT_LABELS: Record<string, string> = { "run.finished": "Run finished", "alert.fired": "Alert fired" }

function WebhooksTab() {
  const qc = useQueryClient()
  const [creating, setCreating] = useState(false)
  const [url, setUrl] = useState("")
  const [events, setEvents] = useState<string[]>(["alert.fired"])
  const [created, setCreated] = useState<Webhook | null>(null)
  const [deliveriesFor, setDeliveriesFor] = useState<string | null>(null)
  const { data } = useQuery({ queryKey: ["webhooks"], queryFn: async () => (await api.get<{ items: Webhook[] }>("/webhooks")).data.items })
  const create = useMutation({
    mutationFn: async () => (await api.post<Webhook>("/webhooks", { url, events })).data,
    onSuccess: (w) => {
      qc.invalidateQueries({ queryKey: ["webhooks"] })
      setCreated(w)
      setUrl("")
    },
    onError: (e) => toast.error(errorMessage(e)),
  })
  const update = useMutation({
    mutationFn: async ({ id, enabled }: { id: string; enabled: boolean }) => (await api.patch(`/webhooks/${id}`, { enabled })).data,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  })
  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/webhooks/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["webhooks"] }),
  })
  const test = useMutation({
    mutationFn: async (id: string) => (await api.post<Delivery>(`/webhooks/${id}/test`)).data,
    onSuccess: (d) => {
      qc.invalidateQueries({ queryKey: ["webhooks"] })
      if (d.ok) toast.success(`Delivered (HTTP ${d.status_code}, ${d.duration_ms} ms)`)
      else toast.error(`Delivery failed: ${d.error}`)
    },
  })

  return (
    <div className="grid gap-4 lg:grid-cols-5">
      <Card className="lg:col-span-3">
        <CardHeader className="flex flex-row items-center justify-between p-5 pb-2">
          <CardTitle className="text-base">Webhooks</CardTitle>
          <Button size="sm" onClick={() => setCreating(true)}>
            <Plus /> New webhook
          </Button>
        </CardHeader>
        <CardContent className="p-5 pt-0">
          {!data ? (
            <Loading />
          ) : !data.length ? (
            <EmptyState title="No webhooks" icon={WebhookIcon}>
              Push run results and alerts to Slack, Zapier, n8n or your own API.
            </EmptyState>
          ) : (
            <ul className="divide-y">
              {data.map((w) => (
                <li key={w.id} className="space-y-1.5 py-3">
                  <div className="flex flex-wrap items-center gap-2">
                    <span className="min-w-0 flex-1 truncate font-mono text-xs">{w.url}</span>
                    <Switch checked={w.enabled} onCheckedChange={(enabled) => update.mutate({ id: w.id, enabled })} aria-label="Enabled" />
                    <Button size="sm" variant="ghost" onClick={() => test.mutate(w.id)} disabled={test.isPending}>
                      <Send /> Test
                    </Button>
                    <Button size="icon" variant="ghost" className="size-8 text-muted-foreground" onClick={() => remove.mutate(w.id)} aria-label="Delete">
                      <Trash2 />
                    </Button>
                  </div>
                  <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                    {w.events.map((e) => (
                      <Badge key={e} variant="outline">
                        {EVENT_LABELS[e] ?? e}
                      </Badge>
                    ))}
                    <span>secret {w.secret_hint}</span>
                    {w.last_delivery && (
                      <button type="button" className="hover:text-foreground" onClick={() => setDeliveriesFor(w.id)}>
                        last delivery {w.last_delivery.ok ? "OK" : "failed"} {fmtAgo(w.last_delivery.at)}
                      </button>
                    )}
                    {!w.enabled && <span>· disabled</span>}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
      <Card className="lg:col-span-2">
        <CardHeader className="p-5 pb-2">
          <CardTitle className="text-base">Verifying deliveries</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 p-5 pt-0 text-sm">
          <p className="text-muted-foreground">
            Each POST has <code>X-Gleaner-Timestamp</code> and <code>X-Gleaner-Signature</code>: an HMAC-SHA256 of
            <code> timestamp.body</code> with the webhook's secret. Reject old timestamps to stop replays.
          </p>
          <pre className="overflow-x-auto rounded-md bg-muted p-3 text-xs">{`import hmac, hashlib

def valid(secret, timestamp, body, signature):
    mac = hmac.new(secret.encode(),
                   timestamp.encode() + b"." + body,
                   hashlib.sha256).hexdigest()
    return hmac.compare_digest("sha256=" + mac, signature)`}</pre>
        </CardContent>
      </Card>

      <Dialog open={creating} onOpenChange={(o) => (setCreating(o), !o && setCreated(null))}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{created ? "Webhook created" : "New webhook"}</DialogTitle>
          </DialogHeader>
          {created?.secret ? (
            <Secret label="Signing secret" value={created.secret} />
          ) : (
            <div className="space-y-3">
              <div className="space-y-1.5">
                <Label>Endpoint URL</Label>
                <Input value={url} onChange={(e) => setUrl(e.target.value)} placeholder="https://hooks.example.com/gleaner" className="font-mono text-xs" />
              </div>
              <div className="space-y-1.5">
                <Label>Send</Label>
                {Object.entries(EVENT_LABELS).map(([e, l]) => (
                  <label key={e} className="flex items-center gap-2 text-sm">
                    <Checkbox
                      checked={events.includes(e)}
                      onCheckedChange={(v) => setEvents((cur) => (v ? [...cur, e] : cur.filter((x) => x !== e)))}
                    />{" "}
                    {l}
                  </label>
                ))}
              </div>
              <Note>Private network addresses are refused, so the crawler can't be used to reach internal systems.</Note>
            </div>
          )}
          <DialogFooter>
            {created ? (
              <Button onClick={() => (setCreating(false), setCreated(null))}>Done</Button>
            ) : (
              <Button onClick={() => create.mutate()} disabled={!url.trim() || !events.length || create.isPending}>
                {create.isPending && <Loader2 className="animate-spin" />} Create
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {deliveriesFor && <DeliveriesDialog hookId={deliveriesFor} onClose={() => setDeliveriesFor(null)} />}
    </div>
  )
}

function DeliveriesDialog({ hookId, onClose }: { hookId: string; onClose: () => void }) {
  const { data } = useQuery({ queryKey: ["deliveries", hookId], queryFn: async () => (await api.get<Delivery[]>(`/webhooks/${hookId}/deliveries`)).data })
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>Recent deliveries</DialogTitle>
        </DialogHeader>
        {!data ? (
          <Loading />
        ) : (
          <ul className="divide-y text-sm">
            {data.map((d) => (
              <li key={d.id} className="flex items-center gap-3 py-2">
                <Badge variant="outline" className={d.ok ? "text-success" : "text-destructive"}>
                  {d.ok ? "OK" : "Failed"}
                </Badge>
                <span className="font-mono text-xs">{d.event}</span>
                <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">{d.error ?? `HTTP ${d.status_code} · ${d.duration_ms} ms`}</span>
                <span className="text-xs text-muted-foreground">{fmtAgo(d.at)}</span>
              </li>
            ))}
          </ul>
        )}
      </DialogContent>
    </Dialog>
  )
}
