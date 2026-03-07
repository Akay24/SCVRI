import { create } from "zustand";
import { persist } from "zustand/middleware";
import { Role } from "@/types/navigation";

type Notification = { id: string; title: string; severity: "critical" | "high" | "medium" | "low" };

export type AuthUser = {
  id: string;
  tenantId: string;
  role: Role;
};

type AppState = {
  user: AuthUser | null;
  role: Role;
  notifications: Notification[];
  darkMode: boolean;
  setUser: (user: AuthUser) => void;
  clearUser: () => void;
  setRole: (role: Role) => void;
  toggleDarkMode: () => void;
};

export const useAppStore = create<AppState>()(
  persist(
    (set) => ({
      user: null,
      role: "analyst",
      notifications: [
        { id: "n1", title: "Port closure risk increased", severity: "high" },
        { id: "n2", title: "Supplier SLA breach", severity: "medium" },
      ],
      darkMode: false,
      setUser: (user) => set({ user, role: user.role }),
      clearUser: () => set({ user: null, role: "analyst" }),
      setRole: (role) => set({ role }),
      toggleDarkMode: () => set((s) => ({ darkMode: !s.darkMode })),
    }),
    {
      name: "scvri-app",
      partialize: (s) => ({ user: s.user, darkMode: s.darkMode }),
    }
  )
);
