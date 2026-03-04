import type { Config } from "tailwindcss";

export default {
  content: ["./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        risk: {
          low: "#16a34a",
          medium: "#eab308",
          high: "#dc2626",
          neutral: "#2563eb",
          inactive: "#6b7280"
        }
      },
      spacing: {
        1: "4px",
        2: "8px",
        3: "12px",
        4: "16px",
        5: "20px",
        6: "24px"
      }
    }
  },
  plugins: []
} satisfies Config;
