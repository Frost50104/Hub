import { api } from './api'

/**
 * Ассистент (волна 1). Журнал операций, а не чат: каждый оборот несёт вид
 * (`kind`) и блок (`data`), и рисуется своим компонентом.
 *
 * Живёт отдельно от `lib/learn.ts` сознательно: ассистент общий для двух
 * пространств, а learn-модуль тянет за собой весь учебный API.
 */

export type TurnKind = 'answer' | 'summary' | 'action' | 'report' | 'error' | 'denied'

export interface AssistantSource {
  title: string
  url_path: string
}

/** Поле карточки плана. `chip` меняет способ подачи значения. */
export interface PlanField {
  label: string
  value: string
  chip?: 'key' | 'who' | 'priority'
  chip_text?: string
}

export interface PlanStep {
  text: string
  state: 'done' | 'now' | 'wait'
}

export interface PlanResult {
  text: string
  url?: string
  link_text?: string
}

export interface Plan {
  id: string
  tool: string
  scope: string
  title: string
  fields: PlanField[]
  steps: PlanStep[]
  status: 'pending' | 'done' | 'rejected' | 'failed'
  result: PlanResult | null
  error: string | null
  expires_at: string
}

export interface DeniedData {
  reason: string
  who_can: { name: string; role: string }[]
}

/** Тело блока. Ключи взаимоисключающие — по одному на `kind`. */
export interface TurnData {
  plan?: Plan
  lines?: string[]
  reason?: string
  who_can?: { name: string; role: string }[]
  /** Снимок отчёта iiko на момент запроса. */
  report?: Report
}

export interface AssistantMessage {
  id: string
  role: 'user' | 'assistant'
  kind: TurnKind
  content: string
  sources: AssistantSource[] | null
  data: TurnData | null
  created_at: string
}

export interface AssistantTurn {
  conversation_id: string
  message_id: string
  kind: TurnKind
  content: string
  sources: AssistantSource[]
  data: TurnData | null
}

export interface AssistantConversation {
  id: string
  title: string
  updated_at: string
}

export interface AssistantStatus {
  configured: boolean
  provider: string | null
  /** Провайдер умеет вызывать инструменты — значит доступны действия. */
  can_act: boolean
}

export interface PlanPatchBody {
  title?: string
  due_at?: string
  priority?: 'low' | 'medium' | 'high' | 'urgent'
  assignees?: string[]
  text?: string
  clear_due?: boolean
}

export const assistantApi = {
  status: (): Promise<AssistantStatus> =>
    api.get<AssistantStatus>('/ai/status').then((r) => r.data),

  ask: (question: string, conversationId?: string | null): Promise<AssistantTurn> =>
    api
      .post<AssistantTurn>('/ai/ask', {
        question,
        conversation_id: conversationId ?? undefined,
      })
      .then((r) => r.data),

  conversations: (): Promise<AssistantConversation[]> =>
    api.get<AssistantConversation[]>('/ai/conversations').then((r) => r.data),

  messages: (conversationId: string): Promise<AssistantMessage[]> =>
    api
      .get<AssistantMessage[]>(`/ai/conversations/${conversationId}/messages`)
      .then((r) => r.data),

  deleteConversation: (conversationId: string): Promise<void> =>
    api.delete(`/ai/conversations/${conversationId}`).then(() => undefined),

  executePlan: (planId: string): Promise<Plan> =>
    api.post<Plan>(`/ai/plans/${planId}/execute`).then((r) => r.data),

  rejectPlan: (planId: string): Promise<Plan> =>
    api.post<Plan>(`/ai/plans/${planId}/reject`).then((r) => r.data),

  patchPlan: (planId: string, body: PlanPatchBody): Promise<Plan> =>
    api.patch<Plan>(`/ai/plans/${planId}`, body).then((r) => r.data),
}

/** Подпись оборота в журнале: «09:14 · действие». */
export const TURN_LABEL: Record<TurnKind, string> = {
  answer: 'ответ',
  summary: 'сводка',
  action: 'действие',
  report: 'отчёт',
  error: 'ошибка',
  denied: 'отказ по правам',
}

export function turnTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', {
    hour: '2-digit',
    minute: '2-digit',
  })
}

// ─── Отчёты iiko (волна 2) ──────────────────────────────────────────────────

export type ReportKind = 'revenue' | 'avg' | 'items' | 'peak' | 'writeoff'
export type ReportChart = 'bars' | 'hours' | 'lists'

export interface ReportStat {
  label: string
  value: string
  /** Значение — рост: набирается `--green-deep`, а не нейтралью. */
  positive: boolean
}

export interface ReportBar {
  name: string
  sum: string
  /** Доля от самой длинной полосы, 0..100. */
  pct: number
  delta: string
  /** Рост. Падение красным НЕ красится — красный занят просрочкой и ошибками. */
  up: boolean
}

export interface ReportHour {
  label: string
  pct: number
}

export interface ReportItem {
  name: string
  qty: string
  share: string
}

export interface Report {
  kind: ReportKind
  title: string
  chart: ReportChart
  subtitle: string
  period: { from: string; to: string }
  stats: ReportStat[]
  bars: ReportBar[]
  hours: ReportHour[]
  top: ReportItem[]
  anti: ReportItem[]
  note: string | null
  cached?: boolean
}

export interface ReportCatalog {
  configured: boolean
  reports: { key: ReportKind; title: string; chart: ReportChart }[]
}

export const reportsApi = {
  catalog: (): Promise<ReportCatalog> =>
    api.get<ReportCatalog>('/ai/reports').then((r) => r.data),

  get: (kind: ReportKind, from?: string, to?: string): Promise<Report> =>
    api
      .get<Report>(`/ai/reports/${kind}`, { params: { from, to } })
      .then((r) => r.data),

  /**
   * Тег <a href> не несёт Bearer — качаем blob через axios и отдаём
   * object-URL. Тот же приём, что у выгрузки learn-аналитики.
   */
  downloadCsv: async (kind: ReportKind, from?: string, to?: string): Promise<void> => {
    const resp = await api.get(`/ai/reports/${kind}/csv`, {
      params: { from, to },
      responseType: 'blob',
    })
    const url = URL.createObjectURL(resp.data as Blob)
    const a = document.createElement('a')
    a.href = url
    a.download = `iiko-${kind}-${from ?? 'период'}.csv`
    document.body.appendChild(a)
    a.click()
    a.remove()
    setTimeout(() => URL.revokeObjectURL(url), 60_000)
  },
}
