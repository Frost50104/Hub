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

const timeFormatters = new Map<string, Intl.DateTimeFormat>()

function timeFormatter(tz: string): Intl.DateTimeFormat {
  let f = timeFormatters.get(tz)
  if (!f) {
    // `hourCycle: 'h23'`, а не `hour12: false`: второй на части движков даёт
    // «24:00» вместо «00:00» (тот же приём, что в `tzOffsetMs`).
    f = new Intl.DateTimeFormat('en-GB', {
      timeZone: tz,
      hourCycle: 'h23',
      hour: '2-digit',
      minute: '2-digit',
    })
    timeFormatters.set(tz, f)
  }
  return f
}

/** «HH:MM» мгновения в display tz (0061: время у старта и срока). */
export function timeKey(value: string | number | Date, tz: string = displayTz): string {
  const d = value instanceof Date ? value : new Date(value)
  const parts = timeFormatter(tz).formatToParts(d)
  const hh = parts.find((p) => p.type === 'hour')?.value ?? '00'
  const mm = parts.find((p) => p.type === 'minute')?.value ?? '00'
  return `${hh}:${mm}`
}

/**
 * «15:30» → [15, 30]. Лениво к хвосту: Chrome отдаёт «15:30», а с `step`
 * меньше минуты — «15:30:00». Вне диапазона — null.
 */
export function parseTimeKey(value: string): [number, number] | null {
  const m = /^(\d{1,2}):(\d{2})/.exec(value.trim())
  if (!m) return null
  const hh = Number(m[1])
  const mm = Number(m[2])
  if (hh > 23 || mm > 59) return null
  return [hh, mm]
}

/** День + «HH:MM» по display tz → ISO. Некорректное время — null. */
export function dayTimeToIso(key: string, time: string, tz: string = displayTz): string | null {
  const hm = parseTimeKey(time)
  return hm ? atTimeIso(key, hm[0], hm[1], tz) : null
}

/** «16 авг» — без точки после месяца: ru-RU short даёт «16 авг.». */
export function shortDate(iso: string): string {
  return new Date(iso)
    .toLocaleDateString('ru-RU', { day: 'numeric', month: 'short', timeZone: displayTz })
    .replace('.', '')
}

/**
 * «27.08.2026» — полная дата для карточки задачи.
 *
 * В отличие от `shortDate` несёт год: в списке важна краткость, а в карточке
 * срок бывает и в следующем году, и «16 авг» там читается двусмысленно.
 * Принимает как ISO-мгновение, так и ключ дня `YYYY-MM-DD` — в мобильной
 * карточке значение приходит прямо из `input[type=date]`.
 */
export function humanDate(value: string): string {
  const iso = /^\d{4}-\d{2}-\d{2}$/.test(value) ? dueDayToIso(value) : value
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return value
  return d.toLocaleDateString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: displayTz,
  })
}

/**
 * Срок в строке списка/на доске: «30 сен», а при выбранном времени — «30 сен 15:00».
 * Час печатаем ТОЛЬКО если его выбрали: у срока без времени мгновение условное
 * (полдень display tz), и «12:00» было бы неправдой.
 */
export function formatDueShort(iso: string, hasTime: boolean | undefined): string {
  return hasTime ? `${shortDate(iso)} ${timeKey(iso)}` : shortDate(iso)
}

/** То же для карточки и публичной страницы: «30.09.2026» / «30.09.2026, 15:00». */
export function formatDueLong(iso: string, hasTime: boolean | undefined): string {
  return hasTime ? `${humanDate(iso)}, ${timeKey(iso)}` : humanDate(iso)
}

/**
 * Порядок по сроку для «Моих задач»: по дню, внутри дня сначала «весь день»
 * (без времени), потом по времени; без срока — в конце. Сортировка сервера по
 * мгновению ставила бы «без времени» (условный полдень) между 11:00 и 13:00.
 */
export function compareDue(
  a: { due_at: string | null; due_has_time?: boolean },
  b: { due_at: string | null; due_has_time?: boolean },
): number {
  if (!a.due_at || !b.due_at) {
    if (a.due_at === b.due_at) return 0
    return a.due_at ? -1 : 1
  }
  const da = dayKey(a.due_at)
  const db = dayKey(b.due_at)
  if (da !== db) return da < db ? -1 : 1
  const ta = a.due_has_time === true
  const tb = b.due_has_time === true
  if (ta !== tb) return ta ? 1 : -1
  return Date.parse(a.due_at) - Date.parse(b.due_at)
}

/**
 * Просрочена ли задача: день срока раньше сегодняшнего (display tz). Готовые
 * не считаются просроченными никогда — иначе закрытая с опозданием задача
 * навсегда осталась бы красной.
 */
/**
 * Просрочка задачи с учётом шаблона (0060): сроки шаблона отсчитаны от точки
 * отсчёта и часто лежат в прошлом, но это не опоздание — задача шаблона не
 * краснеет никогда. Все строки, карточки и календарь трекера зовут ЭТУ функцию.
 */
export function taskOverdue(
  task: { due_at: string | null; done: boolean; is_template?: boolean },
  now: number = Date.now(),
): boolean {
  return task.is_template !== true && isOverdue(task.due_at, task.done, now)
}

export function isOverdue(
  due: string | null,
  done: boolean,
  now: number = Date.now(),
): boolean {
  return !!due && !done && dayKey(due) < todayKey(now)
}

/** «просрочено на 4 дня» — в КАЛЕНДАРНЫХ днях display tz (≥1 для просроченной). */
export function overdueDays(due: string, now: number = Date.now()): number {
  const [y1, m1, d1] = dayKey(due).split('-').map(Number) as [number, number, number]
  const [y2, m2, d2] = todayKey(now).split('-').map(Number) as [number, number, number]
  const diff = Math.round((Date.UTC(y2, m2 - 1, d2) - Date.UTC(y1, m1 - 1, d1)) / 86_400_000)
  return Math.max(1, diff)
}
