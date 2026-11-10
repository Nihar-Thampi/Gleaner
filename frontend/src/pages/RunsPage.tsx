import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"

import { api, params } from "@/api/client"
import { Loading, PageHeader, Pager } from "@/components/common"
import { RunsTable } from "@/components/lists"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { RUN_STATUS_LABELS } from "@/lib/format"
import type { Page, RunBrief, Scraper } from "@/types"

const ALL = "__all__"

export default function RunsPage() {
  const [status, setStatus] = useState(ALL)
  const [scraper, setScraper] = useState(ALL)
  const [offset, setOffset] = useState(0)
  const limit = 50
  const { data: scrapers } = useQuery({ queryKey: ["scrapers"], queryFn: async () => (await api.get<Scraper[]>("/scrapers")).data })
  const { data } = useQuery({
    queryKey: ["runs", status, scraper, offset],
    queryFn: async () =>
      (await api.get<Page<RunBrief>>("/runs", {
        params: params({ status: status === ALL ? null : status, scraper_id: scraper === ALL ? null : scraper, limit, offset }),
      })).data,
    placeholderData: keepPreviousData,
    refetchInterval: (q) => (q.state.data?.items.some((r) => r.status === "running" || r.status === "queued") ? 2500 : 20_000),
  })

  return (
    <div>
      <PageHeader title="Runs" description="Every execution of every scraper, with what it fetched, found and changed." />
      <Card>
        <CardContent className="p-4">
          <div className="mb-3 flex flex-wrap gap-2">
            <Select value={scraper} onValueChange={(v) => (setScraper(v), setOffset(0))}>
              <SelectTrigger className="w-64">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All scrapers</SelectItem>
                {scrapers?.map((s) => (
                  <SelectItem key={s.id} value={s.id}>
                    {s.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <Select value={status} onValueChange={(v) => (setStatus(v), setOffset(0))}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>Any status</SelectItem>
                {Object.entries(RUN_STATUS_LABELS).map(([k, l]) => (
                  <SelectItem key={k} value={k}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {!data ? <Loading /> : <RunsTable runs={data.items} showScraper />}
          {data && <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />}
        </CardContent>
      </Card>
    </div>
  )
}
