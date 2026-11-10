import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from "react"
import { useQueryClient } from "@tanstack/react-query"

import { api, getToken, setToken } from "@/api/client"
import type { Me, Role } from "@/types"

interface AuthState {
  me: Me | null
  loading: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  hasRole: (...roles: Role[]) => boolean
  /** Admins and editors build and run scrapers; viewers read and export. */
  canEdit: boolean
  isAdmin: boolean
}

const AuthContext = createContext<AuthState | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null>(null)
  const [loading, setLoading] = useState(() => !!getToken())
  const queryClient = useQueryClient()

  const logout = useCallback(() => {
    setToken(null)
    setMe(null)
    queryClient.clear()
  }, [queryClient])

  useEffect(() => {
    if (!getToken()) return
    api
      .get<Me>("/auth/me")
      .then((r) => setMe(r.data))
      .catch(() => setToken(null))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => {
    window.addEventListener("gleaner:logout", logout)
    return () => window.removeEventListener("gleaner:logout", logout)
  }, [logout])

  const login = useCallback(
    async (email: string, password: string) => {
      const { data } = await api.post<Me & { token: string }>("/auth/login", { email, password })
      queryClient.clear()
      setToken(data.token)
      setMe({ user: data.user, workspace: data.workspace })
    },
    [queryClient]
  )

  const value = useMemo<AuthState>(() => {
    const role = me?.user.role
    return {
      me,
      loading,
      login,
      logout,
      hasRole: (...roles) => !!role && roles.includes(role),
      canEdit: role === "admin" || role === "editor",
      isAdmin: role === "admin",
    }
  }, [me, loading, login, logout])

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error("useAuth must be used inside AuthProvider")
  return ctx
}

/** For pages behind the login: `me` is always set there. */
export function useMe(): Me {
  const { me } = useAuth()
  if (!me) throw new Error("Not signed in")
  return me
}
