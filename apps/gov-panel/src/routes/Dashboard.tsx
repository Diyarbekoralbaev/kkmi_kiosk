import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Cell,
  Legend,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api } from '../lib/api'
import { Card, LoadingState, Select, cn } from '../components/ui'

interface MonthlyTotals {
  received: number
  in_progress: number
  resolved: number
  returned: number
}
interface DailyPoint {
  date: string
  applications: number
  appointments: number
}
interface CategoryPoint {
  id: string
  slug: string
  name_translations: { uz: string; kk: string; ru: string }
  count: number
}
interface MonthlyOut {
  year: number
  month: number
  totals: MonthlyTotals
  daily: DailyPoint[]
  categories: CategoryPoint[]
}

// KPI tile titles intentionally in Karakalpak Cyrillic per operator
// decision — these are the operational stages gov staff use day-to-day,
// in their script. Everything else around them is Russian.
const KPI_LABELS = {
  received: 'Жами тускен',
  in_progress: 'Көрип шығылмақта',
  resolved: 'Көрип шығылған',
  returned: 'Қайтарылған',
} as const

const KPI_COLORS = {
  received: 'text-brand',
  in_progress: 'text-amber-600',
  resolved: 'text-emerald-600',
  returned: 'text-rose-600',
} as const

// Recharts category palette — picked to read clearly on light cards.
const CATEGORY_COLORS = [
  '#0a4d8c', // brand
  '#f5b932', // accent
  '#10b981', // emerald
  '#3b82f6', // blue
  '#a855f7', // purple
  '#f97316', // orange
  '#06b6d4', // cyan
  '#84cc16', // lime
  '#ef4444', // red
  '#94a3b8', // slate
  '#d97706', // amber-dark
]

function monthOptions(now: Date): { value: string; label: string }[] {
  // Last 12 months including current.
  const out: { value: string; label: string }[] = []
  for (let i = 0; i < 12; i += 1) {
    const d = new Date(now.getFullYear(), now.getMonth() - i, 1)
    const y = d.getFullYear()
    const m = d.getMonth() + 1
    out.push({
      value: `${y}-${String(m).padStart(2, '0')}`,
      label: d.toLocaleDateString('ru-RU', { month: 'long', year: 'numeric' }),
    })
  }
  return out
}

export function DashboardPage() {
  const now = new Date()
  const [selected, setSelected] = useState(
    `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`,
  )
  const [yStr, mStr] = selected.split('-')
  const year = Number(yStr)
  const month = Number(mStr)

  const { data, isLoading } = useQuery({
    queryKey: ['gov-dashboard-monthly', year, month],
    queryFn: async () =>
      (
        await api.get<MonthlyOut>(
          `/api/gov/dashboard/monthly?year=${year}&month=${month}`,
        )
      ).data,
  })

  const months = useMemo(() => monthOptions(now), [now])

  return (
    <Layout>
      <PageHeader
        title="Дашборд"
        description="Сводка обращений и приёмов за месяц."
        actions={
          <Select
            value={selected}
            onChange={(e) => setSelected(e.target.value)}
            className="w-56"
          >
            {months.map((m) => (
              <option key={m.value} value={m.value}>
                {m.label}
              </option>
            ))}
          </Select>
        }
      />
      <div className="space-y-6 px-8 py-6">
        {isLoading || !data ? (
          <LoadingState />
        ) : (
          <>
            <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
              <Kpi
                label={KPI_LABELS.received}
                value={data.totals.received}
                colorClass={KPI_COLORS.received}
              />
              <Kpi
                label={KPI_LABELS.in_progress}
                value={data.totals.in_progress}
                colorClass={KPI_COLORS.in_progress}
              />
              <Kpi
                label={KPI_LABELS.resolved}
                value={data.totals.resolved}
                colorClass={KPI_COLORS.resolved}
              />
              <Kpi
                label={KPI_LABELS.returned}
                value={data.totals.returned}
                colorClass={KPI_COLORS.returned}
              />
            </div>

            <Card title="Динамика по дням">
              <div className="h-72 w-full">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart
                    data={data.daily.map((d) => ({
                      ...d,
                      day: new Date(d.date).getDate(),
                    }))}
                    margin={{ top: 10, right: 24, bottom: 10, left: 0 }}
                  >
                    <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
                    <XAxis
                      dataKey="day"
                      stroke="#5a6b85"
                      fontSize={12}
                      tick={{ fill: '#5a6b85' }}
                    />
                    <YAxis
                      stroke="#5a6b85"
                      fontSize={12}
                      tick={{ fill: '#5a6b85' }}
                      allowDecimals={false}
                    />
                    <Tooltip
                      contentStyle={{
                        background: '#fff',
                        border: '1px solid #e2e8f0',
                        borderRadius: 8,
                        fontSize: 12,
                      }}
                      labelFormatter={(value: number) => `День ${value}`}
                    />
                    <Legend
                      wrapperStyle={{ fontSize: 12, paddingTop: 8 }}
                      iconType="circle"
                    />
                    <Line
                      type="monotone"
                      dataKey="applications"
                      name="Обращения"
                      stroke="#0a4d8c"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      activeDot={{ r: 5 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="appointments"
                      name="Приёмы"
                      stroke="#f5b932"
                      strokeWidth={2}
                      dot={{ r: 3 }}
                      activeDot={{ r: 5 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </Card>

            <div className="grid grid-cols-1 gap-6 md:grid-cols-2">
              <Card title="Категории обращений">
                {data.categories.length === 0 ? (
                  <div className="py-8 text-center text-sm text-ink-muted">
                    Обращений в этом месяце пока нет.
                  </div>
                ) : (
                  <div className="h-72 w-full">
                    <ResponsiveContainer width="100%" height="100%">
                      <PieChart>
                        <Tooltip
                          contentStyle={{
                            background: '#fff',
                            border: '1px solid #e2e8f0',
                            borderRadius: 8,
                            fontSize: 12,
                          }}
                          formatter={(value: number) => [value, 'Обращений']}
                        />
                        <Pie
                          data={data.categories.map((c) => ({
                            name: c.name_translations.ru || c.slug,
                            value: c.count,
                          }))}
                          dataKey="value"
                          nameKey="name"
                          cx="50%"
                          cy="50%"
                          outerRadius={90}
                          innerRadius={45}
                          paddingAngle={2}
                        >
                          {data.categories.map((_, i) => (
                            <Cell
                              key={i}
                              fill={CATEGORY_COLORS[i % CATEGORY_COLORS.length]}
                            />
                          ))}
                        </Pie>
                      </PieChart>
                    </ResponsiveContainer>
                  </div>
                )}
              </Card>

              <Card title="Топ-5 направлений">
                <CategoryRanking categories={data.categories} />
              </Card>
            </div>
          </>
        )}
      </div>
    </Layout>
  )
}

function Kpi({
  label,
  value,
  colorClass,
}: {
  label: string
  value: number
  colorClass: string
}) {
  return (
    <div className="rounded-card border border-line bg-card p-5 shadow-card">
      <div className="text-xs font-medium uppercase tracking-widest text-ink-muted">
        {label}
      </div>
      <div className={cn('mt-2 text-3xl font-semibold tabular-nums', colorClass)}>
        {value}
      </div>
    </div>
  )
}

function CategoryRanking({ categories }: { categories: CategoryPoint[] }) {
  const total = categories.reduce((sum, c) => sum + c.count, 0)
  const top5 = [...categories]
    .sort((a, b) => b.count - a.count)
    .slice(0, 5)
  if (total === 0) {
    return (
      <div className="py-8 text-center text-sm text-ink-muted">
        Нет данных за этот месяц.
      </div>
    )
  }
  return (
    <ul className="space-y-3">
      {top5.map((c, i) => {
        const pct = total ? Math.round((c.count / total) * 100) : 0
        return (
          <li key={c.id || c.slug} className="space-y-1">
            <div className="flex items-baseline justify-between text-sm">
              <span className="font-medium text-ink">
                {i + 1}. {c.name_translations.ru || c.slug}
              </span>
              <span className="text-ink-muted">
                {c.count} ({pct}%)
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface">
              <div
                className="h-full rounded-full bg-brand"
                style={{ width: `${pct}%` }}
              />
            </div>
          </li>
        )
      })}
    </ul>
  )
}
