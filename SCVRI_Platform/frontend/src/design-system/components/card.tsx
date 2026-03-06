import { PropsWithChildren } from "react";
import { cn } from "@/utils/cn";

export function Card({ children, className }: PropsWithChildren<{ className?: string }>) {
  return (
    <section className={cn("rounded-lg border border-stroke bg-card p-4 shadow-sm", className)}>
      {children}
    </section>
  );
}
