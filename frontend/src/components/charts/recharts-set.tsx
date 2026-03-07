"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis
} from "recharts";

export default function RechartsSet({ type, data }: { type: "line" | "bar"; data: { name: string; value: number }[] }) {
  return (
    <div className="h-64 w-full">
      <ResponsiveContainer>
        {type === "line" ? (
          <LineChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Line dataKey="value" stroke="#2563eb" /></LineChart>
        ) : (
          <BarChart data={data}><CartesianGrid strokeDasharray="3 3" /><XAxis dataKey="name" /><YAxis /><Tooltip /><Bar dataKey="value" fill="#2563eb" /></BarChart>
        )}
      </ResponsiveContainer>
    </div>
  );
}
