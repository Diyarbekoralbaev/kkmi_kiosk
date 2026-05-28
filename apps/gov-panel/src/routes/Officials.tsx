import { useRef, useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus, Pencil, Trash2, Upload, X } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import {
  Avatar,
  Badge,
  Button,
  Card,
  Dialog,
  EmptyState,
  FormField,
  Input,
  LoadingState,
  Select,
  Table,
  TBody,
  TD,
  TH,
  THead,
  Textarea,
  TR,
} from '../components/ui'

interface Official {
  id: string
  name: string
  position: string
  responsibilities: string
  reception_day: string
  reception_time: string
  order: number
  role: 'chief' | 'deputy'
  has_photo: boolean
}

const DAY_OPTS: { value: string; label: string }[] = [
  { value: '', label: '—' },
  { value: 'mon', label: 'Du' },
  { value: 'tue', label: 'Se' },
  { value: 'wed', label: 'Cho' },
  { value: 'thu', label: 'Pa' },
  { value: 'fri', label: 'Ju' },
  { value: 'sat', label: 'Sha' },
  { value: 'sun', label: 'Ya' },
]

const DAY_LABEL: Record<string, string> = Object.fromEntries(
  DAY_OPTS.filter((o) => o.value).map((o) => [o.value, o.label]),
)

function photoUrl(o: Official, version?: number): string {
  return `/api/public/officials/${o.id}/photo.jpg${version ? `?v=${version}` : ''}`
}

export function OfficialsPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Official | null>(null)
  const [creating, setCreating] = useState(false)
  const { data, isLoading } = useQuery({
    queryKey: ['officials'],
    queryFn: async () =>
      (
        await api.get<{ items: Official[]; total: number }>(
          '/api/gov/officials',
        )
      ).data,
  })

  const remove = useMutation({
    mutationFn: async (id: string) => api.delete(`/api/gov/officials/${id}`),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['officials'] })
      toast.success('Удалено')
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <Layout>
      <PageHeader
        title="Хокимы и заместители"
        description="ИИ-агент проговаривает гражданам этот список и часы приёма, и записывает к нужному лицу."
        actions={
          <Button
            onClick={() => setCreating(true)}
            leftIcon={<Plus className="h-4 w-4" />}
          >
            Новый
          </Button>
        }
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <LoadingState />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="Список пуст"
            description={'Нажмите «Новый», чтобы добавить первого должностного лица.'}
            action={
              <Button
                onClick={() => setCreating(true)}
                leftIcon={<Plus className="h-4 w-4" />}
              >
                Добавить
              </Button>
            }
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>Фото</TH>
                <TH>ФИО</TH>
                <TH>Должность</TH>
                <TH>Роль</TH>
                <TH>Направление</TH>
                <TH>Приём</TH>
                <TH className="text-right">Действия</TH>
              </tr>
            </THead>
            <TBody>
              {data.items.map((o) => (
                <TR key={o.id} className="align-top">
                  <TD>
                    <Avatar
                      src={o.has_photo ? photoUrl(o) : null}
                      name={o.name}
                      size={48}
                      tone={o.role === 'chief' ? 'accent' : 'brand'}
                    />
                  </TD>
                  <TD className="font-medium text-ink">{o.name}</TD>
                  <TD className="text-ink-muted">{o.position}</TD>
                  <TD>
                    <Badge tone={o.role === 'chief' ? 'accent' : 'neutral'}>
                      {o.role === 'chief' ? 'Хоким' : 'Заместитель'}
                    </Badge>
                  </TD>
                  <TD className="max-w-xs text-ink-muted">
                    {o.responsibilities || '—'}
                  </TD>
                  <TD className="whitespace-nowrap font-mono text-xs text-ink-muted">
                    {o.reception_day ? DAY_LABEL[o.reception_day] : ''}
                    {o.reception_time ? ` · ${o.reception_time}` : ''}
                    {!o.reception_day && !o.reception_time && '—'}
                  </TD>
                  <TD className="text-right">
                    <div className="flex justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setEditing(o)}
                        title="Редактировать"
                      >
                        <Pencil className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (confirm(`Удалить: ${o.name}?`))
                            remove.mutate(o.id)
                        }}
                        title="Удалить"
                        className="hover:bg-rose-50 hover:text-rose-700"
                      >
                        <Trash2 className="h-4 w-4" />
                      </Button>
                    </div>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
      {(editing || creating) && (
        <Editor
          official={editing}
          onClose={() => {
            setEditing(null)
            setCreating(false)
          }}
        />
      )}
    </Layout>
  )
}

function Editor({
  official,
  onClose,
}: {
  official: Official | null
  onClose: () => void
}) {
  const qc = useQueryClient()
  const [name, setName] = useState(official?.name ?? '')
  const [position, setPosition] = useState(official?.position ?? '')
  const [resp, setResp] = useState(official?.responsibilities ?? '')
  const [day, setDay] = useState(official?.reception_day ?? '')
  const [time, setTime] = useState(official?.reception_time ?? '')
  const [order, setOrder] = useState(official?.order ?? 0)
  const [role, setRole] = useState<'chief' | 'deputy'>(
    official?.role ?? 'deputy',
  )
  const [photoVersion, setPhotoVersion] = useState<number>(Date.now())
  const [hasPhoto, setHasPhoto] = useState<boolean>(
    official?.has_photo ?? false,
  )
  const fileRef = useRef<HTMLInputElement | null>(null)

  const save = useMutation({
    mutationFn: async () => {
      const body = {
        name,
        position,
        responsibilities: resp,
        reception_day: day,
        reception_time: time,
        order,
        role,
      }
      if (official) {
        await api.patch(`/api/gov/officials/${official.id}`, body)
      } else {
        await api.post('/api/gov/officials', body)
      }
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['officials'] })
      toast.success(official ? 'Сохранено' : 'Добавлено')
      onClose()
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  async function onPickPhoto(file: File) {
    if (!official) return
    if (file.size > 2 * 1024 * 1024) {
      toast.error('Размер фото не должен превышать 2 МБ')
      return
    }
    const fd = new FormData()
    fd.append('file', file)
    try {
      const res = await api.post<Official>(
        `/api/gov/officials/${official.id}/photo`,
        fd,
        { headers: { 'Content-Type': 'multipart/form-data' } },
      )
      setHasPhoto(res.data.has_photo)
      setPhotoVersion(Date.now())
      qc.invalidateQueries({ queryKey: ['officials'] })
      toast.success('Фото загружено')
    } catch (err) {
      toast.error(asApiError(err).message)
    }
  }

  async function onDeletePhoto() {
    if (!official || !hasPhoto) return
    if (!confirm('Удалить фото?')) return
    try {
      const res = await api.delete<Official>(
        `/api/gov/officials/${official.id}/photo`,
      )
      setHasPhoto(res.data.has_photo)
      setPhotoVersion(Date.now())
      qc.invalidateQueries({ queryKey: ['officials'] })
      toast.success('Фото удалено')
    } catch (err) {
      toast.error(asApiError(err).message)
    }
  }

  return (
    <Dialog
      open
      onClose={onClose}
      title={official ? 'Редактирование' : 'Новая запись'}
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => save.mutate()} loading={save.isPending}>
            Сохранить
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
        className="space-y-4"
      >
        {official && (
          <Card title="Фото" padding="tight">
            <div className="flex items-center gap-4">
              <Avatar
                key={photoVersion}
                src={hasPhoto ? `${photoUrl(official)}?v=${photoVersion}` : null}
                name={name || official.name}
                size={96}
                tone={role === 'chief' ? 'accent' : 'brand'}
              />
              <div className="flex flex-col gap-2">
                <input
                  ref={fileRef}
                  type="file"
                  accept="image/jpeg,image/png"
                  className="hidden"
                  onChange={(e) => {
                    const f = e.target.files?.[0]
                    if (f) onPickPhoto(f)
                    e.target.value = ''
                  }}
                />
                <Button
                  type="button"
                  size="sm"
                  onClick={() => fileRef.current?.click()}
                  leftIcon={<Upload className="h-4 w-4" />}
                >
                  {hasPhoto ? 'Заменить' : 'Загрузить фото'}
                </Button>
                {hasPhoto && (
                  <Button
                    type="button"
                    size="sm"
                    variant="secondary"
                    onClick={onDeletePhoto}
                    leftIcon={<X className="h-4 w-4" />}
                    className="border-rose-200 text-rose-700 hover:bg-rose-50"
                  >
                    Удалить
                  </Button>
                )}
              </div>
            </div>
            <p className="mt-3 text-xs text-ink-muted">
              JPEG или PNG, до 2 МБ. Фотопортрет.
            </p>
          </Card>
        )}

        <FormField label="ФИО полностью">
          <Input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-[2fr_1fr] gap-3">
          <FormField label="Должность">
            <Input
              required
              placeholder="Хоким, Первый заместитель, ..."
              value={position}
              onChange={(e) => setPosition(e.target.value)}
            />
          </FormField>
          <FormField label="Роль">
            <Select
              value={role}
              onChange={(e) => setRole(e.target.value as 'chief' | 'deputy')}
            >
              <option value="chief">Хоким (личный приём)</option>
              <option value="deputy">Заместитель</option>
            </Select>
          </FormField>
        </div>
        <FormField label="Направление">
          <Textarea
            rows={2}
            placeholder="Финансы, экономика, социальная сфера, ..."
            value={resp}
            onChange={(e) => setResp(e.target.value)}
          />
        </FormField>
        <div className="grid grid-cols-3 gap-3">
          <FormField label="День приёма">
            <Select value={day} onChange={(e) => setDay(e.target.value)}>
              {DAY_OPTS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </FormField>
          <FormField label="Время">
            <Input
              placeholder="10:00-12:00"
              value={time}
              onChange={(e) => setTime(e.target.value)}
            />
          </FormField>
          <FormField label="Порядок">
            <Input
              type="number"
              min={0}
              max={999}
              value={order}
              onChange={(e) => setOrder(parseInt(e.target.value || '0', 10))}
            />
          </FormField>
        </div>
        {!official && (
          <p className="text-xs text-ink-muted">
            Загрузить фото можно после сохранения — снова откройте запись.
          </p>
        )}
      </form>
    </Dialog>
  )
}
