import { Badge } from './Badge'

type AppStatus = 'new' | 'in_progress' | 'resolved' | 'returned' | 'archived'
type ApptStatus = 'pending' | 'completed' | 'cancelled' | 'no_show'
export type AnyStatus = AppStatus | ApptStatus | string

// Status labels are intentionally KARAKALPAK CYRILLIC even though the rest
// of the admin UI is Russian. The operator's call: status names are
// operational stages used by Karakalpak gov staff and reads more natural
// in their own script than a Russian transliteration.
const MAP: Record<
  string,
  { tone: 'info' | 'warning' | 'success' | 'neutral' | 'danger' | 'brand'; label: string }
> = {
  // applications (murajat)
  new: { tone: 'info', label: 'Янги' },
  in_progress: { tone: 'warning', label: 'Көрип шығылмақта' },
  resolved: { tone: 'success', label: 'Көрип шығылған' },
  returned: { tone: 'brand', label: 'Қайтарылған' },
  archived: { tone: 'neutral', label: 'Архив' },
  // appointments (qabul) — Russian, matches admin chrome
  pending: { tone: 'info', label: 'Ожидается' },
  completed: { tone: 'success', label: 'Завершён' },
  cancelled: { tone: 'danger', label: 'Отменён' },
  no_show: { tone: 'neutral', label: 'Не явился' },
}

export function StatusBadge({ status }: { status: AnyStatus }) {
  const entry = MAP[status] ?? { tone: 'neutral' as const, label: status }
  return <Badge tone={entry.tone}>{entry.label}</Badge>
}
