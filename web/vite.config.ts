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

export default defineConfig(({ mode }) => ({
  resolve: {
    alias: {
      '@': resolve(__dirname, './src'),
    },
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
    VitePWA({
      strategies: 'injectManifest',
      registerType: 'prompt',
      srcDir: 'src',
      filename: 'sw.ts',
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,webp,woff2}'],
      },
      manifest: {
        name: 'Signaris Hub',
        short_name: 'Hub',
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
