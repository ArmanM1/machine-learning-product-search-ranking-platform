import type { SVGProps } from 'react'

type IconProps = SVGProps<SVGSVGElement>

const defaults: IconProps = {
  width: 18,
  height: 18,
  viewBox: '0 0 24 24',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.7,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  focusable: false,
}

export function ArrowUpRightIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="M7 17 17 7M8 7h9v9" /></svg>
}

export function ArrowRightIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="M5 12h14M14 7l5 5-5 5" /></svg>
}

export function ChevronDownIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="m7 10 5 5 5-5" /></svg>
}

export function SearchIcon(props: IconProps) {
  return <svg {...defaults} {...props}><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4 4" /></svg>
}

export function RefreshIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="M20 6v5h-5M4 18v-5h5" /><path d="M6.1 9a7 7 0 0 1 11.3-2.4L20 9M4 15l2.6 2.4A7 7 0 0 0 17.9 15" /></svg>
}

export function InfoIcon(props: IconProps) {
  return <svg {...defaults} {...props}><circle cx="12" cy="12" r="9" /><path d="M12 11v5M12 8h.01" /></svg>
}

export function AlertIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="M10.3 4.2 2.7 17.4A1.7 1.7 0 0 0 4.2 20h15.6a1.7 1.7 0 0 0 1.5-2.6L13.7 4.2a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 16.5h.01" /></svg>
}

export function CheckIcon(props: IconProps) {
  return <svg {...defaults} {...props}><path d="m5 12 4 4L19 6" /></svg>
}

export function CopyIcon(props: IconProps) {
  return <svg {...defaults} {...props}><rect x="8" y="8" width="11" height="11" rx="2" /><path d="M16 8V6a2 2 0 0 0-2-2H6a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h2" /></svg>
}
