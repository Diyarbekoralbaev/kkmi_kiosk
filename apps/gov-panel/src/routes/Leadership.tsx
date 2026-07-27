import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Trash2 } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import {
  Button,
  Card,
  Dialog,
  EmptyState,
  FormField,
  Input,
  LoadingState,
  Select,
  Table,
  THead,
  TBody,
  TR,
  TH,
  TD,
  Textarea,
} from '../components/ui'
import { api, asApiError } from '../lib/api'

// Whoever appears here is exactly who the kiosk will offer for a reception —
// both the touch list and the agent's show_leadership read this table, and the
// agent is instructed never to name anyone outside it. An empty list therefore
// disables booking rather than letting the assistant improvise.

interface Official {
  id: string
  name: string
  position: string
  responsibilities: string
  reception_day: string
  reception_time: string
  order: number
  role: string
}

const DAYS = [
  { value: '', label: '— не указан —' },
  { value: 'mon', label: 'Понедельник' },
  { value: 'tue', label: 'Вторник' },
  { value: 'wed', label: 'Среда' },
  { value: 'thu', label: 'Четверг' },
  { value: 'fri', label: 'Пятница' },
  { value: 'sat', label: 'Суббота' },
  { value: 'sun', label: 'Воскресенье' },
]

const ROLES = [
  { value: 'chief', label: 'Ректор' },
  { value: 'deputy', label: 'Проректор / декан' },
]

const dayLabel = (v: string) => DAYS.find((d) => d.value === v)?.label ?? '—'

const EMPTY: Omit<Official, 'id'> = {
  name: '',
  position: '',
  responsibilities: '',
  reception_day: '',
  reception_time: '',
  order: 0,
  role: 'deputy',
}

export function LeadershipPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Official | null>(null)
  const [form, setForm] = useState<Omit<Official, 'id'>>(EMPTY)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')

  const { data, isLoading } = useQuery<{ items: Official[] }>({
    queryKey: ['gov-officials'],
    queryFn: async () => (await api.get('/api/gov/officials')).data,
  })

  const save = useMutation({
    mutationFn: async () => {
      if (editing) await api.patch(`/api/gov/officials/${editing.id}`, form)
      else await api.post('/api/gov/officials', form)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gov-officials'] })
      setOpen(false)
      setError('')
    },
    onError: (e) => setError(asApiError(e).message),
  })

  const remove = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/gov/officials/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['gov-officials'] }),
  })

  function openNew() {
    setEditing(null)
    setForm(EMPTY)
    setError('')
    setOpen(true)
  }

  function openEdit(o: Official) {
    setEditing(o)
    const { id: _id, ...rest } = o
    setForm(rest)
    setError('')
    setOpen(true)
  }

  return (
    <Layout>
      <PageHeader
        title="Руководство"
        description="Кто ведёт приём. Этот список киоск показывает посетителю и из него же ИИ-ассистент предлагает запись — никого другого он назвать не может."
        actions={
          <Button onClick={openNew}>
            <Plus className="mr-1 h-4 w-4" />
            Добавить
          </Button>
        }
      />
      <div className="p-8">
        <Card>
          {isLoading && <LoadingState />}
          {data && data.items.length === 0 && (
            <EmptyState
              title="Список пуст"
              description="Пока никто не добавлен, запись на приём в киоске недоступна."
            />
          )}
          {data && data.items.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Ф.И.О.</TH>
                  <TH>Должность</TH>
                  <TH>День приёма</TH>
                  <TH>Время</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {data.items.map((o) => (
                  <TR key={o.id}>
                    <TD className="font-medium text-ink">{o.name}</TD>
                    <TD>{o.position}</TD>
                    <TD>{dayLabel(o.reception_day)}</TD>
                    <TD>{o.reception_time || '—'}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" onClick={() => openEdit(o)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            if (confirm(`Удалить ${o.name}?`)) remove.mutate(o.id)
                          }}
                        >
                          <Trash2 className="h-4 w-4 text-danger" />
                        </Button>
                      </div>
                    </TD>
                  </TR>
                ))}
              </TBody>
            </Table>
          )}
        </Card>
      </div>

      <Dialog
        open={open}
        onClose={() => setOpen(false)}
        title={editing ? 'Изменить' : 'Добавить'}
      >
        <div className="space-y-4">
          <FormField label="Ф.И.О.">
            <Input
              value={form.name}
              onChange={(e) => setForm({ ...form, name: e.target.value })}
              placeholder="Ниязов Бахтияр Каримович"
            />
          </FormField>
          <FormField label="Должность">
            <Input
              value={form.position}
              onChange={(e) => setForm({ ...form, position: e.target.value })}
              placeholder="Ректор"
            />
          </FormField>
          <FormField label="Роль">
            <Select
              value={form.role}
              onChange={(e) => setForm({ ...form, role: e.target.value })}
            >
              {ROLES.map((r) => (
                <option key={r.value} value={r.value}>
                  {r.label}
                </option>
              ))}
            </Select>
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="День приёма">
              <Select
                value={form.reception_day}
                onChange={(e) =>
                  setForm({ ...form, reception_day: e.target.value })
                }
              >
                {DAYS.map((d) => (
                  <option key={d.value} value={d.value}>
                    {d.label}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Время">
              <Input
                value={form.reception_time}
                onChange={(e) =>
                  setForm({ ...form, reception_time: e.target.value })
                }
                placeholder="14:00 – 17:00"
              />
            </FormField>
          </div>
          <FormField label="Круг вопросов">
            <Textarea
              value={form.responsibilities}
              onChange={(e) =>
                setForm({ ...form, responsibilities: e.target.value })
              }
              placeholder="Учебный процесс, академическая задолженность…"
            />
          </FormField>
          <FormField label="Порядок в списке">
            <Input
              type="number"
              value={String(form.order)}
              onChange={(e) =>
                setForm({ ...form, order: Number(e.target.value) || 0 })
              }
            />
          </FormField>

          {error && <p className="text-sm text-danger">{error}</p>}

          <div className="flex justify-end gap-2 pt-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() => save.mutate()}
              disabled={save.isPending || !form.name || !form.position}
            >
              Сохранить
            </Button>
          </div>
        </div>
      </Dialog>
    </Layout>
  )
}
