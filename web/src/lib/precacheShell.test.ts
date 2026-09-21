import { describe, expect, it } from 'vitest'

import { type CacheStorageLike, isPrecachedShell, purgePrecachedShell } from './precacheShell'

const ORIGIN = 'https://hub.signaris.ru'
const PRECACHE = `workbox-precache-v2-${ORIGIN}/`

/** Минимальный `CacheStorage` в памяти: имя кеша → адреса записей. */
function fakeStorage(
  data: Record<string, string[]>,
  opts: { failKeys?: boolean; failDelete?: boolean } = {},
): CacheStorageLike & { data: Record<string, string[]> } {
  const storage = {
    data,
    async keys() {
      if (opts.failKeys) throw new Error('SecurityError')
      return Object.keys(data)
    },
    async open(name: string) {
      const urls = (data[name] ??= [])
      return {
        async keys() {
          return urls.map((url) => ({ url }) as Request)
        },
        async delete(request: Request) {
          if (opts.failDelete) throw new Error('QuotaExceeded')
          const i = urls.indexOf(request.url)
          if (i < 0) return false
          urls.splice(i, 1)
          return true
        },
      } as unknown as Cache
    },
  }
  return storage as unknown as CacheStorageLike & { data: Record<string, string[]> }
}

describe('isPrecachedShell', () => {
  it('HTML-оболочка старого воркера — в прекеше под ревизией', () => {
    expect(isPrecachedShell(PRECACHE, `${ORIGIN}/index.html?__WB_REVISION__=abc`)).toBe(true)
    expect(isPrecachedShell(PRECACHE, `${ORIGIN}/`)).toBe(true)
  })

  it('чанки, иконки, version.json и sw.js — не оболочка', () => {
    for (const path of [
      '/assets/index-F3IZpcp2.js',
      '/assets/index-Bx1.css',
      '/icons/icon-192.png',
      '/version.json',
      '/sw.js',
    ]) {
      expect(isPrecachedShell(PRECACHE, `${ORIGIN}${path}`)).toBe(false)
    }
  })

  it('чужие кеши не трогаем, даже с HTML', () => {
    expect(isPrecachedShell('my-runtime-cache', `${ORIGIN}/index.html`)).toBe(false)
  })

  it('битый адрес — не оболочка, а не исключение', () => {
    expect(isPrecachedShell(PRECACHE, 'not a url')).toBe(false)
  })
})

describe('purgePrecachedShell', () => {
  it('удаляет только HTML в прекеше, остальное оставляет', async () => {
    const storage = fakeStorage({
      [PRECACHE]: [
        `${ORIGIN}/index.html?__WB_REVISION__=old`,
        `${ORIGIN}/assets/index-A.js`,
        `${ORIGIN}/icons/icon-192.png`,
      ],
      other: [`${ORIGIN}/index.html`],
    })
    expect(await purgePrecachedShell(storage)).toBe(1)
    expect(storage.data[PRECACHE]).toEqual([
      `${ORIGIN}/assets/index-A.js`,
      `${ORIGIN}/icons/icon-192.png`,
    ])
    expect(storage.data.other).toEqual([`${ORIGIN}/index.html`])
  })

  it('здоровый воркер (HTML нет) — пустой проход', async () => {
    const storage = fakeStorage({ [PRECACHE]: [`${ORIGIN}/assets/index-B.js`] })
    expect(await purgePrecachedShell(storage)).toBe(0)
    expect(storage.data[PRECACHE]).toHaveLength(1)
  })

  it('идемпотентна: второй вызов ничего не находит', async () => {
    const storage = fakeStorage({ [PRECACHE]: [`${ORIGIN}/index.html?__WB_REVISION__=x`] })
    expect(await purgePrecachedShell(storage)).toBe(1)
    expect(await purgePrecachedShell(storage)).toBe(0)
  })

  it('нет Cache API — 0 без исключения', async () => {
    expect(await purgePrecachedShell(undefined)).toBe(0)
  })

  it('хранилище бросает (приватное окно Safari) — 0 без исключения', async () => {
    expect(await purgePrecachedShell(fakeStorage({}, { failKeys: true }))).toBe(0)
    const failing = fakeStorage(
      { [PRECACHE]: [`${ORIGIN}/index.html?__WB_REVISION__=x`] },
      { failDelete: true },
    )
    expect(await purgePrecachedShell(failing)).toBe(0)
  })
})
