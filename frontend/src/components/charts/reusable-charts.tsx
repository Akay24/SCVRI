"use client";

import { lazy, Suspense } from "react";

const Recharts = lazy(() => import("./recharts-set"));

export function LazyLineChart({ data }: { data: { name: string; value: number }[] }) {
  return <Suspense fallback={<div>Loading chart...</div>}><Recharts type="line" data={data} /></Suspense>;
}

export function LazyBarChart({ data }: { data: { name: string; value: number }[] }) {
  return <Suspense fallback={<div>Loading chart...</div>}><Recharts type="bar" data={data} /></Suspense>;
}
