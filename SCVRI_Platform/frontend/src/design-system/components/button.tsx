import { ButtonHTMLAttributes } from "react";
import { cn } from "@/utils/cn";

export function Button({ className, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      className={cn(
        "rounded-md bg-copper px-4 py-2 text-sm font-medium text-white transition-opacity hover:opacity-90 active:opacity-80 disabled:opacity-50",
        className
      )}
      {...props}
    />
  );
}
