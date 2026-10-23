import { useQueryClient } from '@tanstack/react-query'
import { ImagePlus, Play } from 'lucide-react'
import { useEffect, useRef, useState, type ChangeEvent } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Confirm } from '@/components/ui/Confirm'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import {
  useMediaAdminSettings,
  useMediaDetail,
  useStartAvatarTest,
  useUpdateMediaAdminSettings,
} from '@/hooks/useMediaJobs'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import { learnApi, type MediaAdminSettings } from '@/lib/learn'
import { activeJob, failureText, latestJob } from '@/lib/mediaJobs'
import { formatMoney, pricePerMinute, RESOLUTIONS, sceneTestCostCents } from '@/lib/storyboard'

/**
 * «Управление → Видео» (0066, макет AdminVideoFull): тумблер модуля,
 * расшифровка, глоссарий, сцена гуся 16:9 с проверкой на 10 секундах
 * (`avatar_test`), лимит и качество. Сегмент виден только при
 * `me.features.media_pipeline_admin`.
 */
export function LearnVideoAdminPage() {
  const settings = useMediaAdminSettings()
  const update = useUpdateMediaAdminSettings()
  if (settings.isPending) return <SkeletonRows rows={4} />
  if (settings.isError || !settings.data) {
    return (
      <EmptyState
        title="Конвейер видео недоступен"
        text="Сервер не ответил на запрос настроек — на этом окружении модуль может быть выключен целиком."
      />
    )
  }
  const s = settings.data
  return (
    <div className="space-y-5">
      <ModuleToggle
        settings={s}
        pending={update.isPending}
        onChange={(v) => update.mutate({ enabled: v })}
      />
      <TranscribeSection
        settings={s}
        pending={update.isPending}
        onSave={(patch) => update.mutate(patch)}
      />
      <AvatarSection
        settings={s}
        pending={update.isPending}
        onSave={(patch) => update.mutate(patch)}
      />
    </div>
  )
}

function Section({
  title,
  hint,
  children,
}: {
  title: string
  hint?: string
  children: React.ReactNode
}) {
  return (
    <section className="space-y-3 rounded-xl border border-hair bg-tint p-4">
      <div>
        <h2 className="font-display text-[17px] font-bold text-text">{title}</h2>
        {hint && <p className="mt-1 text-[14px] leading-[1.45] text-text2">{hint}</p>}
      </div>
      {children}
    </section>
  )
}

function ModuleToggle({
  settings,
  pending,
  onChange,
}: {
  settings: MediaAdminSettings
  pending: boolean
  onChange: (v: boolean) => void
}) {
  const [confirmOff, setConfirmOff] = useState(false)
  const enabled = settings.enabled
  return (
    <section
      className={cn(
        'flex items-start justify-between gap-4 rounded-xl border p-4',
        enabled ? 'border-hair bg-tint' : 'border-amber/50 bg-amber/[0.06]',
      )}
    >
      <div className="min-w-0">
        <p className="font-display text-[17px] font-bold text-text">
          {enabled ? 'Конвейер видео включён' : 'Конвейер видео выключен'}
        </p>
        <p className="mt-1 text-[14px] leading-[1.45] text-text2">
          {enabled
            ? 'Авторы могут загружать MOV и WebM, собирать видео из нескольких записей, получать субтитры; сотрудники видят субтитры в плеере.'
            : 'Для авторов модуля нет: только MP4 с faststart, без субтитров и чистовика. Готовые файлы и расшифровки сохраняются — включение вернёт всё как было.'}
          {!settings.stt_configured &&
            ' На этом сервере не настроена расшифровка: субтитров не будет, пока администратор не подключит её.'}
        </p>
        {settings.active_jobs > 0 && (
          <p className="mt-1 text-[13px] text-text3">Сейчас в работе: {settings.active_jobs}</p>
        )}
      </div>
      <div className="flex h-11 w-11 shrink-0 items-center justify-center">
        <Switch
          checked={enabled}
          disabled={pending}
          aria-label="Включить конвейер видео"
          onCheckedChange={(v) => {
            if (!v && settings.active_jobs > 0) setConfirmOff(true)
            else onChange(v)
          }}
        />
      </div>
      <Confirm
        open={confirmOff}
        onOpenChange={setConfirmOff}
        title="Выключить конвейер видео?"
        text="Идут задания. Выключение не прерывает их, но новые не примутся, а кнопки в редакторе исчезнут; данные сохранятся."
        confirmLabel="Выключить"
        destructive
        pending={pending}
        onConfirm={() => {
          setConfirmOff(false)
          onChange(false)
        }}
      />
    </section>
  )
}

function TranscribeSection({
  settings,
  pending,
  onSave,
}: {
  settings: MediaAdminSettings
  pending: boolean
  onSave: (patch: { auto_transcribe?: boolean; glossary?: string }) => void
}) {
  const [glossary, setGlossary] = useState(settings.glossary)
  useEffect(() => setGlossary(settings.glossary), [settings.glossary])
  const dirty = glossary.trim() !== settings.glossary.trim()
  return (
    <Section
      title="Расшифровка"
      hint={
        settings.stt_configured
          ? `Распознаёт ${settings.stt_provider === 'openai' ? 'удалённый сервис' : 'наш сервер (Whisper small)'}; текст уходит в субтитры, поиск и к ассистенту.`
          : 'Служба распознавания не настроена на сервере — расшифровка недоступна.'
      }
    >
      <label className="flex items-center gap-2 text-sm text-text2">
        <Switch
          checked={settings.auto_transcribe}
          disabled={pending}
          onCheckedChange={(v) => onSave({ auto_transcribe: v })}
        />
        расшифровывать каждое новое видео урока автоматически
      </label>
      <div>
        <Label htmlFor="media-glossary">Глоссарий</Label>
        <Input
          id="media-glossary"
          value={glossary}
          maxLength={500}
          placeholder="Signaris, Hub, UPPETIT, Нурлан…"
          onChange={(e) => setGlossary(e.target.value)}
        />
        <p className="mt-1 text-[13px] leading-[1.45] text-text2">
          Имена, бренды и термины через запятую — подсказка распознаванию, чтобы «Хаб» не
          превращался в «хап». До 500 знаков.
        </p>
      </div>
      <Button
        size="sm"
        disabled={!dirty || pending}
        onClick={() => onSave({ glossary: glossary.trim() })}
      >
        Сохранить глоссарий
      </Button>
    </Section>
  )
}

const SCENE_MAX_BYTES = 20 * 1024 * 1024

function AvatarSection({
  settings,
  pending,
  onSave,
}: {
  settings: MediaAdminSettings
  pending: boolean
  onSave: (patch: {
    avatar_monthly_minutes_cap?: number
    avatar_resolution?: MediaAdminSettings['avatar_resolution']
    scene_media_id?: string | null
  }) => void
}) {
  const [cap, setCap] = useState(String(settings.avatar_monthly_minutes_cap))
  useEffect(
    () => setCap(String(settings.avatar_monthly_minutes_cap)),
    [settings.avatar_monthly_minutes_cap],
  )
  const capNum = Number(cap)
  const capValid = Number.isInteger(capNum) && capNum >= 0 && capNum <= 100_000
  const used = settings.month_used_minutes
  const resolution = settings.avatar_resolution
  const capCostCents = settings.avatar_monthly_minutes_cap * 60 * (sceneTestCostCents(resolution) / 10)
  return (
    <Section
      title="Гусь (аватар)"
      hint={
        settings.avatar_env_enabled
          ? 'Говорящий гусь вместо спикера через Hedra: наружу уходят только сцена и голосовая дорожка. Всё остальное считается на нашем сервере.'
          : 'Гусь на этом сервере выключен: нет ключа Hedra. Сцену, лимит и качество можно задать заранее.'
      }
    >
      <SceneBlock settings={settings} pending={pending} onSave={onSave} />
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        <div>
          <Label htmlFor="media-cap">Лимит минут в месяц</Label>
          <Input
            id="media-cap"
            value={cap}
            inputMode="numeric"
            onChange={(e) => setCap(e.target.value)}
            onBlur={() =>
              capValid &&
              capNum !== settings.avatar_monthly_minutes_cap &&
              onSave({ avatar_monthly_minutes_cap: capNum })
            }
          />
          <p className="mt-1 text-[13px] text-text2">
            Использовано в этом месяце: {used.toLocaleString('ru-RU', { maximumFractionDigits: 1 })}{' '}
            из {settings.avatar_monthly_minutes_cap} мин
            {settings.avatar_monthly_minutes_cap > 0 &&
              ` · ≈ ${formatMoney(capCostCents)} в месяц при ${resolution}`}
            . Обнуляется 1-го числа.
          </p>
        </div>
        <div>
          <Label htmlFor="media-res">Качество по умолчанию</Label>
          <Select
            id="media-res"
            value={resolution}
            disabled={pending}
            onChange={(e) =>
              onSave({
                avatar_resolution: e.target.value as MediaAdminSettings['avatar_resolution'],
              })
            }
          >
            {RESOLUTIONS.map((r) => (
              <option key={r} value={r}>
                {r} · {pricePerMinute(r)}
              </option>
            ))}
          </Select>
          <p className="mt-1 text-[13px] leading-[1.45] text-text2">
            Гусь всегда во весь кадр там, где в записи был человек; во время показа экрана остаётся
            только голос.
          </p>
        </div>
      </div>
    </Section>
  )
}

/** Сцена-референс 16:9 (гусь анфас + фон) и «Проверить на 10 секундах». */
function SceneBlock({
  settings,
  pending,
  onSave,
}: {
  settings: MediaAdminSettings
  pending: boolean
  onSave: (patch: { scene_media_id?: string | null }) => void
}) {
  const qc = useQueryClient()
  const input = useRef<HTMLInputElement | null>(null)
  const [uploadPct, setUploadPct] = useState<number | null>(null)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const test = useStartAvatarTest()
  const sceneId = settings.scene_media_id
  // Задание `avatar_test` стоит на самой сцене; его ход и провал читаем из
  // детали сцены (опрос — пока задание активно), готовую проверку отдают
  // настройки (`scene_test`).
  const scene = useMediaDetail(sceneId, Boolean(sceneId) && settings.avatar_env_enabled)
  const testJob = activeJob(scene.data, 'avatar_test')
  const lastTest = latestJob(scene.data, 'avatar_test')
  const lastKey = lastTest ? `${lastTest.id}:${lastTest.status}` : ''
  useEffect(() => {
    if (lastKey.endsWith(':done') || lastKey.endsWith(':failed')) {
      void qc.invalidateQueries({ queryKey: ['learn-media', 'admin', 'settings'] })
    }
  }, [lastKey, qc])

  const onPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    if (!['image/png', 'image/jpeg', 'image/webp'].includes(file.type)) {
      toast.error('Сцена — PNG, JPEG или WebP')
      return
    }
    if (file.size > SCENE_MAX_BYTES) {
      toast.error('Файл больше 20 МБ')
      return
    }
    setUploadPct(0)
    try {
      const media = await learnApi.uploadMedia(file, {
        role: 'scene',
        onProgress: (f) => setUploadPct(Math.round(f * 100)),
      })
      onSave({ scene_media_id: media.id })
    } catch (err) {
      toast.error('Не удалось загрузить сцену', { description: extractErrorDetail(err) })
    } finally {
      setUploadPct(null)
    }
  }

  const testCost = formatMoney(sceneTestCostCents(settings.avatar_resolution))
  const busy = pending || uploadPct !== null
  return (
    <div className="space-y-3 rounded-xl border border-hair p-3">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[200px_1fr]">
        <div className="aspect-video w-full overflow-hidden rounded-lg bg-surface">
          {settings.scene_url ? (
            <img
              src={settings.scene_url}
              alt="Сцена с гусём"
              className="h-full w-full object-cover"
            />
          ) : (
            <button
              type="button"
              disabled={busy || !settings.enabled}
              onClick={() => input.current?.click()}
              className="flex h-full w-full flex-col items-center justify-center gap-1 text-[13px] font-semibold text-amber hover:bg-glass disabled:opacity-50"
            >
              <ImagePlus className="h-5 w-5" />
              {uploadPct !== null ? `Загрузка ${uploadPct} %` : 'Загрузить сцену 16:9'}
            </button>
          )}
        </div>
        <div className="min-w-0 space-y-2">
          <p className="text-[14px] font-semibold text-text">
            {settings.scene_url ? 'Сцена с гусём' : 'Сцена с гусём не загружена'}
          </p>
          <p className="text-[13px] leading-[1.45] text-text2">
            Это референс для Hedra: она оживляет картинку целиком, клюв и мимика идут за голосом.
            Именно этот кадр встанет вместо спикера, поэтому нужна сцена 16:9: гусь анфас по центру,
            фирменный фон, без текста.
            {!settings.enabled && ' Загрузка доступна при включённом конвейере.'}
          </p>
          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              variant="secondary"
              disabled={busy || !settings.enabled}
              onClick={() => input.current?.click()}
            >
              {uploadPct !== null
                ? `Загрузка ${uploadPct} %`
                : settings.scene_url
                  ? 'Заменить'
                  : 'Загрузить'}
            </Button>
            {sceneId && settings.avatar_env_enabled && (
              <Button
                size="sm"
                disabled={busy || test.isPending || testJob !== null}
                onClick={() => test.mutate()}
              >
                <Play className="h-4 w-4" />
                {testJob
                  ? testJob.status === 'queued'
                    ? 'Ждём очереди…'
                    : 'Hedra рендерит…'
                  : `Проверить на 10 секундах · ≈ ${testCost}`}
              </Button>
            )}
            {sceneId && (
              <Button
                size="sm"
                variant="ghost"
                disabled={busy}
                onClick={() => setConfirmDelete(true)}
              >
                Удалить
              </Button>
            )}
          </div>
          {lastTest?.status === 'failed' && !testJob && (
            <p className="text-[13px] text-red">
              Проверка не удалась: {failureText(lastTest)}.
            </p>
          )}
        </div>
      </div>
      {settings.scene_test && (
        <div className="grid grid-cols-1 gap-3 border-t border-hair pt-3 sm:grid-cols-[200px_1fr]">
          <video
            src={settings.scene_test.url}
            controls
            playsInline
            preload="metadata"
            className="aspect-video w-full rounded-lg bg-black"
          />
          <p className="text-[13px] leading-[1.45] text-text2">
            Проверка от {fmtDate(settings.scene_test.created_at)}: гусь говорит 10 секунд
            встроенным образцом голоса. Если клюв идёт в такт и фон не плывёт — сцена годится;
            иначе замените картинку и проверьте снова.
          </p>
        </div>
      )}
      <input
        ref={input}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        hidden
        onChange={(e) => void onPick(e)}
      />
      <Confirm
        open={confirmDelete}
        onOpenChange={setConfirmDelete}
        title="Убрать сцену гуся?"
        text="Новые заказы гуся станут недоступны, пока не загрузите другую сцену. Сам файл и готовые монтажи останутся."
        confirmLabel="Убрать"
        destructive
        pending={pending}
        onConfirm={() => {
          setConfirmDelete(false)
          onSave({ scene_media_id: null })
        }}
      />
    </div>
  )
}

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', { day: 'numeric', month: 'short' })
}
