import { useQuery } from '@tanstack/react-query'
import { Link, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api } from '../lib/api'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  LoadingState,
  Table,
  TBody,
  TD,
  TH,
  THead,
  TR,
} from '../components/ui'

interface SessionRow {
  id: string
  call_id: string
  started_at: string
  ended_at: string | null
  duration_seconds: number | null
  transcript: string
  error_code: string | null
  provider: string
  model: string | null
}

export function SessionsPage() {
  const { data, isLoading } = useQuery({
    queryKey: ['gov-sessions'],
    queryFn: async () =>
      (
        await api.get<{ items: SessionRow[]; total: number }>(
          '/api/gov/sessions?limit=100',
        )
      ).data,
  })

  return (
    <Layout>
      <PageHeader title="Сессии" description="История голосовых сессий." />
      <div className="px-8 py-6">
        {isLoading ? (
          <LoadingState />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="Сессий нет"
            description="Голосовых сессий пока не было."
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>ID сессии</TH>
                <TH>Начало</TH>
                <TH>Длительность</TH>
                <TH>Ошибка</TH>
              </tr>
            </THead>
            <TBody>
              {data.items.map((s) => (
                <TR key={s.id}>
                  <TD>
                    <Link
                      to={`/sessions/${s.id}`}
                      className="font-mono text-brand hover:text-brand-dark"
                    >
                      {s.call_id}
                    </Link>
                  </TD>
                  <TD className="whitespace-nowrap text-ink-muted">
                    {new Date(s.started_at).toLocaleString('ru-RU')}
                  </TD>
                  <TD className="text-ink">
                    {s.duration_seconds ?? '—'} с
                  </TD>
                  <TD>
                    {s.error_code ? (
                      <Badge tone="danger">{s.error_code}</Badge>
                    ) : (
                      <span className="text-ink-muted">—</span>
                    )}
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

export function SessionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const { data } = useQuery({
    queryKey: ['gov-session', id],
    queryFn: async () =>
      (await api.get<SessionRow>(`/api/gov/sessions/${id}`)).data,
    enabled: !!id,
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
        title={data.call_id}
        description={`${new Date(data.started_at).toLocaleString('ru-RU')} · ${data.duration_seconds ?? '—'} с · ${data.provider}/${data.model ?? '?'}`}
        actions={
          <Link to="/sessions">
            <Button variant="ghost" leftIcon={<ArrowLeft className="h-4 w-4" />}>
              Назад
            </Button>
          </Link>
        }
      />
      <div className="max-w-4xl space-y-4 px-8 py-6">
        {data.error_code && (
          <div className="rounded-card border border-rose-200 bg-rose-50 px-4 py-3 text-sm text-rose-700">
            <span className="font-semibold">Ошибка:</span>{' '}
            <span className="font-mono">{data.error_code}</span>
          </div>
        )}
        <Card title="Транскрипт" padding="none">
          <pre className="whitespace-pre-wrap p-5 font-mono text-xs leading-relaxed text-ink">
            {data.transcript || '(транскрипта нет)'}
          </pre>
        </Card>
      </div>
    </Layout>
  )
}
