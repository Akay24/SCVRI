import { z } from "zod";
import { suppliers } from "./mockData";

const SupplierSchema = z.object({
  id: z.string(),
  name: z.string(),
  riskScore: z.number(),
  spend: z.number(),
  activePOs: z.number(),
  region: z.string()
});

export type Supplier = z.infer<typeof SupplierSchema>;

export const supplierService = {
  list: async (): Promise<Supplier[]> => z.array(SupplierSchema).parse(suppliers)
};
