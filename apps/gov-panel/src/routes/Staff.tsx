import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Plus, KeyRound } from 'lucide-react'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import {
  Badge,
  Button,
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
  TR,
} from '../components/ui'

type Role = 'org_admin' | 'reviewer'

const ROLE_LABEL_RU: Record<Role, string> = {
  org_admin: 'Администратор',
  reviewer: 'Ответственный',
}

interface StaffRow {
  id: string
  email: string
  full_name: string
  role: Role
  status: string
  totp_enabled: boolean
  last_login_at: string | null
  created_at: string
}

export function StaffPage() {
  const qc = useQueryClient()
  const [showCreate, setShowCreate] = useState(false)
  const [tempPwd, setTempPwd] = useState<{
    email: string
    pwd: string
  } | null>(null)
  const { data, isLoading } = useQuery({
    queryKey: ['gov-staff'],
    queryFn: async () =>
      (
        await api.get<{ items: StaffRow[]; total: number }>(
          '/api/gov/staff',
        )
      ).data,
  })

  const reset = useMutation({
    mutationFn: async (id: string) =>
      (
        await api.post<{ temp_password: string }>(
          `/api/gov/staff/${id}/password/reset`,
        )
      ).data,
    onError: (err) => toast.error(asApiError(err).message),
  })

  const toggle = useMutation({
    mutationFn: async ({ id, status }: { id: string; status: string }) =>
      api.patch(`/api/gov/staff/${id}`, {
        status: status === 'active' ? 'disabled' : 'active',
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['gov-staff'] }),
    onError: (err) => toast.error(asApiError(err).message),
  })

  const changeRole = useMutation({
    mutationFn: async ({ id, role }: { id: string; role: Role }) =>
      api.patch(`/api/gov/staff/${id}`, { role }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['gov-staff'] })
      toast.success('Сохранено')
    },
    onError: (err) => toast.error(asApiError(err).message),
  })

  return (
    <Layout>
      <PageHeader
        title="Сотрудники"
        description="Учётные записи сотрудников, имеющих доступ к панели института."
        actions={
          <Button
            onClick={() => setShowCreate(true)}
            leftIcon={<Plus className="h-4 w-4" />}
          >
            Новый сотрудник
          </Button>
        }
      />
      <div className="px-8 py-6">
        {isLoading ? (
          <LoadingState />
        ) : !data || data.items.length === 0 ? (
          <EmptyState
            title="Сотрудников нет"
            description="Нажмите «Новый сотрудник», чтобы добавить первого."
          />
        ) : (
          <Table>
            <THead>
              <tr>
                <TH>Email</TH>
                <TH>ФИО</TH>
                <TH>Роль</TH>
                <TH>Статус</TH>
                <TH>MFA</TH>
                <TH>Действия</TH>
              </tr>
            </THead>
            <TBody>
              {data.items.map((u) => (
                <TR key={u.id}>
                  <TD className="font-medium text-ink">{u.email}</TD>
                  <TD className="text-ink-muted">{u.full_name}</TD>
                  <TD>
                    <Select
                      value={u.role}
                      onChange={(e) =>
                        changeRole.mutate({
                          id: u.id,
                          role: e.target.value as Role,
                        })
                      }
                      className="!h-8 !py-0"
                    >
                      <option value="org_admin">{ROLE_LABEL_RU.org_admin}</option>
                      <option value="reviewer">{ROLE_LABEL_RU.reviewer}</option>
                    </Select>
                  </TD>
                  <TD>
                    <button
                      onClick={() =>
                        toggle.mutate({ id: u.id, status: u.status })
                      }
                      title="Переключить статус"
                    >
                      <Badge
                        tone={u.status === 'active' ? 'success' : 'danger'}
                      >
                        {u.status === 'active' ? 'Активный' : 'Отключён'}
                      </Badge>
                    </button>
                  </TD>
                  <TD>
                    {u.totp_enabled ? (
                      <Badge tone="success">вкл</Badge>
                    ) : (
                      <Badge tone="neutral">выкл</Badge>
                    )}
                  </TD>
                  <TD>
                    <Button
                      variant="ghost"
                      size="sm"
                      leftIcon={<KeyRound className="h-3 w-3" />}
                      onClick={async () => {
                        const r = await reset.mutateAsync(u.id)
                        setTempPwd({ email: u.email, pwd: r.temp_password })
                      }}
                    >
                      Сбросить пароль
                    </Button>
                  </TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </div>
      {showCreate && (
        <CreateForm
          onClose={() => setShowCreate(false)}
          onCreated={(p) =>
            setTempPwd({ email: p.email, pwd: p.temp_password })
          }
        />
      )}
      {tempPwd && (
        <Dialog
          open
          onClose={() => setTempPwd(null)}
          title="Временный пароль"
          size="sm"
          footer={<Button onClick={() => setTempPwd(null)}>Закрыть</Button>}
        >
          <div className="mb-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-800">
            Этот пароль показывается ровно один раз. Передайте его сотруднику{' '}
            {tempPwd.email}.
          </div>
          <code className="block rounded-lg border border-line bg-surface px-3 py-2 font-mono text-sm">
            {tempPwd.pwd}
          </code>
        </Dialog>
      )}
    </Layout>
  )
}

function CreateForm({
  onClose,
  onCreated,
}: {
  onClose: () => void
  onCreated: (p: { email: string; temp_password: string }) => void
}) {
  const qc = useQueryClient()
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [role, setRole] = useState<Role>('reviewer')
  const create = useMutation({
    mutationFn: async () =>
      (
        await api.post<{ email: string; temp_password: string }>(
          '/api/gov/staff',
          { email, full_name: name, role },
        )
      ).data,
    onSuccess: (data) => {
      qc.invalidateQueries({ queryKey: ['gov-staff'] })
      onCreated(data)
      onClose()
    },
    onError: (err) => toast.error(asApiError(err).message),
  })
  return (
    <Dialog
      open
      onClose={onClose}
      title="Новый сотрудник"
      size="sm"
      footer={
        <>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button onClick={() => create.mutate()} loading={create.isPending}>
            Создать
          </Button>
        </>
      }
    >
      <form
        onSubmit={(e) => {
          e.preventDefault()
          create.mutate()
        }}
        className="space-y-3"
      >
        <FormField label="Email">
          <Input
            type="email"
            required
            placeholder="user@example.com"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
          />
        </FormField>
        <FormField label="ФИО">
          <Input
            placeholder="Фамилия Имя Отчество"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </FormField>
        <FormField
          label="Роль"
          hint={
            role === 'reviewer'
              ? 'Видит только назначенные ему обращения / приёмы.'
              : 'Полный доступ к панели и распределению задач.'
          }
        >
          <Select value={role} onChange={(e) => setRole(e.target.value as Role)}>
            <option value="reviewer">{ROLE_LABEL_RU.reviewer}</option>
            <option value="org_admin">{ROLE_LABEL_RU.org_admin}</option>
          </Select>
        </FormField>
      </form>
    </Dialog>
  )
}
