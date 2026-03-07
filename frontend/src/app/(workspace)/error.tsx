"use client";

import { useEffect } from "react";

export default function WorkspaceError({
  error,
  reset
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log to an error reporting service in production
    console.error("[SCVRI] Page error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center gap-4 text-center">
      <div className="rounded-full bg-red-100 p-4">
        <svg
          className="h-10 w-10 text-red-600"
          fill="none"
          viewBox="0 0 24 24"
          stroke="currentColor"
          strokeWidth={1.5}
        >
          <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z" />
        </svg>
      </div>
      <div>
        <h2 className="text-xl font-semibold text-slate-900">Something went wrong</h2>
        <p className="mt-1 max-w-sm text-sm text-slate-500">
          {error.message || "An unexpected error occurred loading this page."}
        </p>
        {error.digest && (
          <p className="mt-1 font-mono text-xs text-slate-400">Error ID: {error.digest}</p>
        )}
      </div>
      <button
        onClick={reset}
        className="rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
      >
        Try again
      </button>
    </div>
  );
}
