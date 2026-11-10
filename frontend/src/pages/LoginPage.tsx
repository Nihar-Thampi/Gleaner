import { useState, type FormEvent } from "react"
import { Navigate } from "react-router-dom"
import { Loader2 } from "lucide-react"

import { errorMessage } from "@/api/client"
import { Logo } from "@/components/layout/AppLayout"
import { Button } from "@/components/ui/button"
import { Card, CardContent } from "@/components/ui/card"
import { Input } from "@/components/ui/input"
import { Label } from "@/components/ui/label"
import { useAuth } from "@/context/AuthContext"

const DEMO_PASSWORD = "Gleaner!2026"
const DEMO_ACCOUNTS = [
  { email: "admin@meridian.demo", who: "Jordan Lee", role: "Admin · approves domains, manages keys and webhooks" },
  { email: "aisha@meridian.demo", who: "Aisha Khan", role: "Editor · builds and runs scrapers" },
  { email: "tom@meridian.demo", who: "Tom Becker", role: "Viewer · reads and exports data" },
]

export default function LoginPage() {
  const { me, login } = useAuth()
  const [email, setEmail] = useState("")
  const [password, setPassword] = useState("")
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  if (me) return <Navigate to="/dashboard" replace />

  async function signIn(e: string, p: string) {
    setBusy(true)
    setError(null)
    try {
      await login(e, p)
    } catch (err) {
      setError(errorMessage(err))
    } finally {
      setBusy(false)
    }
  }

  function onSubmit(ev: FormEvent) {
    ev.preventDefault()
    signIn(email, password)
  }

  return (
    <div className="grid min-h-dvh lg:grid-cols-2">
      <div className="hidden flex-col justify-between bg-[oklch(0.24_0.025_150)] p-10 text-[oklch(0.97_0.01_100)] lg:flex">
        <div className="flex items-center gap-2.5">
          <Logo className="size-8" />
          <span className="text-lg font-semibold">Gleaner</span>
        </div>
        <div className="max-w-md space-y-4">
          <h1 className="text-3xl font-semibold leading-tight">Web data you can trust, collected the right way.</h1>
          <p className="text-white/75">
            Point Gleaner at a website, describe the data you want, and it builds the scraper, runs it on a schedule, tracks
            every change and tells you when something matters.
          </p>
          {/* What Gleaner hands back: a ledger of changes, drawn with the app's own furrow rows. */}
          <ul className="mt-8 divide-y divide-white/10 rounded-lg border border-white/10 font-mono text-[0.8125rem]" aria-label="Example changes">
            {[
              { mark: "~", tone: "bg-[oklch(0.78_0.13_82)]", item: "Three Season 0°C Bag", field: "price", from: "200.99", to: "173.99" },
              { mark: "~", tone: "bg-[oklch(0.78_0.13_82)]", item: "Fastpack 40L", field: "stock", from: "In stock", to: "Only 5 left" },
              { mark: "+", tone: "bg-[oklch(0.7_0.14_148)]", item: "Water Filter Pump", field: "new item", from: "", to: "" },
            ].map((r) => (
              <li key={r.item} className="relative flex items-baseline gap-3 py-2.5 pl-8 pr-3">
                <span aria-hidden="true" className={`absolute inset-y-2 left-0 w-[3px] rounded-full ${r.tone}`} />
                <span aria-hidden="true" className="absolute left-3 text-white/70">
                  {r.mark}
                </span>
                <span className="min-w-0 flex-1 truncate font-sans text-white">{r.item}</span>
                <span className="text-white/60">{r.field}</span>
                {r.from && (
                  <span className="whitespace-nowrap">
                    <span className="text-white/45 line-through">{r.from}</span> <span className="text-white">{r.to}</span>
                  </span>
                )}
              </li>
            ))}
          </ul>
        </div>
        <p className="text-xs text-white/55">Demo build. It only crawls practice sites made for scraping.</p>
      </div>

      <div className="flex items-center justify-center p-6">
        <div className="w-full max-w-sm space-y-6">
          <div className="flex items-center gap-2.5 lg:hidden">
            <Logo className="size-8" />
            <span className="text-lg font-semibold">Gleaner</span>
          </div>
          <div>
            <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
            <p className="mt-1 text-sm text-muted-foreground">Use your work account, or try a demo account below.</p>
          </div>

          <form onSubmit={onSubmit} className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="email">Email</Label>
              <Input id="email" type="email" autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} required />
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="password">Password</Label>
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                required
              />
            </div>
            {error && <p className="text-sm text-destructive">{error}</p>}
            <Button type="submit" className="w-full" disabled={busy}>
              {busy && <Loader2 className="animate-spin" />}
              Sign in
            </Button>
          </form>

          <Card>
            <CardContent className="space-y-1 p-3">
              <p className="px-2 pb-1 text-xs font-medium text-muted-foreground">Demo accounts (one click)</p>
              {DEMO_ACCOUNTS.map((a) => (
                <button
                  key={a.email}
                  type="button"
                  disabled={busy}
                  onClick={() => signIn(a.email, DEMO_PASSWORD)}
                  className="flex w-full flex-col rounded-md px-2 py-1.5 text-left hover:bg-accent disabled:opacity-50"
                >
                  <span className="text-sm font-medium">{a.who}</span>
                  <span className="text-xs text-muted-foreground">{a.role}</span>
                </button>
              ))}
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  )
}
