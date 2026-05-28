import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft, Search } from 'lucide-react'
import { toast } from 'sonner'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import { isReviewer, useAuth } from '../lib/auth'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingState,
  Select,
  StatusBadge,
  Table,
  TBody,
  TD,
  TH,
  THead,
  Textarea,
  TR,
} from '../components/ui'

const STATUSES = ['pending', 'completed', 'cancelled', 'no_show'] as const
type Status = (typeof STATUSES)[number]
const REVIEWER_TARGET_STATUSES: Status[] = ['completed', 'no_show']
const STATUS_LABEL_RU: Record<Status, string> = {
  pending: 'Ожидается',
  completed: 'Завершён',
  cancelled: 'Отменён',
  no_show: 'Не явился',
}

// Callback-reception model: a citizen registers and the Council calls them
// back. No official, no scheduled date, no queue number anymore.
interface AppointmentRow {
  id: string
  visitor_phone: string
  visitor_phone_masked: string
  topic_summary: string
  reference_no: string
  status: Status
  source: 'kiosk' | 'online'
  session_id: string | null
  verification_url: string
  assigned_user_id: string | null
  assigned_at: string | null
  result_note: string
  created_at: string
  updated_at: string
}

interface StaffMember {
  id: string
  email: string
  full_name: string
  role: string
}

export function AppointmentsPage() {
  const { me } = useAuth()
  const reviewer = isReviewer(me)
  const [statusFilter, setStatusFilter] = useState<Status | ''>('')
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['gov-appts', statusFilter, search],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (search) params.set('search', search)
      params.set('limit', '100')
      const r = await api.get<{ items: AppointmentRow[]; total: number }>(
        `/api/gov/appointments?${params.toString()}`,
      )
      return r.data
    },
  })

  return (
    <Layout>
      <PageHeader
        title={reviewer ? 'Мои приёмы' : 'Приёмы'}
        description={
          reviewer
            ? 'Заявки на обратный звонок, назначенные на вас. Внесите результат и обновите статус.'
            : 'Заявки граждан на обратный звонок (Кенес перезвонит).'
        }
        actions={
          <div className="flex items-center gap-2">
            <Input
              placeholder="Телефон или тема..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leftIcon={<Search className="h-4 w-4" />}
              className="w-64"
            />
            <Select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as Status | '')}
              className="w-44"
            >
              <option value="">Все статусы</option>
              {STATUSES.map((s) => (
                <option key={s} value={s}>
                  {STATUS_LABEL_RU[s]}
                </option>
              ))}
            </Select>
          </div>
        }
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <LoadingState />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="Нет приёмов"
            description="По выбранному фильтру приёмов пока нет."
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>№</TH>
                <TH>Телефон</TH>
                <TH>Мәселе</TH>
                <TH>Источник</TH>
                <TH>Статус</TH>
                <TH>Создан</TH>
              </tr>
            </THead>
            <TBody>
              {data.items.map((a) => (
                <TR key={a.id}>
                  <TD className="font-mono">
                    <Link
                      to={`/appointments/${a.id}`}
                      className="font-semibold text-brand hover:text-brand-dark"
                    >
                      {a.reference_no}
                    </Link>
                  </TD>
                  <TD className="font-mono text-ink-muted">{a.visitor_phone}</TD>
                  <TD className="max-w-xs truncate text-ink-muted">
                    {a.topic_summary}
                  </TD>
                  <TD>
                    <Badge tone={a.source === 'kiosk' ? 'info' : 'brand'}>
                      {a.source === 'kiosk' ? 'Киоск' : 'Онлайн'}
                    </Badge>
                  </TD>
                  <TD>
                    <StatusBadge status={a.status} />
                  </TD>
                  <TD className="whitespace-nowrap text-ink-muted">
                    {new Date(a.created_at).toLocaleString('ru-RU')}
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
    </Layout>
  )
}

export function AppointmentDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { me } = useAuth()
  const reviewer = isReviewer(me)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['gov-appt', id],
    queryFn: async () =>
      (await api.get<AppointmentRow>(`/api/gov/appointments/${id}`)).data,
    enabled: !!id,
  })

  const reviewersQ = useQuery({
    queryKey: ['gov-staff', 'reviewers+admins'],
    enabled: !reviewer,
    queryFn: async () =>
      (
        await api.get<{ items: StaffMember[] }>(
          '/api/gov/staff',
        )
      ).data.items.filter(
        (s) => s.role === 'reviewer' || s.role === 'org_admin',
      ),
  })

  const [resultDraft, setResultDraft] = useState('')

  const update = useMutation({
    mutationFn: async (payload: {
      status?: Status
      assigned_user_id?: string | null
      result_note?: string
    }) => api.patch(`/api/gov/appointments/${id}`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gov-appt', id] })
      qc.invalidateQueries({ queryKey: ['gov-appts'] })
      toast.success('Сохранено')
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  if (!data) {
    return (
      <Layout>
        <PageHeader title="..." />
        <LoadingState />
      </Layout>
    )
  }

  return (
    <Layout>
      <PageHeader
        title={`Приём ${data.reference_no}`}
        description={`${data.visitor_phone} · ${new Date(data.created_at).toLocaleString('ru-RU')}`}
        actions={
          <Link to="/appointments">
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Назад
            </Button>
          </Link>
        }
      />
      <div className="max-w-3xl space-y-6 px-8 py-6">
        <Card title="Мәселе">
          <div className="whitespace-pre-wrap leading-relaxed text-ink">
            {data.topic_summary || 'Не указано'}
          </div>
        </Card>

        <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
          <Field label="Номер" value={data.reference_no} mono />
          <Field label="Телефон" value={data.visitor_phone} mono />
          <Field
            label="Источник"
            value={data.source === 'kiosk' ? 'Киоск' : 'Онлайн'}
          />
          <Field label="Статус" value={STATUS_LABEL_RU[data.status] ?? data.status} />
          <Field
            label="Создан"
            value={new Date(data.created_at).toLocaleString('ru-RU')}
          />
        </div>

        {!reviewer && (
          <Card title="Назначение ответственного">
            <Select
              value={data.assigned_user_id ?? ''}
              onChange={(e) =>
                update.mutate({ assigned_user_id: e.target.value || null })
              }
            >
              <option value="">— Не назначен —</option>
              {(reviewersQ.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.full_name || s.email} ({s.role === 'reviewer' ? 'Ответственный' : 'Админ'})
                </option>
              ))}
            </Select>
            {data.assigned_at && (
              <p className="mt-2 text-xs text-ink-muted">
                Назначен: {new Date(data.assigned_at).toLocaleString('ru-RU')}
              </p>
            )}
          </Card>
        )}

        <Card title="Результат приёма">
          <Textarea
            rows={4}
            placeholder={
              reviewer
                ? 'Опишите результат обратного звонка (что обсуждалось, какое решение принято).'
                : 'Запись приёма (для администратора — обычно заполняет ответственный).'
            }
            value={resultDraft || data.result_note}
            onChange={(e) => setResultDraft(e.target.value)}
          />
          <div className="mt-3 flex justify-end">
            <Button
              onClick={() =>
                update.mutate({
                  result_note: resultDraft || data.result_note,
                })
              }
              loading={update.isPending}
            >
              Сохранить результат
            </Button>
          </div>
        </Card>

        <Card title="Изменение статуса">
          <div className="flex flex-wrap gap-2">
            {STATUSES.map((s) => {
              const disabled =
                s === data.status ||
                update.isPending ||
                (reviewer && !REVIEWER_TARGET_STATUSES.includes(s))
              return (
                <Button
                  key={s}
                  variant={s === data.status ? 'primary' : 'secondary'}
                  size="sm"
                  disabled={disabled}
                  onClick={() => update.mutate({ status: s })}
                >
                  {STATUS_LABEL_RU[s]}
                </Button>
              )
            })}
          </div>
        </Card>

        {!reviewer && (
          <Card title="QR-ссылка для проверки">
            <a
              href={data.verification_url}
              target="_blank"
              rel="noreferrer"
              className="break-all font-mono text-sm text-brand hover:text-brand-dark"
            >
              {data.verification_url}
            </a>
          </Card>
        )}
      </div>
    </Layout>
  )
}

function Field({
  label,
  value,
  mono = false,
}: {
  label: string
  value: string
  mono?: boolean
}) {
  return (
    <div className="rounded-card border border-line bg-card p-4">
      <div className="text-xs font-medium uppercase tracking-wider text-ink-muted">
        {label}
      </div>
      <div
        className={`mt-1 text-ink ${mono ? 'font-mono text-sm' : 'text-sm'}`}
      >
        {value}
      </div>
    </div>
  )
}
