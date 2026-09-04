import { z } from "zod";

const SupplierSchema = z.object({
  id: z.string(),
  name: z.string(),
  riskScore: z.number(),
  spend: z.number(),
  activePOs: z.number(),
  region: z.string(),
  tier: z.number(),
  category: z.string(),
  onTimeDelivery: z.number(),
  qualityYield: z.number(),
  inTransit: z.number(),
  delayed: z.number(),
  country: z.string(),
});

export type Supplier = z.infer<typeof SupplierSchema>;
import { suppliers as mockSuppliers } from "./mockData";

export type SupplierDraft = Omit<Supplier, "id">;

export const supplierService = {
  list: async (): Promise<Supplier[]> => {
    try {
      const res = await fetch("/api/suppliers", { next: { revalidate: 60 } });
      if (res.ok) {
        const data = await res.json();
        if (Array.isArray(data) && data.length > 0) {
          return z.array(SupplierSchema).parse(data);
        }
      }
    } catch {
      // Fallback
    }
    return mockSuppliers as unknown as Supplier[];
  },

  get: async (id: string): Promise<Supplier> => {
    try {
      const res = await fetch(`/api/suppliers/${id}`, { next: { revalidate: 60 } });
      if (res.ok) {
        return SupplierSchema.parse(await res.json());
      }
    } catch {
      // Fallback
    }
    const mock = mockSuppliers.find((s) => s.id === id);
    if (mock) return mock as unknown as Supplier;
    throw new Error(`Supplier ${id} not found`);
  },

  create: async (draft: SupplierDraft): Promise<Supplier> => {
    const res = await fetch("/api/suppliers", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(draft),
    });
    if (!res.ok) throw new Error(`Failed to create supplier: ${res.status}`);
    return res.json();
  },

  update: async (id: string, patch: Partial<SupplierDraft>): Promise<Supplier> => {
    const res = await fetch(`/api/suppliers/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(patch),
    });
    if (!res.ok) throw new Error(`Failed to update supplier ${id}: ${res.status}`);
    return res.json();
  },

  remove: async (id: string): Promise<void> => {
    const res = await fetch(`/api/suppliers/${id}`, { method: "DELETE" });
    if (!res.ok) throw new Error(`Failed to delete supplier ${id}: ${res.status}`);
  },
};
