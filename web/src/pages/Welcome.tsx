import { useQuery } from '@tanstack/react-query'

import { api } from '@/lib/api'

type Me = {
  employee_id: string
  email: string
  full_name: string
  tenant_id: string
  tenant_slug: string
  hub_role: 'admin' | 'member' | 'viewer' | null
}

async function fetchMe(): Promise<Me> {
  const { data } = await api.get<Me>('/me')
  return data
}

export function Welcome() {
  const { data, isLoading, error } = useQuery({
    queryKey: ['me'],
    queryFn: fetchMe,
  })

  if (isLoading) {
    return <div className="p-8 text-text2">Загружаем профиль…</div>
  }

  if (error) {
    return (
      <div className="mx-auto max-w-xl space-y-4 p-8 text-center">
        <h2 className="font-display text-xl text-red">Не удалось загрузить профиль</h2>
        <p className="text-text2">{(error as Error).message}</p>
        <a className="inline-block rounded-lg border border-glass-border px-4 py-2 text-sm text-amber hover:bg-glass" href="/login">
          Войти заново
        </a>
      </div>
    )
  }

  if (!data) return null

  return (
    <div className="mx-auto max-w-2xl space-y-6 p-6">
      <header className="space-y-2">
        <h1 className="font-display text-3xl">Привет, {data.full_name}!</h1>
        <p className="text-text2">
          {data.hub_role
            ? 'Signaris Hub, Hub-MVP.1. Это страница приветствия — реальные функции (проекты, задачи, канбан) появятся в следующих фазах.'
            : 'У вашей организации пока нет доступа к Signaris Hub. Обратитесь к администратору в auth.signaris.ru, чтобы Hub появился в списке продуктов.'}
        </p>
      </header>

      <section className="glass space-y-3 p-6">
        <h2 className="font-display text-lg">Ваш профиль</h2>
        <dl className="grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 text-sm">
          <dt className="text-text2">Email</dt>
          <dd>{data.email}</dd>
          <dt className="text-text2">Tenant</dt>
          <dd>{data.tenant_slug}</dd>
          <dt className="text-text2">Tenant ID</dt>
          <dd className="font-mono text-xs">{data.tenant_id}</dd>
          <dt className="text-text2">Employee ID</dt>
          <dd className="font-mono text-xs">{data.employee_id}</dd>
          <dt className="text-text2">Роль в Hub</dt>
          <dd>
            {data.hub_role ? (
              <span className="rounded bg-amber/20 px-2 py-0.5 text-amber">
                {data.hub_role}
              </span>
            ) : (
              <span className="text-text3">нет доступа</span>
            )}
          </dd>
        </dl>
      </section>
    </div>
  )
}
