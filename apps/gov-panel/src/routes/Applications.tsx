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
  cn,
} from '../components/ui'

// Status enum extended with `returned`. Reviewer can only transition to
// `resolved` or `returned`; admin sees the full set.
const STATUSES = ['new', 'in_progress', 'resolved', 'returned', 'archived'] as const
type Status = (typeof STATUSES)[number]
const REVIEWER_TARGET_STATUSES: Status[] = ['resolved', 'returned']
const STATUS_LABEL_RU: Record<Status, string> = {
  new: 'Новые',
  in_progress: 'В работе',
  resolved: 'Завершено',
  returned: 'Возвращено',
  archived: 'Архив',
}

// `kind` splits the inbox into citizen appeals (murajaat) and feedback
// (complaint / suggestion / gratitude). Backend filters via ?kind=.
type Kind = 'murajaat' | 'feedback'
type FeedbackType = 'complaint' | 'suggestion' | 'gratitude'

const KIND_TABS: { value: Kind; label: string }[] = [
  { value: 'murajaat', label: 'Мүражатлар' },
  { value: 'feedback', label: 'Фикрлер' },
]

// Feedback type labels — Karakalpak Cyrillic / Russian, matching the
// bilingual operational vocabulary used elsewhere in the panel.
const FEEDBACK_TYPE_META: Record<
  FeedbackType,
  { label: string; tone: 'danger' | 'info' | 'success' }
> = {
  complaint: { label: 'Шағым / Жалоба', tone: 'danger' },
  suggestion: { label: 'Усыныс / Предложение', tone: 'info' },
  gratitude: { label: 'Миннетдаршылық / Благодарность', tone: 'success' },
}

interface AppRow {
  id: string
  topic: string
  body: string
  phone: string
  status: Status
  kind: Kind
  feedback_type: FeedbackType | null
  category_id: string | null
  category_slug: string | null
  assigned_user_id: string | null
  resolution_note: string
  created_at: string
  resolved_at: string | null
}

interface StaffMember {
  id: string
  email: string
  full_name: string
  role: string
}

function FeedbackTypeBadge({ type }: { type: FeedbackType | null }) {
  if (!type) return <span className="text-xs text-ink-muted/60">—</span>
  const meta = FEEDBACK_TYPE_META[type]
  if (!meta) return <Badge tone="neutral">{type}</Badge>
  return <Badge tone={meta.tone}>{meta.label}</Badge>
}

export function ApplicationsPage() {
  const { me } = useAuth()
  const reviewer = isReviewer(me)
  const [kind, setKind] = useState<Kind>('murajaat')
  const [statusFilter, setStatusFilter] = useState<Status | ''>('')
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['gov-apps', kind, statusFilter, search],
    queryFn: async () => {
      const params = new URLSearchParams()
      params.set('kind', kind)
      if (statusFilter) params.set('status', statusFilter)
      if (search) params.set('search', search)
      params.set('limit', '100')
      const r = await api.get<{ items: AppRow[]; total: number }>(
        `/api/gov/applications?${params.toString()}`,
      )
      return r.data
    },
  })

  const isFeedback = kind === 'feedback'

  return (
    <Layout>
      <PageHeader
        title={reviewer ? 'Мои обращения' : 'Обращения'}
        description={
          reviewer
            ? 'Обращения, назначенные на вас. Внесите решение и обновите статус.'
            : 'Все обращения, поступившие через киоск.'
        }
        actions={
          <div className="flex items-center gap-2">
            <Input
              placeholder="Поиск..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              leftIcon={<Search className="h-4 w-4" />}
              className="w-64"
            />
            <Select
              value={statusFilter}
              onChange={(e) =>
                setStatusFilter(e.target.value as Status | '')
              }
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
        <div className="mb-5 inline-flex rounded-lg border border-line bg-card p-1">
          {KIND_TABS.map((tab) => (
            <button
              key={tab.value}
              type="button"
              onClick={() => setKind(tab.value)}
              className={cn(
                'rounded-md px-4 py-1.5 text-sm font-medium transition',
                kind === tab.value
                  ? 'bg-brand text-white shadow-sm'
                  : 'text-ink-muted hover:text-ink',
              )}
            >
              {tab.label}
            </button>
          ))}
        </div>
        {isLoading ? (
          <LoadingState />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="Нет обращений"
            description="По выбранному фильтру обращений пока нет."
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>Тема</TH>
                {isFeedback && <TH>Тип</TH>}
                <TH>Телефон</TH>
                <TH>Статус</TH>
                <TH>Дата</TH>
              </tr>
            </THead>
            <TBody>
              {data.items.map((a) => (
                <TR key={a.id}>
                  <TD>
                    <Link
                      to={`/applications/${a.id}`}
                      className="font-medium text-brand hover:text-brand-dark"
                    >
                      {a.topic}
                    </Link>
                  </TD>
                  {isFeedback && (
                    <TD>
                      <FeedbackTypeBadge type={a.feedback_type} />
                    </TD>
                  )}
                  <TD className="font-mono text-ink-muted">{a.phone}</TD>
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

export function ApplicationDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { me } = useAuth()
  const reviewer = isReviewer(me)
  const qc = useQueryClient()
  const { data } = useQuery({
    queryKey: ['gov-app', id],
    queryFn: async () =>
      (await api.get<AppRow>(`/api/gov/applications/${id}`)).data,
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

  const [note, setNote] = useState('')

  const update = useMutation({
    mutationFn: async (payload: {
      status?: Status
      assigned_user_id?: string | null
      resolution_note?: string
    }) => api.patch(`/api/gov/applications/${id}`, payload),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gov-app', id] })
      qc.invalidateQueries({ queryKey: ['gov-apps'] })
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
        title={data.topic}
        description={`Телефон: ${data.phone} · ${new Date(data.created_at).toLocaleString('ru-RU')}`}
        actions={
          <Link to="/applications">
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Назад
            </Button>
          </Link>
        }
      />
      <div className="max-w-3xl space-y-6 px-8 py-6">
        {data.kind === 'feedback' && (
          <div className="flex items-center gap-2">
            <span className="text-xs font-medium uppercase tracking-wider text-ink-muted">
              Тип отзыва:
            </span>
            <FeedbackTypeBadge type={data.feedback_type} />
          </div>
        )}

        <Card title="Текст обращения">
          <div className="whitespace-pre-wrap leading-relaxed text-ink">
            {data.body}
          </div>
        </Card>

        {!reviewer && (
          <Card title="Назначение ответственного">
            <Select
              value={data.assigned_user_id ?? ''}
              onChange={(e) =>
                update.mutate({
                  assigned_user_id: e.target.value || null,
                })
              }
            >
              <option value="">— Не назначен —</option>
              {(reviewersQ.data ?? []).map((s) => (
                <option key={s.id} value={s.id}>
                  {s.full_name || s.email} ({s.role === 'reviewer' ? 'Ответственный' : 'Админ'})
                </option>
              ))}
            </Select>
          </Card>
        )}

        <Card title="Изменение статуса">
          <div className="mb-5 flex flex-wrap gap-2">
            {STATUSES.map((s) => {
              const disabled =
                s === data.status ||
                (reviewer && !REVIEWER_TARGET_STATUSES.includes(s))
              return (
                <Button
                  key={s}
                  variant={s === data.status ? 'primary' : 'secondary'}
                  size="sm"
                  disabled={disabled || update.isPending}
                  onClick={() => update.mutate({ status: s })}
                >
                  {STATUS_LABEL_RU[s]}
                </Button>
              )
            })}
          </div>
          <div className="space-y-2">
            <h3 className="text-xs font-medium uppercase tracking-wider text-ink-muted">
              Решение / комментарий
            </h3>
            <Textarea
              rows={4}
              value={note || data.resolution_note}
              onChange={(e) => setNote(e.target.value)}
            />
            <Button
              onClick={() =>
                update.mutate({
                  resolution_note: note || data.resolution_note,
                })
              }
              loading={update.isPending}
            >
              Сохранить
            </Button>
          </div>
        </Card>
      </div>
    </Layout>
  )
}
