import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        amber: 'var(--amber)',
        bg: 'var(--bg)',
        'bg-alt': 'var(--bg-alt)',
        surface: 'var(--surface)',
        text: 'var(--text)',
        text2: 'var(--text2)',
        text3: 'var(--text3)',
        glass: 'var(--glass)',
        'glass-border': 'var(--glass-border)',
      },
      fontFamily: {
        display: ['Unbounded', 'sans-serif'],
        body: ['Onest', 'sans-serif'],
      },
      borderRadius: {
        glass: '20px',
      },
      boxShadow: {
        glass: '0 8px 24px rgba(0,0,0,0.18)',
      },
    },
  },
  plugins: [],
} satisfies Config
