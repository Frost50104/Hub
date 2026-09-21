import { NBSP } from '@/lib/typography'

/**
 * Достаёт человекочитаемую причину из axios-ошибки FastAPI (`detail`) или Error.
 *
 * FastAPI отдаёт ошибки валидации СПИСКОМ `[{type, loc, msg, ctx}]`, а
 * человеческий текст сервер собирает только для лишних полей
 * (`app/main.py::validation_error_handler`, формат остальных закреплён тестом).
 * До 21.09 список здесь не разбирался, и любой такой 422 доходил до человека
 * английским «Request failed with status code 422» — так выглядел отказ
 * принять комментарий на 9 279 символов. `msg` pydantic тоже английский,
 * поэтому наружу идёт только русский текст.
 */
export function extractErrorDetail(err: unknown): string {
  // `?.` и на самом err: из onError сюда может прийти что угодно, включая null,
  // а падение внутри обработчика ошибки съело бы и тост.
  const detail = (err as { response?: { data?: { detail?: unknown } } } | null)?.response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length > 0) return validationMessage(detail)
  if (err instanceof Error && err.message) return err.message
  return 'Неизвестная ошибка'
}

interface ValidationItem {
  type?: unknown
  ctx?: { max_length?: unknown }
}

function validationMessage(items: unknown[]): string {
  for (const raw of items) {
    const item = raw as ValidationItem | null
    const max = item?.ctx?.max_length
    if (item?.type === 'string_too_long' && typeof max === 'number') {
      const n = max.toLocaleString('ru-RU').replace(/\s/g, NBSP)
      return `Слишком длинный текст: не больше ${n} символов`
    }
  }
  return 'Сервер не принял данные — проверьте заполнение полей'
}
