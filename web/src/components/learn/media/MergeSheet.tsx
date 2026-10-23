import { ArrowDown, ArrowUp, FilePlus2, X } from 'lucide-react'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { Switch } from '@/components/ui/Switch'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type MediaDetail, type MediaStatus } from '@/lib/learn'
import { formatBytes, formatDuration, videoFileProblem } from '@/lib/mediaJobs'
import { checkTrim, trimmedDuration } from '@/lib/timeInput'
import { plural } from '@/lib/typography'

/**
 * «Собрать видео из записей» (макет MergeSheet): несколько файлов → части с
 * ролью `part` → порядок, подрезка «с … до …» → `POST /learn/media/merge`.
 * В урок попадает только собранный ролик (вставляется сразу, в `processing`),
 * части остаются исходниками на сервере. Загрузка — последовательно (две
 * параллельные делили бы канал телефона пополам), конвертация MOV ждётся
 * опросом детали части.
 */

const PART_MAX_BYTES = 300 * 1024 * 1024
const MAX_PARTS = 20
const POLL_MS = 5_000

interface Part {
  key: string
  file: File
  mediaId: string | null
  status: 'uploading' | 'processing' | 'ready' | 'failed'
  pct: number
  duration: number | null
  error: string | null
  startRaw: string
  endRaw: string
}

let seq = 0

export function MergeSheet({
  open,
  onOpenChange,
  onMerged,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  /** Собранный файл создан (в `processing`): вставить ноду в урок. */
  onMerged: (media: MediaDetail, opts: { requireFullWatch: boolean; disableSeek: boolean }) => void
}) {
  const [parts, setParts] = useState<Part[]>([])
  const [requireFullWatch, setRequireFullWatch] = useState(true)
  const [disableSeek, setDisableSeek] = useState(false)
  const [busy, setBusy] = useState(false)
  const input = useRef<HTMLInputElement | null>(null)
  const uploading = useRef(false)
  const queue = useRef<Part[]>([])

  const patch = (key: string, upd: Partial<Part>) =>
    setParts((prev) => prev.map((p) => (p.key === key ? { ...p, ...upd } : p)))

  // Очередь загрузки: по одному файлу за раз.
  const drain = async () => {
    if (uploading.current) return
    uploading.current = true
    try {
      while (queue.current.length) {
        const part = queue.current.shift()!
        try {
          const media = await learnApi.uploadMedia(part.file, {
            role: 'part',
            onProgress: (f) => patch(part.key, { pct: Math.round(f * 100) }),
          })
          patch(part.key, {
            mediaId: media.id,
            status: media.status === 'processing' ? 'processing' : 'ready',
            duration: media.duration_sec ?? null,
            pct: 100,
          })
        } catch (e) {
          patch(part.key, { status: 'failed', error: extractErrorDetail(e) })
        }
      }
    } finally {
      uploading.current = false
    }
  }

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])]
    e.target.value = ''
    const room = MAX_PARTS - parts.length
    if (files.length > room) toast.info(`Частей может быть не больше ${MAX_PARTS}`)
    const accepted: Part[] = []
    for (const file of files.slice(0, Math.max(0, room))) {
      const problem = videoFileProblem(file, true, PART_MAX_BYTES)
      if (problem) {
        toast.error(`${file.name}: ${problem}`)
        continue
      }
      accepted.push({
        key: `p${++seq}`,
        file,
        mediaId: null,
        status: 'uploading',
        pct: 0,
        duration: null,
        error: null,
        startRaw: '',
        endRaw: '',
      })
    }
    if (!accepted.length) return
    setParts((prev) => [...prev, ...accepted])
    queue.current.push(...accepted)
    void drain()
  }

  // Части в конвертации — опрашиваем, пока не станут ready/failed.
  const pendingKey = parts
    .filter((p) => p.status === 'processing' && p.mediaId)
    .map((p) => p.mediaId)
    .join(',')
  useEffect(() => {
    if (!pendingKey || !open) return
    const ids = pendingKey.split(',')
    const tick = async () => {
      for (const id of ids) {
        try {
          const d = await learnApi.mediaDetail(id)
          const status: MediaStatus = d.status
          if (status !== 'processing') {
            setParts((prev) =>
              prev.map((p) =>
                p.mediaId === id
                  ? {
                      ...p,
                      status,
                      duration: d.duration_sec,
                      error: status === 'failed' ? 'Конвертация не удалась' : null,
                    }
                  : p,
              ),
            )
          }
        } catch {
          // следующий тик
        }
      }
    }
    const t = setInterval(() => void tick(), POLL_MS)
    void tick()
    return () => clearInterval(t)
  }, [pendingKey, open])

  const move = (index: number, dir: -1 | 1) =>
    setParts((prev) => {
      const next = [...prev]
      const j = index + dir
      if (j < 0 || j >= next.length) return prev
      const a = next[index]!
      next[index] = next[j]!
      next[j] = a
      return next
    })

  const remove = (key: string) => {
    queue.current = queue.current.filter((p) => p.key !== key)
    setParts((prev) => prev.filter((p) => p.key !== key))
  }

  const checks = parts.map((p) => checkTrim(p.startRaw, p.endRaw, p.duration))
  const readyCount = parts.filter((p) => p.status === 'ready').length
  const notReadyIndex = parts.findIndex((p) => p.status !== 'ready')
  const invalid = checks.findIndex((c) => c.problem !== null)
  const total = parts.reduce((acc, p) => acc + (p.duration ?? 0), 0)
  const trimmed = parts.reduce(
    (acc, p, i) => acc + (trimmedDuration(p.duration, checks[i]!.start, checks[i]!.end) ?? 0),
    0,
  )
  const canSubmit = parts.length >= 2 && readyCount === parts.length && invalid === -1 && !busy

  const submit = async () => {
    setBusy(true)
    try {
      const out = await learnApi.mergeMedia(
        parts.map((p, i) => ({
          media_id: p.mediaId!,
          trim_start_sec: checks[i]!.start,
          trim_end_sec: checks[i]!.end,
        })),
      )
      onMerged(out.media, { requireFullWatch, disableSeek })
      toast.success('Собираем видео — ролик появится в уроке сам', {
        description:
          'Около 40–60 минут на час записи. Сохраните урок, чтобы блок остался на месте.',
      })
      setParts([])
      onOpenChange(false)
    } catch (e) {
      toast.error('Не удалось запустить сборку', {
        description: extractErrorDetail(e),
      })
    } finally {
      setBusy(false)
    }
  }

  const submitLabel =
    parts.length >= 2 && notReadyIndex >= 0
      ? `Собрать · ждём часть ${notReadyIndex + 1}`
      : 'Собрать'

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => {
        if (!v && busy) return
        onOpenChange(v)
      }}
      title="Собрать видео из записей"
      description="Части склеятся в указанном порядке, формат выровняем сами. Подрежьте начало и конец там, где запись стартовала раньше времени."
      desktopWidth={760}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)} disabled={busy}>
            Отмена
          </Button>
          <Button disabled={!canSubmit} onClick={() => void submit()}>
            {busy ? 'Запускаем…' : submitLabel}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <button
          type="button"
          onClick={() => input.current?.click()}
          disabled={parts.length >= MAX_PARTS}
          className="flex w-full items-center justify-center gap-2 rounded-xl border border-dashed border-hair px-4 py-5 text-sm font-semibold text-amber hover:bg-glass disabled:opacity-50"
        >
          <FilePlus2 className="h-4 w-4" /> Добавить файлы · можно несколько сразу
        </button>
        <input
          ref={input}
          type="file"
          accept="video/mp4,video/quicktime,video/webm,.mp4,.mov,.webm,.m4v"
          multiple
          hidden
          onChange={onPick}
        />
        <p className="-mt-2 text-[12px] text-text3">MP4, MOV, WebM · до 300 МБ каждый</p>

        {parts.length > 0 && (
          <ol className="divide-y divide-hair rounded-xl border border-hair">
            {parts.map((p, i) => {
              const check = checks[i]!
              return (
                <li
                  key={p.key}
                  className="grid grid-cols-[24px_1fr_auto] gap-x-3 gap-y-1 px-3 py-2.5"
                >
                  <span className="pt-0.5 text-[13px] tabular-nums text-text3">{i + 1}</span>
                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-text">{p.file.name}</p>
                    <p className="text-[12px] text-text3">
                      {p.status === 'uploading' && `загрузка ${p.pct} %`}
                      {p.status === 'processing' &&
                        `${formatBytes(p.file.size)} · конвертация из ${(p.file.name.split('.').pop() ?? '').toUpperCase()}…`}
                      {p.status === 'ready' && `${formatDuration(p.duration)} · загружено`}
                      {p.status === 'failed' && (
                        <span className="text-red">{p.error ?? 'не удалось'}</span>
                      )}
                    </p>
                    <div className="mt-1.5 flex flex-wrap items-center gap-2 text-[12px] text-text3">
                      <label className="flex items-center gap-1">
                        С
                        <Input
                          value={p.startRaw}
                          placeholder="0:00"
                          inputMode="numeric"
                          className="h-7 w-[72px] px-2 text-[13px]"
                          onChange={(e) => patch(p.key, { startRaw: e.target.value })}
                        />
                      </label>
                      <label className="flex items-center gap-1">
                        До
                        <Input
                          value={p.endRaw}
                          placeholder={p.duration ? formatDuration(p.duration) : 'конец'}
                          inputMode="numeric"
                          className="h-7 w-[72px] px-2 text-[13px]"
                          onChange={(e) => patch(p.key, { endRaw: e.target.value })}
                        />
                      </label>
                      {check.problem && <span className="text-red">{check.problem}</span>}
                    </div>
                  </div>
                  <div className="flex items-start gap-0.5">
                    <IconBtn label="Выше" disabled={i === 0} onClick={() => move(i, -1)}>
                      <ArrowUp className="h-4 w-4" />
                    </IconBtn>
                    <IconBtn
                      label="Ниже"
                      disabled={i === parts.length - 1}
                      onClick={() => move(i, 1)}
                    >
                      <ArrowDown className="h-4 w-4" />
                    </IconBtn>
                    <IconBtn label="Убрать" onClick={() => remove(p.key)}>
                      <X className="h-4 w-4" />
                    </IconBtn>
                  </div>
                </li>
              )
            })}
          </ol>
        )}

        {parts.length > 0 && (
          <p className="text-[13px] leading-[1.45] text-text2">
            {plural(parts.length, 'часть', 'части', 'частей')}
            {total > 0 && ` · ${formatDuration(total)}`}
            {total > 0 &&
              Math.round(trimmed) !== Math.round(total) &&
              ` → после подрезки ${formatDuration(trimmed)}`}
            . Сборка идёт на сервере около 40–60 минут для часа записи, шторку можно закрыть — ролик
            появится в уроке сам.
          </p>
        )}

        <div className="space-y-2 rounded-xl border border-hair bg-tint p-3">
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={requireFullWatch} onCheckedChange={setRequireFullWatch} />
            обязательный досмотр (≥90% для завершения урока)
          </label>
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={disableSeek} onCheckedChange={setDisableSeek} />
            запретить перемотку вперёд
          </label>
        </div>
        <p className="text-[12px] leading-[1.45] text-text3">
          Части с разным разрешением выровняем по лучшей, звук сведём к одному уровню на этапе
          чистовика.
        </p>
      </div>
    </ResponsiveDialog>
  )
}

function IconBtn({
  label,
  disabled,
  onClick,
  children,
}: {
  label: string
  disabled?: boolean
  onClick: () => void
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      aria-label={label}
      disabled={disabled}
      onClick={onClick}
      className="rounded p-1.5 text-text3 hover:bg-glass hover:text-text disabled:opacity-30"
    >
      {children}
    </button>
  )
}
