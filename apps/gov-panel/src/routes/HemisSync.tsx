import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, Clock, XCircle } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import {
  Card,
  EmptyState,
  LoadingState,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
} from '../components/ui'
import { api } from '../lib/api'

// Staff have no other way to tell whether the kiosk's timetable is current.
// A stale mirror is invisible from the kiosk itself — it keeps answering
// confidently from week-old data — so this page exists to make "when did we
// last sync" a thing someone can actually look at.

interface Sweep {
  resource: string
  status: string
  item_count: number
  error: string
  last_run_at: string | null
}

interface HemisStatus {
  sweeps: Sweep[]
  counts: Record<string, number>
}

const RESOURCE_LABEL: Record<string, string> = {
  departments: 'Факультеты и кафедры',
  specialties: 'Направления',
  groups: 'Группы',
  schedule: 'Расписание',
}

const COUNT_LABEL: Record<string, string> = {
  lessons: 'Занятий',
  groups: 'Групп',
  specialties: 'Направлений',
}

// A nightly job that last ran more than ~26 h ago has missed a night. Same
// threshold the backup check uses, for the same reason: one missed run is the
// signal, not a slow one.
const STALE_AFTER_MS = 26 * 60 * 60 * 1000

function statusIcon(status: string, stale: boolean) {
  if (status === 'error') return <XCircle className="h-4 w-4 text-danger" />
  if (status === 'running') return <Clock className="h-4 w-4 text-ink-muted" />
  if (stale) return <AlertTriangle className="h-4 w-4 text-warning" />
  if (status === 'ok') return <CheckCircle2 className="h-4 w-4 text-success" />
  return <Clock className="h-4 w-4 text-ink-muted" />
}

function ago(iso: string | null): string {
  if (!iso) return 'ни разу'
  const ms = Date.now() - new Date(iso).getTime()
  const hours = Math.floor(ms / 3_600_000)
  if (hours < 1) return 'меньше часа назад'
  if (hours < 24) return `${hours} ч назад`
  return `${Math.floor(hours / 24)} дн назад`
}

export function HemisSyncPage() {
  const { data, isLoading } = useQuery<HemisStatus>({
    queryKey: ['gov-hemis'],
    queryFn: async () => (await api.get('/api/gov/hemis')).data,
    refetchInterval: 60_000,
  })

  return (
    <Layout>
      <PageHeader
        title="Синхронизация с HEMIS"
        description="Расписание и группы копируются из HEMIS каждую ночь. Киоск читает только эту копию, поэтому здесь видно, насколько свежие данные он показывает."
      />
      <div className="space-y-6 p-8">
        {isLoading && <LoadingState />}

        {data && (
          <>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
              {Object.entries(data.counts).map(([key, value]) => (
                <Card key={key} className="p-6">
                  <div className="text-sm text-ink-muted">
                    {COUNT_LABEL[key] ?? key}
                  </div>
                  <div className="mt-1 text-3xl font-semibold text-ink">
                    {value.toLocaleString('ru-RU')}
                  </div>
                </Card>
              ))}
            </div>

            <Card>
              {data.sweeps.length === 0 ? (
                <EmptyState
                  title="Синхронизация ещё не запускалась"
                  description="Запустите её командой: docker compose run --rm hemis-sync"
                />
              ) : (
                <Table>
                  <THead>
                    <TR>
                      <TH>Ресурс</TH>
                      <TH>Статус</TH>
                      <TH>Записей</TH>
                      <TH>Последний запуск</TH>
                    </TR>
                  </THead>
                  <TBody>
                    {data.sweeps.map((s) => {
                      const stale =
                        s.status === 'ok' &&
                        (!s.last_run_at ||
                          Date.now() - new Date(s.last_run_at).getTime() >
                            STALE_AFTER_MS)
                      return (
                        <TR key={s.resource}>
                          <TD className="font-medium text-ink">
                            {RESOURCE_LABEL[s.resource] ?? s.resource}
                          </TD>
                          <TD>
                            <span className="flex items-center gap-2">
                              {statusIcon(s.status, stale)}
                              <span>
                                {s.status === 'error'
                                  ? 'Ошибка'
                                  : stale
                                    ? 'Устарело'
                                    : s.status === 'ok'
                                      ? 'В порядке'
                                      : s.status}
                              </span>
                            </span>
                            {s.error && (
                              <div className="mt-1 font-mono text-xs text-danger">
                                {s.error}
                              </div>
                            )}
                          </TD>
                          <TD>{s.item_count.toLocaleString('ru-RU')}</TD>
                          <TD className="text-ink-muted">{ago(s.last_run_at)}</TD>
                        </TR>
                      )
                    })}
                  </TBody>
                </Table>
              )}
            </Card>
          </>
        )}
      </div>
    </Layout>
  )
}
