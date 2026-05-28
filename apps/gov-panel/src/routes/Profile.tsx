import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { Layout } from '../components/Layout'
import { PageHeader } from '../components/PageHeader'
import { api, asApiError } from '../lib/api'
import { useAuth } from '../lib/auth'
import { Badge, Button, Card, FormField, Input } from '../components/ui'

export function ProfilePage() {
  const { me, refresh } = useAuth()
  const qc = useQueryClient()
  const setupQ = useQuery({
    queryKey: ['mfa-setup'],
    queryFn: async () =>
      (
        await api.post<{ secret: string; otpauth_uri: string }>(
          '/api/auth/mfa/setup',
        )
      ).data,
    enabled: false,
  })
  const enable = useMutation({
    mutationFn: async (code: string) =>
      api.post('/api/auth/mfa/enable', { code }),
    onSuccess: async () => {
      toast.success('MFA включена')
      await refresh()
      qc.removeQueries({ queryKey: ['mfa-setup'] })
    },
    onError: (err) => toast.error(asApiError(err).message),
  })
  const change = useMutation({
    mutationFn: async (vars: { current: string; next: string }) =>
      api.post('/api/auth/password/change', {
        current_password: vars.current,
        new_password: vars.next,
      }),
    onSuccess: () => toast.success('Пароль изменён'),
    onError: (err) => toast.error(asApiError(err).message),
  })
  const [code, setCode] = useState('')
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')

  return (
    <Layout>
      <PageHeader title="Профиль" description="Учётная запись и настройки безопасности." />
      <div className="max-w-xl space-y-6 px-8 py-6">
        <Card title="Профиль">
          <dl className="space-y-2 text-sm">
            <div className="flex justify-between gap-4">
              <dt className="text-ink-muted">Email</dt>
              <dd className="font-medium text-ink">{me?.email}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-muted">ФИО</dt>
              <dd className="font-medium text-ink">{me?.full_name}</dd>
            </div>
            <div className="flex justify-between gap-4">
              <dt className="text-ink-muted">MFA</dt>
              <dd>
                {me?.totp_enabled ? (
                  <Badge tone="success">включена</Badge>
                ) : (
                  <Badge tone="neutral">выключена</Badge>
                )}
              </dd>
            </div>
          </dl>
        </Card>
        {!me?.totp_enabled && (
          <Card title="Двухфакторная аутентификация (необязательно)">
            <p className="mb-4 text-sm text-ink-muted">
              Добавьте в приложение Authenticator (Google Authenticator, Authy).
            </p>
            {!setupQ.data ? (
              <Button
                onClick={() => setupQ.refetch()}
                loading={setupQ.isFetching}
              >
                Сгенерировать ключ
              </Button>
            ) : (
              <div className="space-y-3">
                <code className="block break-all rounded-lg border border-line bg-surface px-3 py-2 font-mono text-sm">
                  {setupQ.data.secret}
                </code>
                <code className="block break-all rounded-lg border border-line bg-surface px-3 py-2 font-mono text-xs">
                  {setupQ.data.otpauth_uri}
                </code>
                <FormField label="6-значный код">
                  <Input
                    inputMode="numeric"
                    maxLength={10}
                    placeholder="000000"
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                  />
                </FormField>
                <Button
                  onClick={() => enable.mutate(code)}
                  loading={enable.isPending}
                  className="w-full"
                >
                  Включить MFA
                </Button>
              </div>
            )}
          </Card>
        )}
        <Card title="Пароль">
          <form
            onSubmit={(e) => {
              e.preventDefault()
              change.mutate({ current, next })
              setCurrent('')
              setNext('')
            }}
            className="space-y-3"
          >
            <FormField label="Старый пароль">
              <Input
                type="password"
                value={current}
                onChange={(e) => setCurrent(e.target.value)}
                required
              />
            </FormField>
            <FormField label="Новый пароль (минимум 10 символов)">
              <Input
                type="password"
                value={next}
                onChange={(e) => setNext(e.target.value)}
                required
                minLength={10}
              />
            </FormField>
            <Button
              type="submit"
              loading={change.isPending}
              className="w-full"
            >
              Изменить пароль
            </Button>
          </form>
        </Card>
      </div>
    </Layout>
  )
}
