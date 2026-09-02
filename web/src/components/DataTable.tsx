import type { ReactNode } from 'react'

interface DataTableProps {
  caption: string
  headers: Array<{ label: string; align?: 'left' | 'right' }>
  rows: ReactNode[][]
  className?: string
}

export function DataTable({ caption, headers, rows, className = '' }: DataTableProps) {
  return (
    <div className="table-scroll" tabIndex={0} role="region" aria-label={`${caption}, scrollable table`}>
      <table className={className}>
        <caption className="sr-only">{caption}</caption>
        <thead>
          <tr>
            {headers.map((header) => (
              <th key={header.label} scope="col" className={header.align === 'right' ? 'numeric' : undefined}>
                {header.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {row.map((cell, cellIndex) => (
                <td key={cellIndex} className={headers[cellIndex]?.align === 'right' ? 'numeric' : undefined}>
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
