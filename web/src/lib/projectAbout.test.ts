import { describe, expect, it } from 'vitest'

import {
  confirmKeyMatches,
  projectContext,
  projectAboutGate,
  projectSummaryRows,
  forgetProjectDraft,
  rememberProjectDraft,
  restoreProjectDraft,
  describeProjectBlastRadius,
  projectNameError,
  projectProfileDirty,
  projectProfilePatch,
  summarizeProjectDescription,
} from './projectAbout'

const project = { name: 'Подбор', description: 'старое' }

describe('projectProfilePatch', () => {
  it('меняли только имя — описание в тело не попадает', () => {
    expect(projectProfilePatch({ name: 'Новое', description: 'старое' }, project)).toEqual({
      name: 'Новое',
    })
  })

  it('очистка описания шлёт пустую строку, а НЕ null', () => {
    // null сервер понимает как «не менять» — описание не стёрлось бы никогда.
    expect(projectProfilePatch({ name: 'Подбор', description: '' }, project)).toEqual({
      description: '',
    })
  })

  it('без изменений тело не собирается вовсе', () => {
    expect(projectProfilePatch({ name: 'Подбор', description: 'старое' }, project)).toBeNull()
  })

  it('имя триммится, и пробельная правка изменением не считается', () => {
    expect(projectProfilePatch({ name: '  Подбор  ', description: 'старое' }, project)).toBeNull()
  })

  it('пустое имя не отправляется — его отвергнет валидатор формы', () => {
    expect(projectProfilePatch({ name: '   ', description: 'старое' }, project)).toBeNull()
  })

  it('null-описание на сервере равно пустой строке в форме', () => {
    const patch = projectProfilePatch(
      { name: 'П', description: '' },
      { name: 'П', description: null },
    )
    expect(patch).toBeNull()
  })

  it('хвостовой перенос строки — это изменение', () => {
    expect(projectProfileDirty({ name: 'Подбор', description: 'старое\n' }, project)).toBe(true)
  })
})

describe('projectNameError', () => {
  it.each([
    ['', 'пустым'],
    ['   ', 'пустым'],
    ['я'.repeat(256), '255'],
  ])('%o отвергается', (name, hint) => {
    expect(projectNameError(name)).toContain(hint)
  })

  it('нормальное имя проходит', () => {
    expect(projectNameError('Подбор')).toBeNull()
  })
})

describe('summarizeProjectDescription', () => {
  it('снимает заголовки и склеивает в строку', () => {
    expect(summarizeProjectDescription('## Заголовок\n\nтекст')).toBe('Заголовок текст')
  })

  it('от ссылки оставляет текст', () => {
    expect(summarizeProjectDescription('см. [доку](https://e.ru)')).toBe('см. доку')
  })

  it('вырезает блок кода', () => {
    expect(summarizeProjectDescription('до\n```\nкод\n```\nпосле')).toBe('до после')
  })

  it('режет по лимиту и ставит многоточие', () => {
    const long = summarizeProjectDescription('я'.repeat(20_000), 160)
    expect(long).toHaveLength(161)
    expect(long?.endsWith('…')).toBe(true)
  })

  it('пустое и null дают null', () => {
    expect(summarizeProjectDescription(null)).toBeNull()
    expect(summarizeProjectDescription('   ')).toBeNull()
  })
})

describe('confirmKeyMatches', () => {
  it.each(['plp', 'PLP', '  PLP  '])('%o подтверждает', (input) => {
    expect(confirmKeyMatches(input, 'PLP')).toBe(true)
  })

  it.each(['PL', 'PLP1', ''])('%o не подтверждает', (input) => {
    expect(confirmKeyMatches(input, 'PLP')).toBe(false)
  })
})

describe('describeProjectBlastRadius', () => {
  it('нули опускаются', () => {
    expect(describeProjectBlastRadius({ tasks: 3, attachments: 0 })).not.toContain('вложен')
  })

  it('пустой проект говорит об этом прямо', () => {
    expect(describeProjectBlastRadius({ tasks: 0, attachments: 0 })).toContain('пуст')
  })

  it('склоняет по числу', () => {
    expect(describeProjectBlastRadius({ tasks: 1, attachments: 0 })).toContain('задача')
    expect(describeProjectBlastRadius({ tasks: 5, attachments: 0 })).toContain('задач')
  })

  it('пустому проекту НЕ обещает удалить комментарии задач', () => {
    expect(describeProjectBlastRadius({ tasks: 0, attachments: 0 })).not.toContain('коммент')
  })

  it('непустому — обещает', () => {
    expect(describeProjectBlastRadius({ tasks: 4, attachments: 0 })).toContain('коммент')
  })
})

describe('черновик между переключениями вкладки', () => {
  it('без записи отдаёт значения проекта', () => {
    expect(restoreProjectDraft('p1', project)).toEqual({
      name: 'Подбор',
      description: 'старое',
    })
  })

  it('запомненный черновик переживает уход с вкладки', () => {
    rememberProjectDraft('p2', { name: 'Черновик', description: 'набрано' })
    expect(restoreProjectDraft('p2', project)).toEqual({
      name: 'Черновик',
      description: 'набрано',
    })
  })

  it('после сохранения черновик снимается', () => {
    rememberProjectDraft('p3', { name: 'Черновик', description: '' })
    forgetProjectDraft('p3')
    expect(restoreProjectDraft('p3', project).name).toBe('Подбор')
  })

  it('черновики не смешиваются между проектами', () => {
    rememberProjectDraft('p4', { name: 'Чужое', description: '' })
    expect(restoreProjectDraft('p5', project).name).toBe('Подбор')
  })

  it('null-описание превращается в пустую строку', () => {
    expect(restoreProjectDraft('p6', { name: 'П', description: null }).description).toBe('')
  })
})


describe('projectAboutGate', () => {
  const base = { archived_at: null, is_personal: false }

  it('владелец может всё', () => {
    const g = projectAboutGate({ ...base, can_edit: true, can_manage: true })
    expect(g).toMatchObject({
      canEditProfile: true,
      canImport: true,
      canArchive: true,
      canDelete: true,
      canOpenSettings: true,
      settingsLimitNote: null,
    })
  })

  it('редактор правит профиль, но не архивирует и не удаляет', () => {
    const g = projectAboutGate({ ...base, can_edit: true, can_manage: false })
    expect(g.canEditProfile).toBe(true)
    expect(g.canImport).toBe(true)
    expect(g.canArchive).toBe(false)
    expect(g.canDelete).toBe(false)
    expect(g.canOpenSettings).toBe(true)
    expect(g.settingsLimitNote).toContain('только владелец')
  })

  it('наблюдатель не видит кнопку настроек вовсе', () => {
    const g = projectAboutGate({ ...base, can_edit: false, can_manage: false })
    expect(g.canOpenSettings).toBe(false)
    expect(g.settingsLimitNote).toBeNull()
  })

  it('hub-admin вне членства — как владелец: функция не смотрит на my_role', () => {
    const g = projectAboutGate({ ...base, can_edit: true, can_manage: true })
    expect(g.canDelete).toBe(true)
  })

  it('личный проект: профиль правится, архив и удаление — нет', () => {
    const g = projectAboutGate({
      archived_at: null,
      is_personal: true,
      can_edit: true,
      can_manage: true,
    })
    expect(g.canEditProfile).toBe(true)
    expect(g.canArchive).toBe(false)
    expect(g.canDelete).toBe(false)
    // Владельцу личного «может только владелец» было бы враньём.
    expect(g.settingsLimitNote).toContain('Личное пространство')
  })

  it('архивный проект: импорта нет, разархивация есть', () => {
    const g = projectAboutGate({
      archived_at: '2026-08-01T00:00:00Z',
      is_personal: false,
      can_edit: true,
      can_manage: true,
    })
    expect(g.canImport).toBe(false)
    expect(g.canEditProfile).toBe(true)
    expect(g.canArchive).toBe(true)
  })

  it('архивный проект у редактора: только правка профиля', () => {
    const g = projectAboutGate({
      archived_at: '2026-08-01T00:00:00Z',
      is_personal: false,
      can_edit: true,
      can_manage: false,
    })
    expect(g.canEditProfile).toBe(true)
    expect(g.canImport).toBe(false)
    expect(g.canArchive).toBe(false)
  })

  it('отсутствующий is_personal трактуется как «не личный»', () => {
    const g = projectAboutGate({ archived_at: null, can_edit: true, can_manage: true })
    expect(g.canArchive).toBe(true)
    expect(g.canDelete).toBe(true)
  })

  it('противоречие can_edit:false + can_manage:true не прячет настройки', () => {
    const g = projectAboutGate({ ...base, can_edit: false, can_manage: true })
    expect(g.canEditProfile).toBe(false)
    expect(g.canOpenSettings).toBe(true)
  })
})

describe('projectSummaryRows', () => {
  const base = { key: 'PLP', createdLabel: '3 марта 2026 г.', memberCount: 3, ownerNames: ['Пётр'] }
  const labels = (rows: { label: string }[]) => rows.map((r) => r.label)
  const value = (rows: { label: string }[], label: string) =>
    (rows.find((r) => r.label === label) as { value?: string } | undefined)?.value

  it('без счётчиков рядов «Задач» и «Выполнено» нет вовсе', () => {
    const rows = projectSummaryRows({ ...base, task_count: undefined })
    expect(labels(rows)).not.toContain('Задач')
    expect(labels(rows)).not.toContain('Выполнено')
  })

  it('ноль задач — это «Пока нет задач», а не пропуск', () => {
    const rows = projectSummaryRows({ ...base, task_count: 0, done_count: 0 })
    expect(value(rows, 'Задач')).toBe('Пока нет задач')
    // «0 из 0» — шум.
    expect(labels(rows)).not.toContain('Выполнено')
  })

  it('счётчики показываются вместе', () => {
    const rows = projectSummaryRows({ ...base, task_count: 214, done_count: 56 })
    expect(value(rows, 'Задач')).toContain('214')
    expect(value(rows, 'Выполнено')).toBe('56 из 214')
  })

  it('есть задачи, но нет done_count — ряда «Выполнено» нет', () => {
    const rows = projectSummaryRows({ ...base, task_count: 214, done_count: undefined })
    expect(labels(rows)).toContain('Задач')
    expect(labels(rows)).not.toContain('Выполнено')
  })

  it('участники ещё не пришли — ряд остаётся, значение ожидает', () => {
    const rows = projectSummaryRows({ ...base, memberCount: null })
    expect(rows.find((r) => r.label === 'Участников')?.kind).toBe('pending')
  })

  it('без владельцев ряда «Владелец» нет', () => {
    const rows = projectSummaryRows({ ...base, ownerNames: [] })
    expect(labels(rows)).not.toContain('Владелец')
  })

  it('несколько владельцев схлопываются', () => {
    const rows = projectSummaryRows({ ...base, ownerNames: ['Пётр', 'Аня'] })
    expect(value(rows, 'Владелец')).toBe('Пётр и ещё 1')
  })

  it('ключ всегда первый', () => {
    expect(projectSummaryRows({ ...base, task_count: 5 })[0]).toMatchObject({
      kind: 'key',
      value: 'PLP',
    })
  })
})


describe('projectContext', () => {
  const base = { task_count: undefined, done_count: undefined, description: null }

  it('без счётчиков часть про задачи отсутствует, а не пишет «0 задач»', () => {
    expect(projectContext(base)).toBe('')
  })

  it('ноль задач — это «Пока нет задач»', () => {
    expect(projectContext({ ...base, task_count: 0 })).toBe('Пока нет задач')
  })

  it('закрытые показываются только когда они есть', () => {
    expect(projectContext({ ...base, task_count: 12, done_count: 0 })).not.toContain('закрыто')
    expect(projectContext({ ...base, task_count: 12, done_count: 5 })).toContain('закрыто')
  })

  it('склонение по числу', () => {
    expect(projectContext({ ...base, task_count: 1 })).toContain('задача')
    expect(projectContext({ ...base, task_count: 12 })).toContain('задач')
  })

  it('описание идёт сводкой, а не целиком', () => {
    const out = projectContext({ ...base, task_count: 3, description: '## Заголовок\n\nтекст' })
    expect(out).toContain('Заголовок текст')
    expect(out).not.toContain('##')
  })

  it('части склеены через разделитель', () => {
    expect(projectContext({ ...base, task_count: 3, done_count: 1, description: 'суть' })).toBe(
      projectContext({ ...base, task_count: 3, done_count: 1, description: 'суть' })
        .split(' · ')
        .join(' · '),
    )
    expect(projectContext({ ...base, task_count: 3, description: 'суть' })).toContain(' · ')
  })
})
