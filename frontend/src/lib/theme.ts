import { useEffect, useState } from "react"

import { storage } from "@/api/client"

export type Theme = "light" | "dark" | "system"
const KEY = "gleaner-theme"

function apply(theme: Theme) {
  const dark = theme === "dark" || (theme === "system" && window.matchMedia("(prefers-color-scheme: dark)").matches)
  document.documentElement.classList.toggle("dark", dark)
}

export function initTheme() {
  apply((storage.get(KEY) as Theme) || "system")
}

export function useTheme() {
  const [theme, setTheme] = useState<Theme>(() => (storage.get(KEY) as Theme) || "system")

  useEffect(() => {
    apply(theme)
    storage.set(KEY, theme)
    if (theme !== "system") return
    const mq = window.matchMedia("(prefers-color-scheme: dark)")
    const onChange = () => apply("system")
    mq.addEventListener("change", onChange)
    return () => mq.removeEventListener("change", onChange)
  }, [theme])

  return { theme, setTheme }
}
