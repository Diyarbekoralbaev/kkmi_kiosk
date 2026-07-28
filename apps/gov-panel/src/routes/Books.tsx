import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { Pencil, Plus, Search, Trash2 } from 'lucide-react'
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

// The catalogue is the only kiosk dataset with no upstream — IRBIS was never
// reachable from outside the institute network, so what is typed here IS the
// library as far as the kiosk and the AI assistant are concerned. A book that
// is not in this table does not exist to them: the agent is instructed to say
// the institute does not have it rather than answer from its own knowledge.

interface Book {
  id: string
  title: string
  authors: string
  year: number | null
  publisher: string
  isbn: string
  language: string
  section: string
  copies: number
  shelf: string
  description: string
  available: boolean
}

// Must match domain/library.SECTIONS — the kiosk browses by these keys.
const SECTIONS = [
  { value: 'anatomy', label: 'Анатомия' },
  { value: 'physiology', label: 'Физиология' },
  { value: 'biochemistry', label: 'Биохимия' },
  { value: 'pharmacology', label: 'Фармакология' },
  { value: 'pathology', label: 'Патология' },
  { value: 'microbiology', label: 'Микробиология' },
  { value: 'internal_medicine', label: 'Внутренние болезни' },
  { value: 'surgery', label: 'Хирургия' },
  { value: 'pediatrics', label: 'Педиатрия' },
  { value: 'obstetrics', label: 'Акушерство и гинекология' },
  { value: 'dentistry', label: 'Стоматология' },
  { value: 'nursing', label: 'Сестринское дело' },
  { value: 'public_health', label: 'Общественное здоровье' },
  { value: 'reference', label: 'Справочники' },
  { value: 'other', label: 'Прочее' },
]

const LANGUAGES = [
  { value: 'kk', label: 'Каракалпакский' },
  { value: 'uz', label: 'Узбекский' },
  { value: 'ru', label: 'Русский' },
  { value: 'en', label: 'Английский' },
]

const sectionLabel = (v: string) =>
  SECTIONS.find((s) => s.value === v)?.label ?? v
const languageLabel = (v: string) =>
  LANGUAGES.find((l) => l.value === v)?.label ?? v

type BookForm = Omit<Book, 'id' | 'year'> & { year: string }

const EMPTY: BookForm = {
  title: '',
  authors: '',
  year: '',
  publisher: '',
  isbn: '',
  language: 'ru',
  section: 'other',
  copies: 1,
  shelf: '',
  description: '',
  available: true,
}

export function BooksPage() {
  const qc = useQueryClient()
  const [editing, setEditing] = useState<Book | null>(null)
  const [form, setForm] = useState<BookForm>(EMPTY)
  const [open, setOpen] = useState(false)
  const [error, setError] = useState('')
  const [search, setSearch] = useState('')
  const [section, setSection] = useState('')

  const { data, isLoading } = useQuery<{ items: Book[]; total: number }>({
    queryKey: ['gov-books', search, section],
    queryFn: async () => {
      const params = new URLSearchParams({ limit: '500' })
      if (search.trim()) params.set('q', search.trim())
      if (section) params.set('section', section)
      return (await api.get(`/api/gov/books?${params}`)).data
    },
  })

  const save = useMutation({
    mutationFn: async () => {
      // The API takes year as int|null; an empty box means "not recorded",
      // which is a legitimate state here rather than a validation failure.
      const payload = {
        ...form,
        year: form.year.trim() ? Number(form.year) : null,
        copies: Number(form.copies) || 0,
      }
      if (editing) await api.patch(`/api/gov/books/${editing.id}`, payload)
      else await api.post('/api/gov/books', payload)
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gov-books'] })
      setOpen(false)
      setError('')
    },
    onError: (e) => setError(asApiError(e).message),
  })

  const remove = useMutation({
    mutationFn: async (id: string) => {
      await api.delete(`/api/gov/books/${id}`)
    },
    onSuccess: () => qc.invalidateQueries({ queryKey: ['gov-books'] }),
  })

  function openNew() {
    setEditing(null)
    setForm(EMPTY)
    setError('')
    setOpen(true)
  }

  function openEdit(b: Book) {
    setEditing(b)
    const { id: _id, year, ...rest } = b
    setForm({ ...rest, year: year === null ? '' : String(year) })
    setError('')
    setOpen(true)
  }

  return (
    <Layout>
      <PageHeader
        title="Библиотека"
        description="Каталог книг института. Киоск и ИИ-ассистент отвечают только по этому списку — книги, которой здесь нет, для них не существует."
        actions={
          <Button onClick={openNew}>
            <Plus className="mr-1 h-4 w-4" />
            Добавить книгу
          </Button>
        }
      />
      <div className="space-y-4 p-8">
        <Card className="p-4">
          <div className="flex flex-wrap items-center gap-3">
            <div className="relative min-w-[280px] flex-1">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-ink-muted" />
              <Input
                className="pl-9"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Название, автор или ISBN"
              />
            </div>
            <Select
              value={section}
              onChange={(e) => setSection(e.target.value)}
              className="min-w-[220px]"
            >
              <option value="">Все разделы</option>
              {SECTIONS.map((s) => (
                <option key={s.value} value={s.value}>
                  {s.label}
                </option>
              ))}
            </Select>
            {data && (
              <span className="text-sm text-ink-muted">
                Всего: {data.total}
              </span>
            )}
          </div>
        </Card>

        <Card>
          {isLoading && <LoadingState />}
          {data && data.items.length === 0 && (
            <EmptyState
              title="Каталог пуст"
              description={
                search || section
                  ? 'По этому запросу ничего не найдено.'
                  : 'Пока не добавлено ни одной книги — в киоске раздел «ИИ-библиотека» ничего не покажет.'
              }
            />
          )}
          {data && data.items.length > 0 && (
            <Table>
              <THead>
                <TR>
                  <TH>Название</TH>
                  <TH>Автор</TH>
                  <TH>Раздел</TH>
                  <TH>Язык</TH>
                  <TH>Год</TH>
                  <TH>Полка</TH>
                  <TH>Экз.</TH>
                  <TH />
                </TR>
              </THead>
              <TBody>
                {data.items.map((b) => (
                  <TR key={b.id}>
                    <TD className="font-medium text-ink">{b.title}</TD>
                    <TD>{b.authors || '—'}</TD>
                    <TD>{sectionLabel(b.section)}</TD>
                    <TD>{languageLabel(b.language)}</TD>
                    <TD>{b.year ?? '—'}</TD>
                    {/* Empty shelf is the field most worth chasing: without it
                        the assistant can name the book but not send anyone to
                        it, so it is called out rather than shown as a dash. */}
                    <TD>
                      {b.shelf || (
                        <span className="text-warning">не указана</span>
                      )}
                    </TD>
                    <TD>{b.copies}</TD>
                    <TD className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button variant="ghost" onClick={() => openEdit(b)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          onClick={() => {
                            if (confirm(`Удалить «${b.title}»?`)) remove.mutate(b.id)
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
        title={editing ? 'Изменить книгу' : 'Добавить книгу'}
      >
        <div className="space-y-4">
          <FormField label="Название">
            <Input
              value={form.title}
              onChange={(e) => setForm({ ...form, title: e.target.value })}
              placeholder="Анатомия человека"
            />
          </FormField>
          <FormField label="Автор(ы)">
            <Input
              value={form.authors}
              onChange={(e) => setForm({ ...form, authors: e.target.value })}
              placeholder="М.Р. Сапин, Г.Л. Билич"
            />
          </FormField>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Раздел">
              <Select
                value={form.section}
                onChange={(e) => setForm({ ...form, section: e.target.value })}
              >
                {SECTIONS.map((s) => (
                  <option key={s.value} value={s.value}>
                    {s.label}
                  </option>
                ))}
              </Select>
            </FormField>
            <FormField label="Язык книги">
              <Select
                value={form.language}
                onChange={(e) => setForm({ ...form, language: e.target.value })}
              >
                {LANGUAGES.map((l) => (
                  <option key={l.value} value={l.value}>
                    {l.label}
                  </option>
                ))}
              </Select>
            </FormField>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Год издания">
              <Input
                value={form.year}
                onChange={(e) => setForm({ ...form, year: e.target.value })}
                placeholder="2019"
              />
            </FormField>
            <FormField label="Издательство">
              <Input
                value={form.publisher}
                onChange={(e) => setForm({ ...form, publisher: e.target.value })}
                placeholder="ГЭОТАР-Медиа"
              />
            </FormField>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <FormField label="Полка">
              <Input
                value={form.shelf}
                onChange={(e) => setForm({ ...form, shelf: e.target.value })}
                placeholder="A-3"
              />
            </FormField>
            <FormField label="Экземпляров">
              <Input
                type="number"
                value={String(form.copies)}
                onChange={(e) =>
                  setForm({ ...form, copies: Number(e.target.value) })
                }
              />
            </FormField>
          </div>
          <FormField label="ISBN">
            <Input
              value={form.isbn}
              onChange={(e) => setForm({ ...form, isbn: e.target.value })}
              placeholder="978-5-9704-4870-1"
            />
          </FormField>
          <FormField label="О книге">
            <Textarea
              rows={3}
              value={form.description}
              onChange={(e) =>
                setForm({ ...form, description: e.target.value })
              }
              placeholder="Одно-два предложения о содержании — ассистент перескажет их посетителю."
            />
          </FormField>
          <label className="flex items-center gap-2 text-sm text-ink">
            <input
              type="checkbox"
              checked={form.available}
              onChange={(e) =>
                setForm({ ...form, available: e.target.checked })
              }
            />
            Есть в наличии
          </label>

          {error && <p className="text-sm text-danger">{error}</p>}

          <div className="flex justify-end gap-3 pt-2">
            <Button variant="ghost" onClick={() => setOpen(false)}>
              Отмена
            </Button>
            <Button
              onClick={() => save.mutate()}
              disabled={!form.title.trim() || save.isPending}
            >
              Сохранить
            </Button>
          </div>
        </div>
      </Dialog>
    </Layout>
  )
}
