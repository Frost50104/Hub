import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

/**
 * Сторож для `components/ui/Toaster.tsx`: тостер — ветка
 * `DismissableLayer.Branch`, и работает она только пока
 * `@radix-ui/react-dismissable-layer` в node_modules ОДИН. Radix пинит точные
 * версии, и бамп `react-dialog`/`react-menu` при отставшем корневом диапазоне
 * дал бы вторую копию: ветка регистрировалась бы в чужом контексте, диалоги
 * снова закрывались бы от тапа по тосту, а `pointer-events` продолжал бы
 * работать — по жалобе такое не отличить от «починили не до конца».
 *
 * Читаем package-lock, а не node_modules: CI ставит ровно его (`npm ci`).
 */
const PACKAGE = '@radix-ui/react-dismissable-layer'

function lockPackages(): Record<string, { version?: string }> {
  const here = dirname(fileURLToPath(import.meta.url))
  const lock = JSON.parse(readFileSync(join(here, '../../package-lock.json'), 'utf8')) as {
    packages: Record<string, { version?: string }>
  }
  return lock.packages
}

describe('react-dismissable-layer — одна копия', () => {
  it('в package-lock ровно одна запись пакета, вложенных копий нет', () => {
    const paths = Object.keys(lockPackages()).filter((p) => p.endsWith(`node_modules/${PACKAGE}`))
    expect(paths).toEqual([`node_modules/${PACKAGE}`])
  })

  it('корневая зависимость объявлена явно — тостер импортирует пакет напрямую', () => {
    const root = lockPackages()['']
    expect(root).toBeDefined()
    const deps = (root as { dependencies?: Record<string, string> }).dependencies ?? {}
    expect(deps[PACKAGE]).toMatch(/^\^/)
  })
})
