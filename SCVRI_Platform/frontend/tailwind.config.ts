import type { Config } from "tailwindcss";

export default {
  darkMode: "class",
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        // ── Brand palette (fixed) ──────────────────────────────
        brand: {
          deep:   "#003135",
          dark:   "#024950",
          copper: "#964734",
          cyan:   "#0FA4AF",
          powder: "#AFDDE5",
        },
        // ── Semantic tokens (CSS-variable-backed, auto-switch with .dark) ──
        page:    "var(--bg-page)",
        card:    "var(--bg-card)",
        sidebar: "var(--bg-sidebar)",
        topbar:  "var(--bg-topbar)",
        surface: "var(--bg-surface)",
        stroke:  "var(--border)",
        ink: {
          DEFAULT: "var(--text)",
          2:       "var(--text-2)",
          3:       "var(--text-3)",
        },
        accent: {
          DEFAULT: "var(--accent)",
          sub:     "var(--accent-sub)",
        },
        copper: {
          DEFAULT: "var(--cta)",
          hover:   "var(--cta-hov)",
        },
        // ── Risk severity (unchanged) ──────────────────────────
        risk: {
          low:      "#16a34a",
          medium:   "#eab308",
          high:     "#dc2626",
          neutral:  "#2563eb",
          inactive: "#6b7280",
        },
      },
      spacing: {
        1: "4px",
        2: "8px",
        3: "12px",
        4: "16px",
        5: "20px",
        6: "24px",
      },
    },
  },
  plugins: [],
} satisfies Config;
