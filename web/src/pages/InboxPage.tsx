import { Inbox } from 'lucide-react'

export function InboxPage() {
  return (
    <div className="mx-auto max-w-2xl space-y-4 p-6">
      <header>
        <h1 className="font-display text-2xl font-semibold">Входящие</h1>
        <p className="text-sm text-text2">
          Уведомления о назначениях, упоминаниях и просроченных задачах.
        </p>
      </header>

      <div className="glass flex flex-col items-center gap-3 p-12 text-center">
        <Inbox className="h-10 w-10 text-text3" />
        <p className="font-display text-base font-semibold text-text">
          Здесь будут уведомления
        </p>
        <p className="max-w-md text-sm text-text2">
          Подключение Web Push и in-app inbox запланировано в Hub-MVP.4:
          @упоминания в комментариях, назначения на задачу, изменения статуса
          у задач, за которыми вы следите, напоминания о дедлайнах за 24 ч.
        </p>
      </div>
    </div>
  )
}
