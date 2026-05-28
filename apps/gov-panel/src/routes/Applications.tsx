import { useMemo, useState } from 'react'
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

interface AppRow {
  id: string
  topic: string
  body: string
  phone: string
  status: Status
  category_id: string | null
  category_slug: string | null
  assigned_user_id: string | null
  resolution_note: string
  created_at: string
  resolved_at: string | null
}

interface Category {
  id: string
  slug: string
  name_translations: { uz: string; kk: string; ru: string }
  order: number
}

interface StaffMember {
  id: string
  email: string
  full_name: string
  role: string
}

function categoryLabel(cat: Category | undefined): string {
  if (!cat) return ''
  return cat.name_translations.ru || cat.name_translations.kk || cat.slug
}

export function ApplicationsPage() {
  const { me } = useAuth()
  const reviewer = isReviewer(me)
  const [statusFilter, setStatusFilter] = useState<Status | ''>('')
  const [search, setSearch] = useState('')

  const { data, isLoading } = useQuery({
    queryKey: ['gov-apps', statusFilter, search],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (search) params.set('search', search)
      params.set('limit', '100')
      const r = await api.get<{ items: AppRow[]; total: number }>(
        `/api/gov/applications?${params.toString()}`,
      )
      return r.data
    },
  })

  const categoriesQ = useQuery({
    queryKey: ['gov-categories'],
    queryFn: async () =>
      (await api.get<{ items: Category[] }>('/api/gov/application-categories'))
        .data.items,
  })
  const catById = useMemo(() => {
    const map: Record<string, Category> = {}
    for (const c of categoriesQ.data ?? []) map[c.id] = c
    return map
  }, [categoriesQ.data])

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
                <TH>Категория</TH>
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
                  <TD className="text-ink-muted">
                    {a.category_id ? (
                      <Badge tone="neutral">
                        {categoryLabel(catById[a.category_id])}
                      </Badge>
                    ) : (
                      <span className="text-xs text-ink-muted/60">
                        Без категории
                      </span>
                    )}
                  </TD>
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

  const categoriesQ = useQuery({
    queryKey: ['gov-categories'],
    queryFn: async () =>
      (await api.get<{ items: Category[] }>('/api/gov/application-categories'))
        .data.items,
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
      category_id?: string | null
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
        <Card title="Текст обращения">
          <div className="whitespace-pre-wrap leading-relaxed text-ink">
            {data.body}
          </div>
        </Card>

        {!reviewer && (
          <Card title="Назначение и категория">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-ink-muted">
                  Ответственный
                </label>
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
              </div>
              <div>
                <label className="mb-1 block text-xs font-medium uppercase tracking-wider text-ink-muted">
                  Категория
                </label>
                <Select
                  value={data.category_id ?? ''}
                  onChange={(e) =>
                    update.mutate({ category_id: e.target.value || null })
                  }
                >
                  <option value="">— Без категории —</option>
                  {(categoriesQ.data ?? []).map((c) => (
                    <option key={c.id} value={c.id}>
                      {categoryLabel(c)}
                    </option>
                  ))}
                </Select>
              </div>
            </div>
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
