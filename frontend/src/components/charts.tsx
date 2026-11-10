/**
 * Charts. Colors come from the validated reference palette (index.css --chart-*): blue and
 * orange for the two main series, a neutral gray for "removed" (an absence, so it recedes),
 * and the reserved red only for failures, always next to a legend and a table view.
 */
import type { ReactNode } from "react"
import {
  Bar,
  BarChart,
  CartesianGrid,
  LabelList,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  type TooltipContentProps,
  type TooltipValueType,
} from "recharts"
import { format, parseISO } from "date-fns"

import { fmtValue } from "@/lib/format"
import type { FieldType } from "@/types"

type TipProps = TooltipContentProps<TooltipValueType, string | number>

const AXIS = { stroke: "var(--chart-axis)", tick: { fill: "var(--chart-muted)", fontSize: 12 }, tickLine: false }
const dayLabel = (d: string) => format(parseISO(d), "d MMM")

function TooltipBox({ title, rows }: { title: ReactNode; rows: { color: string; label: string; value: ReactNode }[] }) {
  return (
    <div className="min-w-36 rounded-md border bg-popover px-3 py-2 text-xs text-popover-foreground shadow-md">
      <div className="mb-1 font-medium">{title}</div>
      {rows.map((r) => (
        <div key={r.label} className="flex items-center justify-between gap-4">
          <span className="inline-flex items-center gap-1.5 text-muted-foreground">
            <span className="size-2 rounded-sm" style={{ background: r.color }} />
            {r.label}
          </span>
          <span className="font-medium tabular-nums">{r.value}</span>
        </div>
      ))}
    </div>
  )
}

export interface Series {
  key: string
  label: string
  color: string
}

/** Daily stacked bars with a 2px surface gap between segments and a rounded top. */
export function StackedDays({ data, series, height = 220 }: { data: Record<string, number | string>[]; series: Series[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 8, right: 4, bottom: 0, left: -16 }} barCategoryGap="22%">
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis dataKey="date" tickFormatter={dayLabel} {...AXIS} interval="preserveStartEnd" minTickGap={20} />
        <YAxis allowDecimals={false} {...AXIS} axisLine={false} width={40} />
        <Tooltip
          cursor={{ fill: "var(--accent)", opacity: 0.5 }}
          content={({ active, payload, label }: TipProps) =>
            active && payload?.length ? (
              <TooltipBox
                title={format(parseISO(String(label)), "EEE d MMM")}
                rows={series.map((s) => ({ color: s.color, label: s.label, value: payload[0].payload[s.key] }))}
              />
            ) : null
          }
        />
        {series.map((s, i) => (
          <Bar
            key={s.key}
            dataKey={s.key}
            stackId="a"
            fill={s.color}
            stroke="var(--chart-surface)"
            strokeWidth={2}
            maxBarSize={22}
            radius={i === series.length - 1 ? [4, 4, 0, 0] : undefined}
          />
        ))}
      </BarChart>
    </ResponsiveContainer>
  )
}

export function HBarChart({ data, valueLabel }: { data: { label: string; value: number }[]; valueLabel: string }) {
  const height = Math.max(100, data.length * 34 + 16)
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout="vertical" margin={{ top: 0, right: 48, bottom: 0, left: 0 }} barCategoryGap={8}>
        <XAxis type="number" hide allowDecimals={false} />
        <YAxis type="category" dataKey="label" width={170} {...AXIS} axisLine={false} />
        <Tooltip
          cursor={{ fill: "var(--accent)", opacity: 0.5 }}
          content={({ active, payload }: TipProps) =>
            active && payload?.length ? (
              <TooltipBox title={payload[0].payload.label} rows={[{ color: "var(--chart-1)", label: valueLabel, value: payload[0].value }]} />
            ) : null
          }
        />
        <Bar dataKey="value" fill="var(--chart-1)" radius={[0, 4, 4, 0]} maxBarSize={18}>
          <LabelList dataKey="value" position="right" fontSize={12} fill="var(--foreground)" />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  )
}

/** One numeric field of one item over time (e.g. price history), as a step line. */
export function ValueHistoryChart({ points, field, type }: { points: { at: string; value: number }[]; field: string; type: FieldType }) {
  const data = points.map((p) => ({ t: new Date(p.at).getTime(), value: p.value }))
  const last = data[data.length - 1]
  return (
    <ResponsiveContainer width="100%" height={200}>
      <LineChart data={data} margin={{ top: 12, right: 70, bottom: 0, left: -4 }}>
        <CartesianGrid vertical={false} stroke="var(--chart-grid)" />
        <XAxis
          dataKey="t"
          type="number"
          scale="time"
          domain={["dataMin", "dataMax"]}
          tickFormatter={(t) => format(new Date(t), "d MMM")}
          {...AXIS}
          minTickGap={24}
        />
        <YAxis {...AXIS} axisLine={false} width={56} domain={["auto", "auto"]} tickFormatter={(v) => fmtValue(v, type)} />
        <Tooltip
          cursor={{ stroke: "var(--chart-axis)" }}
          content={({ active, payload }: TipProps) =>
            active && payload?.length ? (
              <TooltipBox
                title={format(new Date(Number(payload[0].payload.t)), "d MMM yyyy, HH:mm")}
                rows={[{ color: "var(--chart-1)", label: field, value: fmtValue(payload[0].value, type) }]}
              />
            ) : null
          }
        />
        <Line
          type="stepAfter"
          dataKey="value"
          stroke="var(--chart-1)"
          strokeWidth={2}
          dot={data.length < 20 ? { r: 3, fill: "var(--chart-1)", stroke: "var(--chart-surface)", strokeWidth: 2 } : false}
          activeDot={{ r: 4, stroke: "var(--chart-surface)", strokeWidth: 2 }}
          isAnimationActive={false}
        >
          <LabelList
            dataKey="value"
            content={({ x, y, index }) =>
              index === data.length - 1 ? (
                <text x={Number(x) + 8} y={Number(y) + 4} fontSize={12} fill="var(--foreground)">
                  {fmtValue(last?.value, type)}
                </text>
              ) : null
            }
          />
        </Line>
      </LineChart>
    </ResponsiveContainer>
  )
}

export function MiniTable({ head, rows }: { head: string[]; rows: (string | number)[][] }) {
  return (
    <div className="max-h-72 overflow-y-auto">
      <table className="w-full text-sm">
        <thead className="sticky top-0 bg-card">
          <tr className="border-b text-left text-xs text-muted-foreground">
            {head.map((h, i) => (
              <th key={h} className={i ? "py-1.5 text-right font-medium" : "py-1.5 font-medium"}>
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r, ri) => (
            <tr key={ri} className="border-b last:border-0">
              {r.map((c, i) => (
                <td key={i} className={i ? "py-1.5 text-right tabular-nums" : "py-1.5"}>
                  {c}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
