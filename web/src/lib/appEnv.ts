/**
 * «Где я сейчас» — staging или прод.
 *
 * Первопричина (18.08): телефон смотрел staging, десктоп — прод, и час ушёл
 * на разбор «пропавших» проектов (на staging они лежат в другом тенанте, RLS
 * честно отдал пустой список). В PWA нет адресной строки, иконка и вёрстка
 * совпадают — отличить среды было нечем.
 *
 * ДВА написания прода, и оба обязаны считаться продом:
 *   - бэкенд шлёт `prod`       (SIGNARIS_HUB_ENVIRONMENT в .env на VPS),
 *   - сборка шлёт `production` (vite mode).
 * Проверка против одного из них зажгла бы маркер на боевом домене.
 */
const PROD_VALUES = new Set(['prod', 'production'])

const LABELS: Record<string, string> = {
  staging: 'STAGING',
  development: 'DEV',
}

function label(value: string): string {
  return LABELS[value] ?? value.toUpperCase()
}

/**
 * Метка окружения или `null`, если это прод.
 *
 * Два независимых плеча:
 *   1. build-mode — известен синхронно, поэтому маркер есть уже на первом
 *      кадре: без запроса и без мигания;
 *   2. `environment` с `/api/env` — ловит «прод-сборку руками положили на
 *      staging»: бандл считает себя продом, а API отвечает staging'овое.
 *
 * Функция чистая (глобалей не читает) — именно поэтому тестируется без моков.
 */
export function resolveEnvLabel(
  buildMode: string,
  backendEnv?: string | null,
): string | null {
  if (!PROD_VALUES.has(buildMode)) return label(buildMode)
  if (backendEnv && !PROD_VALUES.has(backendEnv)) return label(backendEnv)
  return null
}

// Значение с бэкенда кладёт bootstrap в main.tsx — он и так тянет /api/env до
// первого рендера ради Sentry, поэтому нового запроса не появляется.
let backendEnv: string | null = null

export function setBackendEnv(value: string | null | undefined): void {
  backendEnv = value ?? null
}

export function currentEnvLabel(): string | null {
  return resolveEnvLabel(__APP_MODE__, backendEnv)
}
