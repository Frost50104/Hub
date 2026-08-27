import { describe, expect, it } from 'vitest'

import { describeTaskDeletion } from './taskDeletion'
import { NBSP } from './typography'

describe('describeTaskDeletion', () => {
  it('без подзадач — только о необратимости', () => {
    const text = describeTaskDeletion(0)
    expect(text).toContain('восстановить будет нельзя')
    expect(text).not.toContain('подзадач')
  })

  it('одна подзадача склоняется правильно — и число, и глагол', () => {
    const text = describeTaskDeletion(1)
    expect(text).toContain(`1${NBSP}подзадача удалится`)
    expect(text).not.toContain('удалятся')
  })

  it('несколько подзадач', () => {
    expect(describeTaskDeletion(5)).toContain(`5${NBSP}подзадач удалятся`)
    expect(describeTaskDeletion(3)).toContain(`3${NBSP}подзадачи удалятся`)
  })

  it('«вместе с ней» не повторяется дважды', () => {
    const text = describeTaskDeletion(2)
    expect(text.match(/вместе с ней/g)).toHaveLength(1)
  })

  it('о комментариях и вложениях говорит всегда', () => {
    for (const n of [0, 1, 7]) {
      expect(describeTaskDeletion(n)).toContain('вложения')
    }
  })
})
