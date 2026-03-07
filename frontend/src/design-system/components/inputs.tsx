import { InputHTMLAttributes } from "react";

export const SearchInput = (props: InputHTMLAttributes<HTMLInputElement>) => (
  <input
    aria-label="Global search"
    className="w-full rounded-md border border-stroke bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-3 focus:border-accent focus:outline-none transition-colors"
    {...props}
  />
);

export const Filters = ({ children }: { children: React.ReactNode }) => <div className="flex flex-wrap gap-2">{children}</div>;
