import { z } from "zod";

export async function getJson<T>(url: string, schema: z.ZodSchema<T>): Promise<T> {
  const response = await fetch(url, { next: { revalidate: 60 } });
  if (!response.ok) throw new Error(`Request failed: ${response.status}`);
  return schema.parse(await response.json());
}
