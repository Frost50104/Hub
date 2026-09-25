import { describe, expect, it } from 'vitest'

import { buildSwDiag, DIAG_MAX_BYTES, diagByteLength, sendSwDiag, type SwDiagInput } from './swDiag'

const NOW = 1_700_000_000_000

function input(over: Partial<SwDiagInput> = {}): SwDiagInput {
  return {
    kind: 'update_click',
    now: NOW,
    loadedVersion: 'aaaaaaa-20260925-100000',
    serverVersion: 'bbbbbbb-20260925-110000',
    mode: 'production',
    ua: 'Mozilla/5.0 (Macintosh) Safari',
    standalone: false,
    online: true,
    visible: true,
    path: '/my',
    pageLoadedAt: NOW - 12_345,
    snapshot: { supported: true, controlled: true, active: true, waiting: false, installing: true },
    health: 'hung',
    probeStartedAt: NOW - 25_000,
    hungAt: NOW - 5_000,
    lookupTimedOut: false,
    click: {
      action: 'reload',
      totalMs: 1234.6,
      steps: [
        { name: 'lookup', ms: 12.2, result: 'ok' },
        { name: 'version', ms: 80, result: 'ok' },
      ],
    },
    ...over,
  }
}

describe('buildSwDiag', () => {
  it('собирает payload с `kind` (не `event`), snake_case и целыми миллисекундами', () => {
    const p = buildSwDiag(input())
    expect(p.kind).toBe('update_click')
    expect('event' in p).toBe(false)
    expect(p.ts).toBe(new Date(NOW).toISOString())
    expect(p.env.page_age_ms).toBe(12_345)
    expect(p.sw.probe_age_ms).toBe(25_000)
    expect(p.sw.hung_after_ms).toBe(7_345)
    expect(p.click?.total_ms).toBe(1235)
    expect(p.click?.steps[0]).toEqual({ name: 'lookup', ms: 12, result: 'ok' })
  })

  it('без клика и без пробы — null-поля, без ключа click', () => {
    const p = buildSwDiag(input({ kind: 'sw_hung', click: undefined, probeStartedAt: null, hungAt: null }))
    expect(p.click).toBeUndefined()
    expect(p.sw.probe_age_ms).toBeNull()
    expect(p.sw.hung_after_ms).toBeNull()
  })

  it('режет user-agent и путь, укладывается в потолок', () => {
    const p = buildSwDiag(input({ ua: 'x'.repeat(1000), path: `/${'y'.repeat(1000)}` }))
    expect(p.env.ua).toHaveLength(200)
    expect(p.env.path).toHaveLength(200)
    expect(diagByteLength(p)).toBeLessThanOrEqual(DIAG_MAX_BYTES)
  })
})

describe('sendSwDiag', () => {
  it('без токена не шлёт; с токеном — keepalive POST с Bearer и X-Auth-Mode', () => {
    const calls: unknown[] = []
    const fetchImpl = (url: string, init: unknown) => {
      calls.push([url, init])
      return Promise.resolve()
    }
    sendSwDiag(buildSwDiag(input()), null, fetchImpl)
    expect(calls).toHaveLength(0)
    sendSwDiag(buildSwDiag(input()), 'tok', fetchImpl)
    expect(calls).toHaveLength(1)
    const [url, init] = calls[0] as [string, { method: string; headers: Record<string, string>; keepalive: boolean }]
    expect(url).toBe('/api/diag')
    expect(init.method).toBe('POST')
    expect(init.keepalive).toBe(true)
    expect(init.headers.Authorization).toBe('Bearer tok')
    expect(init.headers['X-Auth-Mode']).toBe('api')
  })

  it('отказ fetch не всплывает', () => {
    expect(() => sendSwDiag(buildSwDiag(input()), 'tok', () => Promise.reject(new Error('net')))).not.toThrow()
    expect(() =>
      sendSwDiag(buildSwDiag(input()), 'tok', () => {
        throw new Error('sync')
      }),
    ).not.toThrow()
  })
})
