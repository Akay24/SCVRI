"use client";

import {
  ColumnDef,
  flexRender,
  getCoreRowModel,
  useReactTable
} from "@tanstack/react-table";

export function DataTable<TData>({ data, columns }: { data: TData[]; columns: ColumnDef<TData>[] }) {
  const table = useReactTable({ data, columns, getCoreRowModel: getCoreRowModel() });

  return (
    <div className="max-h-[420px] overflow-auto rounded-md border border-stroke">
      <table className="w-full text-left text-sm">
        <thead className="sticky top-0 bg-surface">
          {table.getHeaderGroups().map((headerGroup) => (
            <tr key={headerGroup.id}>
              {headerGroup.headers.map((header) => (
                <th key={header.id} className="px-3 py-2 font-semibold text-ink">
                  {flexRender(header.column.columnDef.header, header.getContext())}
                </th>
              ))}
            </tr>
          ))}
        </thead>
        <tbody>
          {table.getRowModel().rows.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                className="px-3 py-10 text-center text-sm text-ink-3"
              >
                No records found
              </td>
            </tr>
          ) : (
            table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-t border-stroke transition-colors hover:bg-surface">
                {row.getVisibleCells().map((cell) => (
                  <td key={cell.id} className="px-3 py-2 text-ink-2">
                    {flexRender(cell.column.columnDef.cell, cell.getContext())}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}
