import { Suspense, lazy, type ReactNode } from "react"
import { Navigate, Route, Routes } from "react-router-dom"
import { Loader2 } from "lucide-react"

import { AppLayout } from "@/components/layout/AppLayout"
import { useAuth } from "@/context/AuthContext"
import type { Role } from "@/types"
import LoginPage from "@/pages/LoginPage"

// Pages load on demand, so the login screen doesn't download the charts.
const AiActivityPage = lazy(() => import("@/pages/AiActivityPage"))
const AlertsPage = lazy(() => import("@/pages/AlertsPage"))
const ChangesPage = lazy(() => import("@/pages/ChangesPage"))
const DashboardPage = lazy(() => import("@/pages/DashboardPage"))
const DomainsPage = lazy(() => import("@/pages/DomainsPage"))
const RunDetailPage = lazy(() => import("@/pages/RunDetailPage"))
const RunsPage = lazy(() => import("@/pages/RunsPage"))
const ScraperDetailPage = lazy(() => import("@/pages/ScraperDetailPage"))
const ScraperEditorPage = lazy(() => import("@/pages/ScraperEditorPage"))
const ScrapersPage = lazy(() => import("@/pages/ScrapersPage"))
const SettingsPage = lazy(() => import("@/pages/SettingsPage"))

const spinner = (
  <div className="flex h-dvh items-center justify-center">
    <Loader2 className="animate-spin text-muted-foreground" />
  </div>
)

function Protected({ children }: { children: ReactNode }) {
  const { me, loading } = useAuth()
  if (loading) return spinner
  if (!me) return <Navigate to="/login" replace />
  return children
}

function RoleGate({ roles, children }: { roles: Role[]; children: ReactNode }) {
  const { hasRole } = useAuth()
  return hasRole(...roles) ? children : <Navigate to="/dashboard" replace />
}

export default function App() {
  return (
    <Suspense fallback={spinner}>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          element={
            <Protected>
              <AppLayout />
            </Protected>
          }
        >
          <Route path="/dashboard" element={<DashboardPage />} />
          <Route path="/scrapers" element={<ScrapersPage />} />
          <Route
            path="/scrapers/new"
            element={
              <RoleGate roles={["admin", "editor"]}>
                <ScraperEditorPage />
              </RoleGate>
            }
          />
          <Route
            path="/scrapers/:id/edit"
            element={
              <RoleGate roles={["admin", "editor"]}>
                <ScraperEditorPage />
              </RoleGate>
            }
          />
          <Route path="/scrapers/:id" element={<ScraperDetailPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:id" element={<RunDetailPage />} />
          <Route path="/changes" element={<ChangesPage />} />
          <Route path="/alerts" element={<AlertsPage />} />
          <Route path="/domains" element={<DomainsPage />} />
          <Route
            path="/ai-activity"
            element={
              <RoleGate roles={["admin"]}>
                <AiActivityPage />
              </RoleGate>
            }
          />
          <Route
            path="/settings"
            element={
              <RoleGate roles={["admin"]}>
                <SettingsPage />
              </RoleGate>
            }
          />
        </Route>
        <Route path="*" element={<Navigate to="/dashboard" replace />} />
      </Routes>
    </Suspense>
  )
}
