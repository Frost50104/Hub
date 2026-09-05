import { describe, expect, it } from 'vitest'

import { renderActivity, type ActivityLike } from './taskActivity'

function act(kind: string, payload: Record<string, unknown> = {}): ActivityLike {
  return { kind, payload, actor_full_name: 'Пётр', actor_email: 'p@t.ru' }
}

describe('renderActivity', () => {
  it('выполнение и возврат в работу', () => {
    expect(renderActivity(act('done_changed', { done: true }))).toBe('Пётр выполнил задачу')
    expect(renderActivity(act('done_changed', { done: false }))).toBe(
      'Пётр вернул задачу в работу',
    )
  })

  it('перенос между колонками называет колонку', () => {
    expect(
      renderActivity(act('stage_changed', { stage_from: 'Идея', stage_to: 'Согласование' })),
    ).toBe('Пётр перенёс в «Согласование»')
  })

  it('пустой stage_to читается как снятие статуса, а не как перенос', () => {
    // Прочерк в поле «Статус» (0046): задача ушла с доски. «Перенёс задачу»
    // на этом месте врало бы — никуда её не переносили.
    expect(
      renderActivity(act('stage_changed', { stage_from: 'Идея', stage_to: null })),
    ).toBe('Пётр убрал статус')
    expect(renderActivity(act('stage_changed', {}))).toBe('Пётр убрал статус')
  })

  it('СТАРЫЕ записи со статусами читаются после смены модели', () => {
    // На проде таких 68: payload несёт системный статус, а не имя колонки.
    // Без словаря строка схлопывалась бы в «перевёл в «»».
    expect(renderActivity(act('status_changed', { old: 'todo', new: 'in_progress' }))).toBe(
      'Пётр перевёл в «В работе»',
    )
    expect(renderActivity(act('status_changed', { new: 'done' }))).toBe(
      'Пётр перевёл в «Готово»',
    )
  })

  it('старая запись с именем этапа предпочитает имя', () => {
    expect(
      renderActivity(act('status_changed', { new: 'in_review', stage_to: 'Проверка ТУ' })),
    ).toBe('Пётр перевёл в «Проверка ТУ»')
  })

  it('старая запись без опознавательных знаков не даёт пустых кавычек', () => {
    expect(renderActivity(act('status_changed', {}))).toBe('Пётр изменил статус')
  })

  it('комментарий рисуется сам, строкой ленты — нет', () => {
    expect(renderActivity(act('commented'))).toBeNull()
  })

  it('переезд называет прежний проект и прежний номер', () => {
    expect(
      renderActivity(
        act('moved', {
          from_project: 'Подбор',
          to_project: 'Развитие Hub',
          from_key: 'PLP-118',
          to_key: 'RH-12',
        }),
      ),
    ).toBe('Пётр перенёс задачу из «Подбор» — прежний номер PLP-118')
  })

  it('переезд без payload не выдумывает проект', () => {
    expect(renderActivity(act('moved', {}))).toBe('Пётр перенёс задачу в другой проект')
  })

  it('неизвестный вид не роняет ленту', () => {
    expect(renderActivity(act('teleported'))).toBe('Пётр: teleported')
  })
})

describe('renderActivity: наблюдатели (02.09)', () => {
  it('с payload — редактор подписал другого, без — подписался сам (легаси и /me)', () => {
    expect(renderActivity(act('watcher_added', { name: 'Ирина' }))).toBe(
      'Пётр подписал Ирина на задачу',
    )
    expect(renderActivity(act('watcher_added'))).toBe('Пётр подписался на задачу')
    expect(renderActivity(act('watcher_removed', { name: 'Ирина' }))).toBe(
      'Пётр снял Ирина с наблюдения',
    )
    expect(renderActivity(act('watcher_removed'))).toBe('Пётр отписался от задачи')
  })
})
