import type { Config } from 'tailwindcss'

export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        amber: 'rgb(var(--amber) / <alpha-value>)',
        red: 'rgb(var(--red) / <alpha-value>)',
        green: 'rgb(var(--green) / <alpha-value>)',
        'green-deep': 'rgb(var(--green-deep) / <alpha-value>)',
        'blue-deep': 'rgb(var(--blue-deep) / <alpha-value>)',
        'on-amber': 'rgb(var(--on-amber) / <alpha-value>)',
        'amber-deep': 'rgb(var(--amber-deep) / <alpha-value>)',
        'av-fill': 'rgb(var(--av-fill) / <alpha-value>)',
        bg: 'rgb(var(--bg) / <alpha-value>)',
        'bg-alt': 'rgb(var(--bg-alt) / <alpha-value>)',
        surface: 'var(--surface)',
        text: 'rgb(var(--text) / <alpha-value>)',
        text2: 'rgb(var(--text2) / <alpha-value>)',
        text3: 'rgb(var(--text3) / <alpha-value>)',
        glass: 'var(--glass)',
        'glass-border': 'var(--glass-border)',
        hair: 'var(--hair)',
        tint: 'var(--tint)',
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
