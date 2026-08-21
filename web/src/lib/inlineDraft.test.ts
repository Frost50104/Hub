import { describe, expect, it, vi } from 'vitest'

import { createInlineDraft } from './inlineDraft'

const flush = () => new Promise((r) => setTimeout(r, 0))

describe('createInlineDraft', () => {
  it('Enter коммитит и очищает; пробелы не коммитятся', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const onChange = vi.fn()
    const d = createInlineDraft({ submit, onChange })
    d.change('  ')
    d.enter()
    expect(submit).not.toHaveBeenCalled()
    d.change('Позвонить поставщику')
    d.enter()
    expect(d.value()).toBe('')
    await flush()
    expect(submit).toHaveBeenCalledWith('Позвонить поставщику')
    expect(onChange).toHaveBeenLastCalledWith('')
  })

  it('Enter → blur даёт один submit; Escape не коммитит', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const d = createInlineDraft({ submit, onChange: () => {} })
    d.change('A')
    d.enter()
    d.blur()
    await flush()
    expect(submit).toHaveBeenCalledTimes(1)
    d.change('B')
    d.escape()
    d.blur()
    d.unmount()
    await flush()
    expect(submit).toHaveBeenCalledTimes(1)
  })

  it('unmount коммитит непустой черновик', async () => {
    const submit = vi.fn().mockResolvedValue(undefined)
    const d = createInlineDraft({ submit, onChange: () => {} })
    d.change('Ушёл со страницы')
    d.unmount()
    await flush()
    expect(submit).toHaveBeenCalledWith('Ушёл со страницы')
  })

  it('ошибка возвращает текст только в пустое поле', async () => {
    const submit = vi.fn().mockRejectedValue(new Error('500'))
    const onChange = vi.fn()
    const d = createInlineDraft({ submit, onChange })
    d.change('Упала')
    d.enter()
    await flush()
    await flush()
    expect(d.value()).toBe('Упала')

    const submit2 = vi.fn().mockRejectedValue(new Error('500'))
    const d2 = createInlineDraft({ submit: submit2, onChange: () => {} })
    d2.change('Первая')
    d2.enter()
    d2.change('Вторая')
    await flush()
    await flush()
    expect(d2.value()).toBe('Вторая')
  })

  it('submit-ы идут по очереди в порядке ввода', async () => {
    const order: string[] = []
    let release: (() => void) | null = null
    const submit = vi.fn((title: string) => {
      order.push(`start:${title}`)
      return new Promise<void>((resolve) => {
        const done = () => {
          order.push(`end:${title}`)
          resolve()
        }
        if (title === 'Первая') release = done
        else done()
      })
    })
    const d = createInlineDraft({ submit, onChange: () => {} })
    d.change('Первая')
    d.enter()
    d.change('Вторая')
    d.enter()
    await flush()
    expect(order).toEqual(['start:Первая'])
    release!()
    await flush()
    await flush()
    expect(order).toEqual(['start:Первая', 'end:Первая', 'start:Вторая', 'end:Вторая'])
  })
})
