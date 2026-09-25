import { readFileSync } from 'node:fs'
import { dirname, resolve } from 'node:path'
import { fileURLToPath } from 'node:url'

import react from '@vitejs/plugin-react-swc'
import { defineConfig } from 'vite'
import { VitePWA } from 'vite-plugin-pwa'

const __dirname = dirname(fileURLToPath(import.meta.url))

// Build-time app version = the git stamp written by deploy.sh into
// web/public/version.json. version.json travels with the frontend in every
// deploy mode, so the baked `__APP_VERSION__` always matches the running
// build. Falls back to the package version for local dev / fresh checkouts.
function readAppVersion(): string {
  try {
    const raw = readFileSync(resolve(__dirname, 'public/version.json'), 'utf8')
    const parsed = JSON.parse(raw) as { version?: string }
    if (parsed.version) return parsed.version
  } catch {
    // version.json only exists after a deploy (write_version) — fall back.
  }
  return process.env.npm_package_version ?? '0.0.0-dev'
}

const SHORT_TAG: Record<string, string> = { staging: 'STG', development: 'DEV' }

/**
 * Имена приложения. Прод — как было; всё остальное ОБЯЗАНО отличаться на
 * домашнем экране: две одинаковые иконки «Hub» — первопричина разбора 18.08
 * (телефон смотрел staging, десктоп — прод, час ушёл на «пропавшие» проекты).
 */
function appNames(mode: string): { name: string; short: string } {
  if (mode === 'production') return { name: 'Signaris Hub', short: 'Hub' }
  return { name: `Hub ${mode.toUpperCase()}`, short: `Hub ${SHORT_TAG[mode] ?? mode.toUpperCase()}` }
}

/**
 * Имя ярлыка на iOS берётся из `apple-mobile-web-app-title`, а НЕ из манифеста
 * — правка одного манифеста была бы no-op ровно на том устройстве, из-за
 * которого всё затевалось.
 *
 * Замена строго точечная, по двум полным строкам: рядом лежит анти-FOUC скрипт
 * темы, его sha256 прописан в CSP (ops/nginx/hub-security-headers.conf), и
 * любая правка тела скрипта молча ломает тему. Если якорь не найден (кто-то
 * переформатировал index.html) — падаем на сборке, а не тихо ничего не делаем.
 */
function envTitlePlugin(mode: string) {
  const { name, short } = appNames(mode)
  return {
    name: 'hub-env-title',
    transformIndexHtml(html: string): string {
      if (mode === 'production') return html
      const anchors: [string, string][] = [
        [
          '<meta name="apple-mobile-web-app-title" content="Hub" />',
          `<meta name="apple-mobile-web-app-title" content="${short}" />`,
        ],
        ['<title>Signaris Hub</title>', `<title>${name}</title>`],
      ]
      return anchors.reduce((acc, [from, to]) => {
        if (!acc.includes(from)) {
          throw new Error(`[hub-env-title] якорь не найден в index.html: ${from}`)
        }
        return acc.replace(from, to)
      }, html)
    },
  }
}

export default defineConfig(({ mode }) => ({
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
  },
  // pdf.worker — ES-модуль (import.meta): дефолтный iife-формат не годится.
  worker: {
    format: 'es',
  },
  server: {
    port: 5174,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:5060',
        changeOrigin: true,
      },
    },
  },
  define: {
    __APP_VERSION__: JSON.stringify(readAppVersion()),
    __APP_MODE__: JSON.stringify(mode),
  },
  plugins: [
    react(),
    envTitlePlugin(mode),
    VitePWA({
      strategies: 'injectManifest',
      registerType: 'prompt',
      // Регистрацию делает `src/lib/serviceWorker.ts`, а не плагин: у его
      // виртуального модуля слушатель `controlling` перезагружал соседние
      // вкладки (25.09). Без `false` плагин при отсутствии импорта
      // `virtual:pwa-register` сам вставил бы `registerSW.js` в index.html;
      // сторож — `deploy.sh`.
      injectRegister: false,
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        // HTML в прекеш НЕ кладём (ОС 21.09, баннер «Доступно обновление» не
        // уходил на «Главной»). Прекеш отвечает на навигацию к `/` своей копией
        // `index.html`, и `no-store` на сервере тут не участвует: это кеш
        // воркера, а не HTTP. Пока новый воркер ставился, «Обновить» перезагружал
        // `/` под СТАРЫМ — та же старая оболочка, тот же старый бандл, баннер на
        // месте; глубокие адреса (`/settings/…`) в прекеш не попадают и ходили в
        // сеть — там кнопка срабатывала с первого раза. Без HTML любая
        // навигация идёт в сеть и приносит свежую оболочку (1 КБ), а чанки
        // по-прежнему из прекеша. Сторож — `deploy.sh` (ищет index.html в dist/sw.js).
        globPatterns: ['**/*.{js,css,svg,png,webp,woff2}'],
        // Тяжёлые редакторско-админские чанки НЕ прекешируем каждому
        // сотруднику при каждом деплое — докачаются on-demand у авторов
        // (adversarial-ревью плана: precache тянул TipTap всем).
        globIgnores: [
          // pdf.js: чанк вьювера (~450KB) и worker (1.26MB) — on-demand,
          // не прекешируем каждому сотруднику при каждом деплое.
          '**/PdfViewer-*.js',
          '**/pdf.worker*.js',
          '**/RichEditor-*.js',
          '**/LearnOrgPage-*.js',
          '**/LearnEmployeesPage-*.js',
          '**/LearnAuditPage-*.js',
          '**/CourseBuilderPage-*.js',
          '**/LearnReviewPage-*.js',
          '**/LearnAnalyticsPage-*.js',
          '**/LearnAutomationsPage-*.js',
          '**/LearnAssessmentsPage-*.js',
          // «Гусиная гонка»: ТВ-страницу сотрудники не открывают, админ-вкладка — hub-admin.
          '**/RaceTvPage-*.js',
          '**/LearnRaceAdminPage-*.js',
        ],
      },
      manifest: {
        // Прод-манифест байт-в-байт прежний; отличается только не-прод.
        name: appNames(mode).name,
        short_name: appNames(mode).short,
        description: 'Корпоративный таск-трекер Signaris',
        theme_color: '#08080E',
        background_color: '#08080E',
        display: 'standalone',
        start_url: '/',
        scope: '/',
        lang: 'ru',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/icon-maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      devOptions: { enabled: false },
    }),
  ],
}))
