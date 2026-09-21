import { describe, expect, it } from 'vitest'

import type { Me } from '@/hooks/useMe'

import {
  droppedSummary,
  fromTemplateReady,
  longDay,
  previewFacts,
  previewNotifyLine,
  previewWarnings,
  reportDescription,
  templateModeAvailable,
  templatePageGate,
  templateRowMeta,
  templatesNavVisible,
  type CopyPreview,
  type TemplateListItem,
} from './projectTemplates'
import { NBSP } from './typography'

/** `plural` ставит неразрывный пробел ровно между числом и словом. */
const nb = (s: string) => s.replace(/(\d) /g, `$1${NBSP}`)

function me(over: Partial<Me> = {}): Me {
  return {
    employee_id: 'e1',
    email: 'a@t.ru',
    full_name: 'А',
    tenant_id: 't',
    tenant_slug: 't',
    hub_role: 'member',
    can_create_projects: true,
    ...over,
  } as Me
}

function preview(over: Partial<CopyPreview> = {}): CopyPreview {
  return {
    tasks: 42,
    subtasks: 12,
    too_big: false,
    max_tasks: 2000,
    dropped: { archived: 0, orphan_subtasks: 0, recurrence_steps: 0 },
    dropped_people: [],
    attachments: 0,
    attachment_bytes: 0,
    members: 7,
    notify_people: 5,
    first_due: '2026-10-06',
    last_due: '2026-11-14',
    overdue_after_shift: 0,
    due_soon_reminders: 0,
    suggested_anchor_on: '2026-09-01',
    shift_days: 35,
    start_on: '2026-10-06',
    disk_ok: true,
    ...over,
  }
}

describe('входы в шаблоны', () => {
  it('пункт меню — модуль включён и человек создаёт проекты', () => {
    expect(templatesNavVisible(me({ features: { project_templates: true } }))).toBe(true)
    expect(templatesNavVisible(me({ features: { project_templates: false } }))).toBe(false)
    expect(
      templatesNavVisible(me({ can_create_projects: false, features: { project_templates: true } })),
    ).toBe(false)
  })

  it('hub-admin видит пункт и при выключенном модуле — там живёт тумблер', () => {
    expect(
      templatesNavVisible(me({ features: { project_templates: false, project_templates_admin: true } })),
    ).toBe(true)
    // …но режим «По шаблону» при выключенном модуле не предлагаем никому.
    expect(
      templateModeAvailable(me({ features: { project_templates: false, project_templates_admin: true } })),
    ).toBe(false)
  })

  it('старый бэкенд без features — выключено', () => {
    expect(templatesNavVisible(me())).toBe(false)
    expect(templatesNavVisible(undefined)).toBe(false)
  })
})

describe('строка библиотеки', () => {
  const item: TemplateListItem = {
    id: 't1',
    key: 'OT',
    name: 'Открытие точки',
    description: null,
    badge_emoji: null,
    badge_url: null,
    template_anchor_on: '2026-09-01',
    created_by: 'e1',
    author_name: 'Иванова А.',
    author_deleted: false,
    task_count: 42,
    attachment_count: 5,
    attachment_bytes: 1000,
    member_count: 3,
    use_count: 3,
    can_edit: true,
    updated_at: '2026-09-21T00:00:00Z',
  }

  it('задачи, вложения, автор, использования', () => {
    expect(templateRowMeta(item)).toBe(
      nb('42 задачи · 5 вложений · автор Иванова А. · использован 3 раза'),
    )
  })

  it('уволенный автор и нулевое использование', () => {
    expect(
      templateRowMeta({ ...item, attachment_count: 0, author_deleted: true, use_count: 0 }),
    ).toBe(nb('42 задачи · автор уволен — правит администратор · ещё не использован'))
  })
})

describe('предпросмотр', () => {
  it('факты: задачи с подзадачами, вложения, люди, сроки', () => {
    const lines = previewFacts(preview({ attachments: 5, attachment_bytes: 1.2 * 1024 ** 3 }))
    expect(lines[0]).toBe(nb('42 задачи и 12 подзадач'))
    // Объём — из `formatBytes`, там обычный пробел.
    expect(lines[1]).toBe(`${nb('5 вложений')} · 1.2 ГБ`)
    expect(lines[2]).toBe(nb('7 участников'))
    expect(lines[3]).toMatch(/^Сроки 6 окт — 14 нояб?$/)
  })

  it('уведомим — только если есть кого', () => {
    expect(previewNotifyLine(preview({ notify_people: 0 }))).toBeNull()
    expect(previewNotifyLine(preview())).toContain(nb('5 человек'))
  })

  it('предупреждения по важности: просрочка, уволенные, напоминания', () => {
    const w = previewWarnings(
      preview({
        overdue_after_shift: 8,
        due_soon_reminders: 4,
        dropped_people: [{ employee_id: 'x', name: 'Петров А.', tasks: 3 }],
      }),
    )
    expect(w.map((x) => x.tone)).toEqual(['red', 'amber', 'blue'])
    expect(w[0]!.text).toContain(nb('8 задач сразу будут просрочены'))
    expect(w[1]!.text).toContain('Петров А.')
  })

  it('«мало места» пропадает, когда вложения выключены', () => {
    const p = preview({ disk_ok: false })
    expect(previewWarnings(p).some((w) => w.text.includes('мало места'))).toBe(true)
    expect(previewWarnings(p, { includeAttachments: false })).toEqual([])
  })

  it('что не попадёт в шаблон', () => {
    expect(droppedSummary({ archived: 0, orphan_subtasks: 0, recurrence_steps: 0 })).toBeNull()
    expect(droppedSummary({ archived: 3, orphan_subtasks: 1, recurrence_steps: 2 })).toBe(
      nb('Не попадут: 3 архивные, 1 подзадача архивной задачи, 2 выполненных шага повтора.'),
    )
  })
})

describe('кнопка «Создать проект»', () => {
  const draft = { name: 'Невский, 10', templateId: 't1', includeAttachments: true }

  it('ждёт предпросмотр и имя', () => {
    expect(fromTemplateReady(draft, undefined)).toBe(false)
    expect(fromTemplateReady({ ...draft, name: '  ' }, preview())).toBe(false)
    expect(fromTemplateReady(draft, preview())).toBe(true)
  })

  it('зеркалит отказы сервера: потолок и место на диске', () => {
    expect(fromTemplateReady(draft, preview({ too_big: true }))).toBe(false)
    expect(fromTemplateReady(draft, preview({ disk_ok: false }))).toBe(false)
    // Без вложений место не нужно.
    expect(fromTemplateReady({ ...draft, includeAttachments: false }, preview({ disk_ok: false }))).toBe(
      true,
    )
  })

  it('старт в прошлом не блокирует (решение владельца 21.09)', () => {
    expect(fromTemplateReady(draft, preview({ overdue_after_shift: 8 }))).toBe(true)
  })
})

describe('страница шаблона', () => {
  it('прячет шаринг, звезду, дашборд и пресеты дат', () => {
    expect(templatePageGate({ is_template: true, can_edit: false })).toEqual({
      isTemplate: true,
      showShare: false,
      showFavorite: false,
      showDashboard: false,
      showDatePresets: false,
      canEditAnchor: false,
    })
    expect(templatePageGate({ is_template: true, can_edit: true }).canEditAnchor).toBe(true)
  })

  it('обычный проект не трогает; поле не пришло — не шаблон', () => {
    const g = templatePageGate({ can_edit: true })
    expect(g.isTemplate).toBe(false)
    expect(g.showShare && g.showFavorite && g.showDashboard && g.showDatePresets).toBe(true)
    expect(g.canEditAnchor).toBe(false)
  })
})

describe('тексты', () => {
  it('длинная дата без «г.»', () => {
    expect(longDay('2026-09-01')).toBe('1 сентября 2026')
  })

  it('отчёт после создания', () => {
    expect(
      reportDescription({
        tasks: 42,
        subtasks: 12,
        dropped: { archived: 0, orphan_subtasks: 0, recurrence_steps: 0 },
        dropped_people: [{ employee_id: 'x', name: 'Петров А.', tasks: 3 }],
        attachments_copied: 5,
        attachments_missing: 0,
        notified: 5,
      }),
    ).toBe(nb('54 задачи · не перенесены: Петров А. · уведомлено 5 человек'))
  })
})
