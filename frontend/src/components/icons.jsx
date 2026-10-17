// ---------------------------------------------------------------------------
// icons.jsx
// ---------------------------------------------------------------------------
// A handful of small, hand-written SVG icons used across the app.
// Keeping them here (instead of pulling in an icon library) keeps the
// project dependency-free and makes every icon easy to find and tweak.
//
// Every icon accepts a `className` prop so callers can control size/color
// with normal Tailwind classes, e.g. <MailIcon className="w-5 h-5" />
// ---------------------------------------------------------------------------

const defaultProps = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  viewBox: '0 0 24 24',
}

export function MailIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <path d="m3 7 9 6 9-6" />
    </svg>
  )
}

export function LockIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <rect x="4" y="11" width="16" height="9" rx="2" />
      <path d="M8 11V7a4 4 0 0 1 8 0v4" />
    </svg>
  )
}

export function UserIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="12" cy="8" r="4" />
      <path d="M4 20c0-4 3.6-6 8-6s8 2 8 6" />
    </svg>
  )
}

export function PhoneIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M5 4h3l1.5 4.5L7 10a12 12 0 0 0 7 7l1.5-2.5L20 16v3a2 2 0 0 1-2 2C10.5 21 3 13.5 3 6a2 2 0 0 1 2-2Z" />
    </svg>
  )
}

export function MapPinIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M12 21s7-6.4 7-11.5A7 7 0 0 0 5 9.5C5 14.6 12 21 12 21Z" />
      <circle cx="12" cy="9.5" r="2.5" />
    </svg>
  )
}

export function BriefcaseIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <rect x="3" y="7" width="18" height="13" rx="2" />
      <path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2" />
      <path d="M3 12h18" />
    </svg>
  )
}

export function PlusIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M12 5v14M5 12h14" />
    </svg>
  )
}

export function ArrowRightIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </svg>
  )
}

export function GridIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <rect x="3" y="3" width="8" height="8" rx="1.5" />
      <rect x="13" y="3" width="8" height="8" rx="1.5" />
      <rect x="3" y="13" width="8" height="8" rx="1.5" />
      <rect x="13" y="13" width="8" height="8" rx="1.5" />
    </svg>
  )
}

export function DocumentIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M7 3h7l5 5v13a1 1 0 0 1-1 1H7a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z" />
      <path d="M14 3v5h5" />
    </svg>
  )
}

export function ListIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M9 6h11M9 12h11M9 18h11" />
      <path d="M4 6h.01M4 12h.01M4 18h.01" />
    </svg>
  )
}

export function GitBranchIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="6" cy="6" r="2.2" />
      <circle cx="6" cy="18" r="2.2" />
      <circle cx="18" cy="9" r="2.2" />
      <path d="M6 8.2V15.8" />
      <path d="M6 8.2C6 12 12 12.5 15.8 10.4" />
    </svg>
  )
}

export function CalendarIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <rect x="3" y="5" width="18" height="16" rx="2" />
      <path d="M16 3v4M8 3v4M3 10h18" />
    </svg>
  )
}

export function SettingsIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="12" cy="12" r="3" />
      <path d="M19.4 15a1.7 1.7 0 0 0 .3 1.9l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.9-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1-1.6 1.7 1.7 0 0 0-1.9.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.9 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.6-1 1.7 1.7 0 0 0-.3-1.9l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.9.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.9-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.9V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1Z" />
    </svg>
  )
}

export function CheckCircleIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="m8.5 12.5 2.5 2.5 5-5" />
    </svg>
  )
}

export function ClockIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3.5 2" />
    </svg>
  )
}

export function FolderIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2Z" />
    </svg>
  )
}

export function LogoutIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4" />
      <path d="M16 17l5-5-5-5" />
      <path d="M21 12H9" />
    </svg>
  )
}

export function BellIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M6 9a6 6 0 0 1 12 0c0 4 1.5 5.5 2 6H4c.5-.5 2-2 2-6Z" />
      <path d="M10 19a2 2 0 0 0 4 0" />
    </svg>
  )
}

export function PencilIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M4 20h4l10.5-10.5a2.1 2.1 0 0 0-3-3L5 17v3Z" />
      <path d="m13.5 6.5 3 3" />
    </svg>
  )
}

export function XIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  )
}

export function UsersIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <circle cx="9" cy="8" r="3.2" />
      <path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5" />
      <path d="M16.5 5a3 3 0 0 1 0 6" />
      <path d="M21 20c0-2.8-2-4.8-4.5-5.4" />
    </svg>
  )
}

export function ExternalLinkIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M14 4h6v6" />
      <path d="M10 14 20 4" />
      <path d="M18 13v5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h5" />
    </svg>
  )
}

export function ChatIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="M4 5h16v11H8l-4 4Z" />
    </svg>
  )
}

export function ChevronDownIcon({ className }) {
  return (
    <svg {...defaultProps} className={className}>
      <path d="m6 9 6 6 6-6" />
    </svg>
  )
}
