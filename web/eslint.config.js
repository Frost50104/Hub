import reactHooks from 'eslint-plugin-react-hooks'
import tseslint from 'typescript-eslint'

// Минимальный фокусный набор: TS-recommended + правила хуков React.
// Мёртвые переменные/типы ловит tsc (strict) — не дублируем.
export default tseslint.config(
  { ignores: ['dist', 'dev-dist', 'node_modules'] },
  {
    files: ['src/**/*.{ts,tsx}'],
    extends: [...tseslint.configs.recommended],
    plugins: { 'react-hooks': reactHooks },
    rules: {
      ...reactHooks.configs.recommended.rules,
      '@typescript-eslint/no-unused-vars': 'off',
    },
  },
)
