import { describe, expect, it } from 'vitest'

import {
  KIND_GROUP,
  NOTIFICATION_GROUP_ORDER,
  NOTIFICATION_KINDS,
  NOTIFICATION_KIND_LABEL,
} from './notificationKinds'

describe('справочник уведомлений', () => {
  it('у каждого вида есть подпись и раздел', () => {
    for (const kind of NOTIFICATION_KINDS) {
      expect(NOTIFICATION_KIND_LABEL[kind], kind).toBeTruthy()
      expect(NOTIFICATION_GROUP_ORDER, kind).toContain(KIND_GROUP[kind])
    }
  })

  it('в карте разделов ровно те же виды — ни одного лишнего', () => {
    expect(Object.keys(KIND_GROUP).sort()).toEqual([...NOTIFICATION_KINDS].sort())
  })
})
