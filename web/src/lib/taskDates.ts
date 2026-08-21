/**
 * Даты задач — срок это КАЛЕНДАРНЫЙ ДЕНЬ в display tz (по умолчанию
 * Europe/Moscow, значение приходит с `/api/env.display_timezone` и ставится
 * через `setDisplayTz` в main.tsx). Хранится мгновение (ISO), но «просрочено /
 * сегодня / завтра» считаются по дням: задача со сроком «сегодня» не краснеет
 * в 12:01 и не показывает «−1 дн» (ОС тестировщика 2026-08). Бэкенд делает то
 * же в `app/services/taskdates.py` — окна «Сегодня/Предстоит/Просрочено».
 *
 * Без дат-библиотек: ключ дня считается через Intl с явной timeZone; полдень
 * дня — через смещение зоны (МСК без DST, одного прохода коррекции хватает).
 */

let displayTz = 'Europe/Moscow'

export function setDisplayTz(tz: string | null | undefined): void {
  if (tz) displayTz = tz
}

export function getDisplayTz(): string {
  return displayTz
}

const keyFormatters = new Map<string, Intl.DateTimeFormat>()

function keyFormatter(tz: string): Intl.DateTimeFormat {
  let f = keyFormatters.get(tz)
  if (!f) {
    // en-CA даёт YYYY-MM-DD без перестановок.
    f = new Intl.DateTimeFormat('en-CA', {
      timeZone: tz,
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    })
    keyFormatters.set(tz, f)
  }
  return f
}

/** «YYYY-MM-DD» календарного дня мгновения в display tz. */
export function dayKey(value: string | number | Date, tz: string = displayTz): string {
  const d = value instanceof Date ? value : new Date(value)
  return keyFormatter(tz).format(d)
}

export function todayKey(now: number | Date = Date.now(), tz: string = displayTz): string {
  return dayKey(now, tz)
}

/** Сдвиг ключа дня на n календарных дней (арифметика по UTC-полудню — без DST-ловушек). */
export function addDaysKey(key: string, n: number): string {
  const [y, m, d] = key.split('-').map(Number) as [number, number, number]
  const shifted = new Date(Date.UTC(y, m - 1, d + n, 12))
  return shifted.toISOString().slice(0, 10)
}

/** Смещение зоны (мс) для мгновения: local − utc. */
function tzOffsetMs(instant: number, tz: string): number {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: tz,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  }).formatToParts(new Date(instant))
  const get = (t: string) => Number(parts.find((p) => p.type === t)?.value ?? 0)
  const asUtc = Date.UTC(get('year'), get('month') - 1, get('day'), get('hour'), get('minute'), get('second'))
  return asUtc - Math.floor(instant / 1000) * 1000
}

/** Мгновение «часы:минуты display tz» указанного дня → ISO. */
function atTimeIso(key: string, hour: number, minute: number, tz: string): string {
  const [y, m, d] = key.split('-').map(Number) as [number, number, number]
  const guess = Date.UTC(y, m - 1, d, hour, minute)
  let instant = guess - tzOffsetMs(guess, tz)
  // Один проход коррекции — на случай перехода DST ровно в этот момент.
  instant = guess - tzOffsetMs(instant, tz)
  return new Date(instant).toISOString()
}

/** Единственный писатель «дата → инстант» на клиенте: полдень display tz. */
export function dueDayToIso(key: string, tz: string = displayTz): string {
  return atTimeIso(key, 12, 0, tz)
}

/** 00:00:00.000 display tz дня → ISO (нижняя граница фильтров). */
export function dayStartIso(key: string, tz: string = displayTz): string {
  return atTimeIso(key, 0, 0, tz)
}

/** 23:59:59.999 display tz дня → ISO (верхняя граница фильтров, бэкенд `<=`). */
export function dayEndIso(key: string, tz: string = displayTz): string {
  const start = new Date(dayStartIso(addDaysKey(key, 1), tz)).getTime()
  return new Date(start - 1).toISOString()
}

/** «16 авг» — без точки после месяца: ru-RU short даёт «16 авг.». */
export function shortDate(iso: string): string {
  return new Date(iso)
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: displayTz })
    .replace('.', '')
}

/**
 * Просрочена ли задача: день срока раньше сегодняшнего (display tz). Готовые
 * не считаются просроченными никогда — иначе закрытая с опозданием задача
 * навсегда осталась бы красной.
 */
export function isOverdue(
  due: string | null,
  status: string,
  now: number = Date.now(),
): boolean {
  return !!due && status !== 'done' && dayKey(due) < todayKey(now)
}

/** «просрочено на 4 дня» — в КАЛЕНДАРНЫХ днях display tz (≥1 для просроченной). */
export function overdueDays(due: string, now: number = Date.now()): number {
  const [y1, m1, d1] = dayKey(due).split('-').map(Number) as [number, number, number]
  const [y2, m2, d2] = todayKey(now).split('-').map(Number) as [number, number, number]
  const diff = Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000)
  return Math.max(1, diff)
}
