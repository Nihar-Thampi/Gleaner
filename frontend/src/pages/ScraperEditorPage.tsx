import { useEffect, useMemo, useState } from "react"
import { useNavigate, useParams } from "react-router-dom"
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query"
import {
  ChevronDown,
  ChevronRight,
  KeyRound,
  Loader2,
  Plus,
  Save,
  ScanSearch,
  ShieldAlert,
  Trash2,
  WandSparkles,
} from "lucide-react"
import { toast } from "sonner"

import { api, errorCode, errorMessage } from "@/api/client"
import { AiBadge, DomainBadge, ErrorNote, FillBar, Loading, Note, PageHeader, ValueCell } from "@/components/common"
import { DomainReviewDialog } from "@/components/DomainReview"
import { Button } from "@/components/ui/button"
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card"
import { Checkbox } from "@/components/ui/checkbox"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { Switch } from "@/components/ui/switch"
import { Textarea } from "@/components/ui/textarea"
import { useAuth } from "@/context/AuthContext"
import { FIELD_TYPES, FIELD_TYPE_LABELS, SCHEDULES } from "@/lib/format"
import { cn } from "@/lib/utils"
import type { Domain, FieldSpec, PreviewResult, Scraper, ScraperConfig, SuggestResult } from "@/types"

type EditField = FieldSpec & { _id: string }
let nextId = 1
const withId = (f: FieldSpec): EditField => ({ ...f, _id: String(nextId++) })

const blankField = (source: "list" | "detail" = "list"): EditField =>
  withId({ name: "", selector: "", attr: "text", type: "string", source, multiple: false, required: false, regex: null, value_map: null })

const EMPTY_CONFIG: ScraperConfig = {
  item_selector: "",
  fields: [],
  detail_link_selector: null,
  next_page_selector: null,
  max_pages: 10,
  max_items: null,
  render: "static",
  wait_for_selector: null,
  key_fields: [],
}

const ATTR_OPTIONS = ["text", "href", "src", "title", "class", "html", "datetime", "content", "alt"]

function hostOf(url: string): string | null {
  try {
    const u = new URL(url)
    return u.port && !((u.protocol === "http:" && u.port === "80") || (u.protocol === "https:" && u.port === "443")) ? `${u.hostname}:${u.port}` : u.hostname
  } catch {
    return null
  }
}

// ---------------------------------------------------------------------------

export default function ScraperEditorPage() {
  const { id } = useParams()
  const editing = !!id
  const { data: scraper, isLoading } = useQuery({
    queryKey: ["scraper", id],
    queryFn: async () => (await api.get<Scraper>(`/scrapers/${id}`)).data,
    enabled: editing,
  })
  if (editing && (isLoading || !scraper)) return <Loading />
  return <Editor key={scraper?.id ?? "new"} scraper={scraper} />
}

function Editor({ scraper }: { scraper?: Scraper }) {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { isAdmin } = useAuth()

  const [name, setName] = useState(scraper?.name ?? "")
  const [description, setDescription] = useState(scraper?.description ?? "")
  const [urlsText, setUrlsText] = useState((scraper?.start_urls ?? []).join("\n"))
  const [config, setConfig] = useState<ScraperConfig>(scraper?.config ?? EMPTY_CONFIG)
  const [fields, setFields] = useState<EditField[]>(() => (scraper?.config?.fields ?? []).map(withId))
  const [schedule, setSchedule] = useState<number | null>(scraper?.schedule_minutes ?? 1440)
  const [enabled, setEnabled] = useState(scraper?.enabled ?? true)

  const [ask, setAsk] = useState("")
  const [suggestion, setSuggestion] = useState<SuggestResult | null>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewKind, setPreviewKind] = useState<"list" | "detail">("list")
  const [detailUrl, setDetailUrl] = useState<string | null>(null)
  const [blockedHost, setBlockedHost] = useState<string | null>(null)
  const [reviewUrl, setReviewUrl] = useState<string | null>(null)

  const startUrls = useMemo(() => urlsText.split(/\s+/).map((u) => u.trim()).filter(Boolean), [urlsText])
  const firstUrl = startUrls[0] ?? ""
  const host = hostOf(firstUrl)

  const { data: domains } = useQuery({ queryKey: ["domains"], queryFn: async () => (await api.get<Domain[]>("/domains")).data })
  const domain = domains?.find((d) => d.host === host)

  const fullConfig = (): ScraperConfig => ({
    ...config,
    fields: fields.map(({ _id, ...f }) => f),
    key_fields: config.key_fields.filter((k) => fields.some((f) => f.name === k)),
  })

  const onFetchError = (e: unknown) => {
    const code = errorCode(e)
    if (code.code === "domain_not_approved") setBlockedHost(code.host ?? host)
    toast.error(errorMessage(e))
  }

  const suggest = useMutation({
    mutationFn: async (pageKind: "list" | "detail") => {
      const url = pageKind === "detail" ? detailUrl : firstUrl
      return (await api.post<SuggestResult>("/ai/suggest", { url, fields: ask, page_kind: pageKind })).data
    },
    onSuccess: (s, pageKind) => {
      setSuggestion(s)
      if (!s.valid) return
      const suggested = s.config.fields.map((f) => withId({ ...f, source: pageKind }))
      if (pageKind === "detail") {
        setFields((cur) => [...cur.filter((f) => f.source === "list"), ...suggested])
      } else {
        setFields((cur) => [...suggested, ...cur.filter((f) => f.source === "detail")])
        setConfig((c) => ({
          ...c,
          item_selector: s.config.item_selector,
          next_page_selector: s.config.next_page_selector,
          key_fields: s.config.key_fields,
          render: s.render,
        }))
      }
      setPreview({ ...s, rows: s.rows })
      setPreviewKind(pageKind)
      if (!name && pageKind === "list" && host) setName(host.replace(/^www\./, ""))
      toast.success(`Suggested ${suggested.length} fields. Check them in the preview.`)
    },
    onError: onFetchError,
  })

  const runPreview = useMutation({
    mutationFn: async (kind: "list" | "detail") => {
      const url = kind === "detail" ? detailUrl : firstUrl
      return (await api.post<PreviewResult>("/scrapers/preview", { url, config: fullConfig(), page_kind: kind })).data
    },
    onSuccess: (p, kind) => {
      setPreview(p)
      setPreviewKind(kind)
      if (kind === "list" && p.detail_url) setDetailUrl(p.detail_url)
    },
    onError: onFetchError,
  })

  const save = useMutation({
    mutationFn: async () => {
      const body = { name, description, start_urls: startUrls, config: fullConfig(), schedule_minutes: schedule, enabled }
      return scraper
        ? (await api.patch<Scraper>(`/scrapers/${scraper.id}`, body)).data
        : (await api.post<Scraper>("/scrapers", body)).data
    },
    onSuccess: (s) => {
      qc.invalidateQueries({ queryKey: ["scrapers"] })
      qc.invalidateQueries({ queryKey: ["scraper", s.id] })
      toast.success(scraper ? "Scraper saved" : "Scraper created")
      navigate(`/scrapers/${s.id}`)
    },
    onError: (e) => toast.error(errorMessage(e)),
  })

  // A preview's detail link makes the "detail page" tools available.
  useEffect(() => {
    if (preview?.detail_url && previewKind === "list") setDetailUrl(preview.detail_url)
  }, [preview, previewKind])

  const updateField = (fid: string, patch: Partial<FieldSpec>) => setFields((fs) => fs.map((f) => (f._id === fid ? { ...f, ...patch } : f)))
  const toggleKey = (fname: string) =>
    setConfig((c) => ({ ...c, key_fields: c.key_fields.includes(fname) ? c.key_fields.filter((k) => k !== fname) : [...c.key_fields, fname] }))

  const hasDetailFields = fields.some((f) => f.source === "detail")
  const canSave = name.trim() && startUrls.length > 0 && fields.length > 0 && fields.every((f) => f.name)
  const busy = suggest.isPending || runPreview.isPending

  return (
    <div className="space-y-6">
      <PageHeader
        title={scraper ? `Edit ${scraper.name}` : "New scraper"}
        description="Paste a page URL, describe the data you want, check the live preview, then save."
        actions={
          <>
            <Button variant="outline" onClick={() => navigate(scraper ? `/scrapers/${scraper.id}` : "/scrapers")}>
              Cancel
            </Button>
            <Button onClick={() => save.mutate()} disabled={!canSave || save.isPending}>
              {save.isPending ? <Loader2 className="animate-spin" /> : <Save />}
              {scraper ? "Save changes" : "Create scraper"}
            </Button>
          </>
        }
      />

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
        {/* ---------------- left: configuration ---------------- */}
        <div className="space-y-4">
          <Card>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="text-base">1. Where to start</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 p-5 pt-0">
              <div className="space-y-1.5">
                <Label htmlFor="urls">Start URL(s), one per line</Label>
                <Textarea
                  id="urls"
                  rows={2}
                  className="font-mono text-sm"
                  value={urlsText}
                  onChange={(e) => setUrlsText(e.target.value)}
                  placeholder="https://books.toscrape.com/catalogue/category/books/mystery_3/index.html"
                />
                {host && (
                  <div className="flex flex-wrap items-center gap-2 text-sm">
                    <span className="font-mono text-xs text-muted-foreground">{host}</span>
                    <DomainBadge status={domain?.status ?? "unknown"} />
                    {domain?.status !== "approved" && domain?.status !== "blocked" && (isAdmin || !domain) && (
                      <Button variant="link" size="sm" className="h-auto p-0" onClick={() => setReviewUrl(firstUrl)}>
                        {isAdmin ? "Review and approve" : "Request approval"}
                      </Button>
                    )}
                    {domain?.status === "pending" && !isAdmin && <span className="text-xs text-muted-foreground">An admin needs to approve it.</span>}
                  </div>
                )}
                {blockedHost && blockedHost === host && domain?.status !== "approved" && (
                  <Note tone="warning" icon={ShieldAlert}>
                    Nothing is fetched from <span className="font-mono">{blockedHost}</span> until it's an approved domain.
                  </Note>
                )}
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <div className="space-y-1.5">
                  <Label htmlFor="name">Name</Label>
                  <Input id="name" value={name} onChange={(e) => setName(e.target.value)} placeholder="Competitor prices" />
                </div>
                <div className="space-y-1.5">
                  <Label htmlFor="desc">Description</Label>
                  <Input id="desc" value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional" />
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="border-primary/30">
            <CardHeader className="p-5 pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <WandSparkles className="size-4 text-link" /> 2. Describe the data you want
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-3 p-5 pt-0">
              <Textarea
                rows={2}
                value={ask}
                onChange={(e) => setAsk(e.target.value)}
                placeholder="e.g. product name, price, rating, whether it's in stock, link to the product page"
              />
              <div className="flex flex-wrap items-center gap-2">
                <Button onClick={() => suggest.mutate("list")} disabled={!firstUrl || ask.trim().length < 2 || busy}>
                  {suggest.isPending && suggest.variables === "list" ? <Loader2 className="animate-spin" /> : <WandSparkles />}
                  Suggest selectors
                </Button>
                {detailUrl && (
                  <Button variant="outline" onClick={() => suggest.mutate("detail")} disabled={ask.trim().length < 2 || busy}>
                    {suggest.isPending && suggest.variables === "detail" ? <Loader2 className="animate-spin" /> : <WandSparkles />}
                    Suggest from a detail page
                  </Button>
                )}
                <span className="text-xs text-muted-foreground">
                  The AI reads the live page, proposes selectors, then they're tested on the page before you see them.
                </span>
              </div>
              {suggestion && (
                <div className="space-y-2 rounded-md border bg-muted/30 p-3 text-sm">
                  <div className="flex items-center gap-2">
                    <AiBadge provider={suggestion.provider} />
                    {suggestion.attempts === 2 && <span className="text-xs text-muted-foreground">Corrected once after testing on the page</span>}
                  </div>
                  {!suggestion.valid && <ErrorNote>{suggestion.error}</ErrorNote>}
                  <ul className="list-disc space-y-0.5 pl-5 text-muted-foreground">
                    {suggestion.notes.map((n) => (
                      <li key={n}>{n}</li>
                    ))}
                    {suggestion.problems.map((p) => (
                      <li key={p} className="text-warning">
                        {p}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="text-base">3. Items and pages</CardTitle>
            </CardHeader>
            <CardContent className="grid gap-4 p-5 pt-0 sm:grid-cols-2">
              <SelectorInput
                label="Item selector"
                hint="Matches one element per row. Empty = the whole page is one row."
                value={config.item_selector}
                onChange={(v) => setConfig({ ...config, item_selector: v })}
                placeholder="article.product_pod"
              />
              <SelectorInput
                label="Next page link"
                hint="Optional. Followed until it runs out or the page limit."
                value={config.next_page_selector ?? ""}
                onChange={(v) => setConfig({ ...config, next_page_selector: v || null })}
                placeholder="li.next a"
              />
              <div className="space-y-1.5">
                <Label>Page limit</Label>
                <Input type="number" min={1} max={500} value={config.max_pages} onChange={(e) => setConfig({ ...config, max_pages: Number(e.target.value) || 1 })} />
              </div>
              <div className="space-y-1.5">
                <Label>Fetching</Label>
                <Select value={config.render} onValueChange={(v) => setConfig({ ...config, render: v as "static" | "browser" })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="static">Static HTML (fast)</SelectItem>
                    <SelectItem value="browser">Headless browser (for JavaScript sites)</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              {config.render === "browser" && (
                <SelectorInput
                  label="Wait for"
                  hint="Optional: wait until this element appears before reading the page."
                  value={config.wait_for_selector ?? ""}
                  onChange={(v) => setConfig({ ...config, wait_for_selector: v || null })}
                  placeholder="div.quote"
                />
              )}
              <SelectorInput
                label="Detail page link"
                hint="Optional. Opens each item's own page to read more fields."
                value={config.detail_link_selector ?? ""}
                onChange={(v) => setConfig({ ...config, detail_link_selector: v || null })}
                placeholder="h3 a"
              />
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between p-5 pb-3">
              <CardTitle className="text-base">4. Fields</CardTitle>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => setFields((f) => [...f, blankField("list")])}>
                  <Plus /> Field
                </Button>
                {config.detail_link_selector && (
                  <Button variant="outline" size="sm" onClick={() => setFields((f) => [...f, blankField("detail")])}>
                    <Plus /> Detail-page field
                  </Button>
                )}
              </div>
            </CardHeader>
            <CardContent className="space-y-2 p-5 pt-0">
              {fields.length === 0 && (
                <p className="rounded-md border border-dashed p-4 text-center text-sm text-muted-foreground">
                  Use "Suggest selectors" above, or add fields by hand.
                </p>
              )}
              {fields.map((f) => (
                <FieldRow
                  key={f._id}
                  field={f}
                  isKey={config.key_fields.includes(f.name)}
                  fill={previewKind === f.source ? preview?.fill_rates[f.name] : undefined}
                  onChange={(patch) => {
                    if (patch.name !== undefined && config.key_fields.includes(f.name)) {
                      setConfig((c) => ({ ...c, key_fields: c.key_fields.map((k) => (k === f.name ? patch.name! : k)) }))
                    }
                    updateField(f._id, patch)
                  }}
                  onToggleKey={() => toggleKey(f.name)}
                  onRemove={() => setFields((fs) => fs.filter((x) => x._id !== f._id))}
                />
              ))}
              {fields.length > 0 && (
                <p className="flex items-center gap-1.5 pt-1 text-xs text-muted-foreground">
                  <KeyRound className="size-3.5" />
                  Key fields identify an item across runs (usually its URL). Without one, any change looks like a new item.
                </p>
              )}
              {hasDetailFields && !config.detail_link_selector && (
                <ErrorNote>Detail-page fields need a detail page link selector.</ErrorNote>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="p-5 pb-3">
              <CardTitle className="text-base">5. Schedule</CardTitle>
            </CardHeader>
            <CardContent className="flex flex-wrap items-end gap-6 p-5 pt-0">
              <div className="space-y-1.5">
                <Label>Run</Label>
                <Select value={String(schedule)} onValueChange={(v) => setSchedule(v === "null" ? null : Number(v))}>
                  <SelectTrigger className="w-48">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {SCHEDULES.map((s) => (
                      <SelectItem key={String(s.value)} value={String(s.value)}>
                        {s.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <label className="flex items-center gap-2 text-sm">
                <Switch checked={enabled} onCheckedChange={setEnabled} /> Enabled
              </label>
            </CardContent>
          </Card>
        </div>

        {/* ---------------- right: live preview ---------------- */}
        <div className="xl:sticky xl:top-0 xl:self-start">
          <PreviewPanel
            preview={preview}
            kind={previewKind}
            fields={fields.filter((f) => f.source === previewKind)}
            busy={runPreview.isPending}
            canPreview={!!firstUrl && fields.length > 0}
            detailUrl={detailUrl}
            hasDetailFields={hasDetailFields}
            onRun={(k) => runPreview.mutate(k)}
          />
        </div>
      </div>

      {reviewUrl && (
        <DomainReviewDialog
          open
          onOpenChange={(o) => !o && setReviewUrl(null)}
          url={reviewUrl}
          existing={domain && isAdmin ? domain : undefined}
        />
      )}
    </div>
  )
}

function SelectorInput({ label, hint, value, onChange, placeholder }: { label: string; hint?: string; value: string; onChange: (v: string) => void; placeholder?: string }) {
  return (
    <div className="space-y-1.5">
      <Label>{label}</Label>
      <Input className="font-mono text-sm" value={value} onChange={(e) => onChange(e.target.value)} placeholder={placeholder} />
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  )
}

function FieldRow({
  field,
  isKey,
  fill,
  onChange,
  onToggleKey,
  onRemove,
}: {
  field: EditField
  isKey: boolean
  fill?: number
  onChange: (patch: Partial<FieldSpec>) => void
  onToggleKey: () => void
  onRemove: () => void
}) {
  const [open, setOpen] = useState(!!field.regex || !!field.value_map)
  const [mapText, setMapText] = useState(field.value_map ? JSON.stringify(field.value_map) : "")
  return (
    <div className={cn("rounded-md border p-3", field.source === "detail" && "border-dashed bg-muted/20")}>
      <div className="grid grid-cols-12 items-center gap-2">
        <Input
          className="col-span-6 h-8 font-mono text-sm sm:col-span-3"
          value={field.name}
          onChange={(e) => onChange({ name: e.target.value.toLowerCase().replace(/[^a-z0-9_]/g, "_") })}
          placeholder="field_name"
          aria-label="Field name"
        />
        <Input
          className="col-span-6 h-8 font-mono text-sm sm:col-span-4"
          value={field.selector}
          onChange={(e) => onChange({ selector: e.target.value })}
          placeholder="CSS selector"
          aria-label="Selector"
        />
        <Select value={ATTR_OPTIONS.includes(field.attr) ? field.attr : "__custom"} onValueChange={(v) => onChange({ attr: v === "__custom" ? "data-id" : v })}>
          <SelectTrigger className="col-span-4 h-8 sm:col-span-2" aria-label="What to read">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {ATTR_OPTIONS.map((a) => (
              <SelectItem key={a} value={a}>
                {a === "text" ? "text" : a === "html" ? "HTML" : `@${a}`}
              </SelectItem>
            ))}
            <SelectItem value="__custom">other attribute…</SelectItem>
          </SelectContent>
        </Select>
        <Select value={field.type} onValueChange={(v) => onChange({ type: v as FieldSpec["type"] })}>
          <SelectTrigger className="col-span-4 h-8 sm:col-span-2" aria-label="Type">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FIELD_TYPES.map((t) => (
              <SelectItem key={t} value={t}>
                {FIELD_TYPE_LABELS[t]}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <div className="col-span-4 flex items-center justify-end gap-0.5 sm:col-span-1">
          <Button variant="ghost" size="icon" className="size-8" onClick={() => setOpen((o) => !o)} aria-label="More options">
            {open ? <ChevronDown /> : <ChevronRight />}
          </Button>
          <Button variant="ghost" size="icon" className="size-8 text-muted-foreground" onClick={onRemove} aria-label="Remove field">
            <Trash2 />
          </Button>
        </div>
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-muted-foreground">
        {field.source === "detail" && <span className="font-medium text-foreground">From the detail page</span>}
        <label className="flex items-center gap-1.5">
          <Checkbox checked={isKey} onCheckedChange={onToggleKey} disabled={!field.name} /> Key
        </label>
        <label className="flex items-center gap-1.5">
          <Checkbox checked={field.required} onCheckedChange={(v) => onChange({ required: !!v })} /> Required
        </label>
        <label className="flex items-center gap-1.5">
          <Checkbox checked={field.multiple} onCheckedChange={(v) => onChange({ multiple: !!v })} /> All matches (list)
        </label>
        {!ATTR_OPTIONS.includes(field.attr) && (
          <Input className="h-7 w-32 font-mono text-xs" value={field.attr} onChange={(e) => onChange({ attr: e.target.value })} aria-label="Attribute" />
        )}
        {fill !== undefined && (
          <span className="ml-auto">
            <FillBar rate={fill} />
          </span>
        )}
      </div>
      {open && (
        <div className="mt-2 grid gap-2 sm:grid-cols-2">
          <div className="space-y-1">
            <Label className="text-xs">Pattern (regex, first group kept)</Label>
            <Input className="h-8 font-mono text-xs" value={field.regex ?? ""} onChange={(e) => onChange({ regex: e.target.value || null })} placeholder="e.g. (\d+) left" />
          </div>
          <div className="space-y-1">
            <Label className="text-xs">Value map (JSON)</Label>
            <Input
              className="h-8 font-mono text-xs"
              value={mapText}
              onChange={(e) => {
                setMapText(e.target.value)
                try {
                  onChange({ value_map: e.target.value.trim() ? JSON.parse(e.target.value) : null })
                } catch {
                  /* keep typing */
                }
              }}
              placeholder='{"Three": 3}'
            />
          </div>
        </div>
      )}
    </div>
  )
}

function PreviewPanel({
  preview,
  kind,
  fields,
  busy,
  canPreview,
  detailUrl,
  hasDetailFields,
  onRun,
}: {
  preview: PreviewResult | null
  kind: "list" | "detail"
  fields: EditField[]
  busy: boolean
  canPreview: boolean
  detailUrl: string | null
  hasDetailFields: boolean
  onRun: (kind: "list" | "detail") => void
}) {
  return (
    <Card>
      <CardHeader className="flex flex-row flex-wrap items-center justify-between gap-2 p-5 pb-3">
        <div>
          <CardTitle className="text-base">Live preview</CardTitle>
          <p className="mt-0.5 text-xs text-muted-foreground">Runs the current settings on the real page. Nothing is saved.</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" size="sm" onClick={() => onRun("list")} disabled={!canPreview || busy}>
            {busy ? <Loader2 className="animate-spin" /> : <ScanSearch />} Test listing page
          </Button>
          {hasDetailFields && detailUrl && (
            <Button variant="outline" size="sm" onClick={() => onRun("detail")} disabled={busy}>
              Test a detail page
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="space-y-3 p-5 pt-0">
        {!preview ? (
          <p className="rounded-md border border-dashed p-8 text-center text-sm text-muted-foreground">
            Run a test to see the rows this scraper would extract.
          </p>
        ) : (
          <>
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-sm">
              <span>
                <span className="font-semibold tabular-nums">{preview.item_count}</span> {kind === "detail" ? "detail page" : "items on this page"}
              </span>
              {preview.render === "browser" && <span className="text-xs text-muted-foreground">rendered in a headless browser</span>}
              {preview.next_url && (
                <span className="truncate text-xs text-muted-foreground">
                  next page: <span className="font-mono">{preview.next_url.replace(/^https?:\/\//, "")}</span>
                </span>
              )}
            </div>
            {preview.notes?.map((n) => (
              <Note key={n}>{n}</Note>
            ))}
            {preview.item_count === 0 && <ErrorNote>The item selector matched nothing on this page.</ErrorNote>}
            {preview.errors.length > 0 && (
              <Note tone="warning">
                <div className="font-medium">Some values couldn't be read</div>
                <ul className="mt-1 list-disc pl-4 text-xs">
                  {preview.errors.slice(0, 5).map((e) => (
                    <li key={e}>{e}</li>
                  ))}
                </ul>
              </Note>
            )}
            {preview.rows.length > 0 && (
              <div className="max-h-[60vh] overflow-auto rounded-md border">
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-muted/80 backdrop-blur">
                    <tr className="text-left text-xs text-muted-foreground">
                      {fields.map((f) => (
                        <th key={f._id} className="whitespace-nowrap px-3 py-2 font-medium">
                          <div className="font-mono">{f.name || "?"}</div>
                          {preview.fill_rates[f.name] !== undefined && (
                            <div className="mt-1">
                              <FillBar rate={preview.fill_rates[f.name]} />
                            </div>
                          )}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {preview.rows.map((row, i) => (
                      <tr key={i} className="border-t align-top">
                        {fields.map((f) => (
                          <td key={f._id} className="max-w-56 truncate px-3 py-1.5" title={String(row[f.name] ?? "")}>
                            <ValueCell value={row[f.name]} type={f.type} />
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
