"use client";

export function Tabs({ tabs, active, onSelect }: { tabs: string[]; active: string; onSelect: (tab: string) => void }) {
  return (
    <div className="flex gap-2 border-b pb-2">
      {tabs.map((tab) => (
        <button
          key={tab}
          onClick={() => onSelect(tab)}
          className={`rounded px-3 py-1 text-sm transition-colors ${
            active === tab
              ? "bg-accent text-white"
              : "bg-surface text-ink-2 hover:bg-stroke/30"
          }`}
        >
          {tab}
        </button>
      ))}
    </div>
  );
}
