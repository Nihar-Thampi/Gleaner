import { useState } from "react"
import { keepPreviousData, useQuery } from "@tanstack/react-query"

import { api, params } from "@/api/client"
import { Loading, PageHeader, Pager } from "@/components/common"
import { ChangesList } from "@/components/lists"
import { Card, CardContent } from "@/components/ui/card"
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select"
import { CHANGE_LABELS, fmtNumber } from "@/lib/format"
import type { Change, Page, Scraper } from "@/types"

const ALL = "__all__"

export default function ChangesPage() {
  const [kind, setKind] = useState(ALL)
  const [scraper, setScraper] = useState(ALL)
  const [offset, setOffset] = useState(0)
  const limit = 50
  const { data: scrapers } = useQuery({ queryKey: ["scrapers"], queryFn: async () => (await api.get<Scraper[]>("/scrapers")).data })
  const { data } = useQuery({
    queryKey: ["changes", "all", kind, scraper, offset],
    queryFn: async () =>
      (await api.get<Page<Change>>("/changes", {
        params: params({ kind: kind === ALL ? null : kind, scraper_id: scraper === ALL ? null : scraper, limit, offset }),
      })).data,
    placeholderData: keepPreviousData,
  })

  return (
    <div>
      <PageHeader title="Changes" description="Every new, changed and removed item across your scrapers, newest first." />
      <Card>
        <CardContent className="p-4">
          <div className="mb-2 flex flex-wrap items-center gap-2">
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
            <Select value={kind} onValueChange={(v) => (setKind(v), setOffset(0))}>
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={ALL}>All kinds</SelectItem>
                {Object.entries(CHANGE_LABELS).map(([k, l]) => (
                  <SelectItem key={k} value={k}>
                    {l}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {data && <span className="text-sm text-muted-foreground">{fmtNumber(data.total)} changes</span>}
          </div>
          {!data ? <Loading /> : <ChangesList changes={data.items} showScraper />}
          {data && <Pager total={data.total} limit={limit} offset={offset} onChange={setOffset} />}
        </CardContent>
      </Card>
    </div>
  )
}
