import axios, { AxiosError } from "axios"

const TOKEN_KEY = "gleaner-token"

export const storage = {
  get(key: string): string | null {
    try {
      return localStorage.getItem(key)
    } catch {
      return null
    }
  },
  set(key: string, value: string | null) {
    try {
      if (value === null) localStorage.removeItem(key)
      else localStorage.setItem(key, value)
    } catch {
      /* storage unavailable: state stays in memory */
    }
  },
}

export const getToken = () => storage.get(TOKEN_KEY)
export const setToken = (token: string | null) => storage.set(TOKEN_KEY, token)

export const api = axios.create({ baseURL: "/api" })

api.interceptors.request.use((config) => {
  const token = getToken()
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

api.interceptors.response.use(
  (res) => res,
  (err: AxiosError<{ detail?: unknown }>) => {
    if (err.response?.status === 401 && getToken() && !err.config?.url?.includes("/auth/login")) {
      setToken(null)
      window.dispatchEvent(new Event("gleaner:logout"))
    }
    return Promise.reject(err)
  }
)

/** A readable message from an API error. */
export function errorMessage(err: unknown): string {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail
    if (typeof detail === "string") return detail
    if (detail && typeof detail === "object" && "message" in detail) return String((detail as { message: unknown }).message)
    if (Array.isArray(detail) && detail[0]?.msg) return detail.map((d) => String(d.msg).replace(/^Value error, /, "")).join(" · ")
    if (!err.response) return "Can't reach the server. Is the backend running?"
    return "Something went wrong. Please try again."
  }
  return err instanceof Error ? err.message : "Something went wrong."
}

/** Drop empty values so they don't end up as ?key= in the URL. */
export function params(p: Record<string, string | number | boolean | null | undefined>) {
  return Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== undefined && v !== "" && v !== false))
}

/** The structured `detail` of a 409 from the page fetcher (e.g. a domain that isn't approved). */
export function errorCode(err: unknown): { code?: string; host?: string; status?: string | null } {
  if (err instanceof AxiosError) {
    const detail = err.response?.data?.detail
    if (detail && typeof detail === "object" && !Array.isArray(detail)) return detail as { code?: string; host?: string }
  }
  return {}
}

/** Trigger a file download from an authenticated endpoint. */
export async function download(url: string, query: Record<string, string | number | boolean | null | undefined>) {
  const res = await api.get(url, { params: params(query), responseType: "blob" })
  const disposition = String(res.headers["content-disposition"] ?? "")
  const name = /filename="?([^"]+)"?/.exec(disposition)?.[1] ?? "export"
  const href = URL.createObjectURL(res.data as Blob)
  const a = document.createElement("a")
  a.href = href
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(href), 1000)
}
