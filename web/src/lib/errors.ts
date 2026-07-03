/** Достаёт человекочитаемую причину из axios-ошибки FastAPI (`detail`) или Error. */
export function extractErrorDetail(err: unknown): string {
  const detail = (err as { response?: { data?: { detail?: unknown } } }).response?.data?.detail
  if (typeof detail === 'string' && detail) return detail
  if (err instanceof Error && err.message) return err.message
  return 'Неизвестная ошибка'
}
