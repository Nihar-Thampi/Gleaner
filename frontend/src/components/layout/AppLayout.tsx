import { Suspense, useState } from "react"
import { NavLink, Outlet, useLocation } from "react-router-dom"
import { useQuery } from "@tanstack/react-query"
import {
  Bell,
  Bot,
  GitCompareArrows,
  Globe,
  History,
  LayoutDashboard,
  Loader2,
  LogOut,
  Menu,
  Monitor,
  Moon,
  Settings,
  Spline,
  Sun,
  X,
  type LucideIcon,
} from "lucide-react"

import { api } from "@/api/client"
import { useAuth, useMe } from "@/context/AuthContext"
import { ROLE_LABELS, initials } from "@/lib/format"
import { useTheme, type Theme } from "@/lib/theme"
import { cn } from "@/lib/utils"
import type { AIStatus, Role } from "@/types"
import { Avatar, AvatarFallback } from "@/components/ui/avatar"
import { Badge } from "@/components/ui/badge"
import { Button } from "@/components/ui/button"
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu"

interface NavItem {
  to: string
  label: string
  icon: LucideIcon
  roles?: Role[]
  badge?: "alerts"
}

const NAV: NavItem[] = [
  { to: "/dashboard", label: "Dashboard", icon: LayoutDashboard },
  { to: "/scrapers", label: "Scrapers", icon: Spline },
  { to: "/runs", label: "Runs", icon: History },
  { to: "/changes", label: "Changes", icon: GitCompareArrows },
  { to: "/alerts", label: "Alerts", icon: Bell, badge: "alerts" },
  { to: "/domains", label: "Domains & compliance", icon: Globe },
  { to: "/ai-activity", label: "AI activity", icon: Bot, roles: ["admin"] },
  { to: "/settings", label: "Settings", icon: Settings, roles: ["admin"] },
]

export function Logo({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <rect width="32" height="32" rx="7" fill="oklch(0.28 0.03 150)" />
      <g className="fill-grain">
        <ellipse cx="16" cy="9" rx="2.6" ry="4.2" />
        <ellipse cx="11.2" cy="13.5" rx="2.4" ry="3.8" transform="rotate(-35 11.2 13.5)" />
        <ellipse cx="20.8" cy="13.5" rx="2.4" ry="3.8" transform="rotate(35 20.8 13.5)" />
        <ellipse cx="11.6" cy="19.5" rx="2.3" ry="3.6" transform="rotate(-35 11.6 19.5)" />
        <ellipse cx="20.4" cy="19.5" rx="2.3" ry="3.6" transform="rotate(35 20.4 19.5)" />
        <rect x="15.1" y="12" width="1.8" height="15" rx="0.9" />
      </g>
    </svg>
  )
}

const THEME_ICON: Record<Theme, LucideIcon> = { light: Sun, dark: Moon, system: Monitor }

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  const next: Theme = theme === "light" ? "dark" : theme === "dark" ? "system" : "light"
  const Icon = THEME_ICON[theme]
  return (
    <Button variant="ghost" size="icon" onClick={() => setTheme(next)} title={`Theme: ${theme} (click for ${next})`}>
      <Icon />
    </Button>
  )
}

function AiStatusBadge() {
  const { data } = useQuery({
    queryKey: ["ai-status"],
    queryFn: async () => (await api.get<AIStatus>("/ai/status")).data,
    staleTime: Infinity,
  })
  if (!data) return null
  return (
    <Badge
      variant="outline"
      className="hidden gap-1.5 font-normal sm:inline-flex"
      title={data.is_demo ? "No local model available: AI features use offline rules. Start Ollama and download the model." : `Local model: ${data.model}`}
    >
      <span className={cn("size-1.5 rounded-full", data.is_demo ? "bg-warning" : "bg-success")} />
      {data.is_demo ? "AI: demo mode" : "AI: local model"}
    </Badge>
  )
}

export function useUnreadAlerts() {
  return useQuery({
    queryKey: ["alerts", "unread-count"],
    queryFn: async () => (await api.get<{ unread: number }>("/alerts", { params: { unread: true, limit: 1 } })).data.unread,
    refetchInterval: 30_000,
  })
}

export function AppLayout() {
  const me = useMe()
  const { logout } = useAuth()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const { data: unread } = useUnreadAlerts()
  const nav = NAV.filter((n) => !n.roles || n.roles.includes(me.user.role))

  const sidebar = (
    <nav className="flex-1 space-y-1 p-3">
      {nav.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          onClick={() => setMobileOpen(false)}
          className={({ isActive }) =>
            cn(
              "relative flex min-h-9 items-center gap-2.5 rounded-md px-3 text-sm font-medium transition-colors focus-visible:outline-2 focus-visible:outline-ring",
              isActive || location.pathname.startsWith(item.to + "/")
                ? "bg-accent text-foreground before:absolute before:inset-y-1.5 before:left-0 before:w-[3px] before:rounded-full before:bg-changed"
                : "text-muted-foreground hover:bg-accent/70 hover:text-foreground"
            )
          }
        >
          <item.icon className="size-4" />
          <span className="flex-1">{item.label}</span>
          {item.badge === "alerts" && !!unread && (
            <span className="rounded-full bg-destructive px-1.5 text-[11px] font-semibold leading-5 text-white tabular-nums">
              {unread > 99 ? "99+" : unread}
            </span>
          )}
        </NavLink>
      ))}
    </nav>
  )

  const brand = (
    <div className="flex items-center gap-2.5">
      <Logo className="size-7" />
      <div className="min-w-0 leading-tight">
        <div className="text-sm font-semibold">Gleaner</div>
        <div className="truncate text-xs text-muted-foreground">{me.workspace.name}</div>
      </div>
    </div>
  )

  return (
    <div className="flex h-dvh w-full overflow-hidden bg-background">
      <aside className="hidden w-60 shrink-0 flex-col border-r bg-background md:flex">
        <div className="flex h-14 items-center border-b px-4">{brand}</div>
        {sidebar}
        <p className="border-t p-4 text-xs leading-relaxed text-muted-foreground">
          Approved sites only. robots.txt and rate limits always apply.
        </p>
      </aside>

      {mobileOpen && (
        <div className="fixed inset-0 z-40 md:hidden">
          <div className="absolute inset-0 bg-black/40" onClick={() => setMobileOpen(false)} />
          <aside className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col overscroll-contain border-r bg-background">
            <div className="flex h-14 items-center justify-between border-b px-4">
              {brand}
              <Button variant="ghost" size="icon" onClick={() => setMobileOpen(false)} aria-label="Close menu">
                <X />
              </Button>
            </div>
            {sidebar}
          </aside>
        </div>
      )}

      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex h-14 shrink-0 items-center gap-2 border-b bg-background px-4 sm:px-6">
          <Button variant="ghost" size="icon" className="md:hidden" onClick={() => setMobileOpen(true)} aria-label="Open menu">
            <Menu />
          </Button>
          <div className="ml-auto flex items-center gap-1.5">
            <AiStatusBadge />
            <ThemeToggle />
            <DropdownMenu>
              <DropdownMenuTrigger className="flex items-center gap-2 rounded-md p-1 pr-2 text-left hover:bg-accent">
                <Avatar className="size-8">
                  <AvatarFallback className="text-xs">{initials(me.user.full_name)}</AvatarFallback>
                </Avatar>
                <div className="hidden leading-tight sm:block">
                  <div className="text-sm font-medium">{me.user.full_name}</div>
                  <div className="text-xs text-muted-foreground">{ROLE_LABELS[me.user.role]}</div>
                </div>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-60">
                <DropdownMenuLabel className="font-normal">
                  <div className="text-sm font-medium">{me.user.email}</div>
                  <div className="text-xs text-muted-foreground">
                    {me.workspace.name} · {ROLE_LABELS[me.user.role]}
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout}>
                  <LogOut className="size-4" /> Sign out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <main className="flex-1 overflow-y-auto">
          <div className="mx-auto max-w-7xl p-4 sm:p-6">
            <Suspense fallback={<Loader2 className="mx-auto mt-24 animate-spin text-muted-foreground" />}>
              <Outlet />
            </Suspense>
          </div>
        </main>
      </div>
    </div>
  )
}
