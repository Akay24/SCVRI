import { create } from "zustand";
import { Role } from "@/types/navigation";

type Notification = { id: string; title: string; severity: "critical" | "high" | "medium" | "low" };

type AppState = {
  role: Role;
  notifications: Notification[];
  setRole: (role: Role) => void;
};

export const useAppStore = create<AppState>((set) => ({
  role: "analyst",
  notifications: [
    { id: "n1", title: "Port closure risk increased", severity: "high" },
    { id: "n2", title: "Supplier SLA breach", severity: "medium" }
  ],
  setRole: (role) => set({ role })
}));
