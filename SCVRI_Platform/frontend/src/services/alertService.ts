import { alerts } from "./mockData";

export const alertService = {
  list: async () => alerts,
  acknowledge: async (id: string) => ({ id, status: "acknowledged" as const })
};
