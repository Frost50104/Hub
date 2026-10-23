import { useEffect, useState } from 'react'

import { Button } from '@/components/ui/Button'
import { Confirm } from '@/components/ui/Confirm'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import { useMediaAdminSettings, useUpdateMediaAdminSettings } from '@/hooks/useMediaJobs'
import { cn } from '@/lib/cn'
import type { MediaAdminSettings } from '@/lib/learn'

/**
 * «Управление → Видео» (0066, макет AdminVideoFull): тумблер модуля,
 * расшифровка, глоссарий, лимит гуся. Сцена гуся и «Проверить на 10
 * секундах» — вместе с заданием `avatar_test` (инкремент 7). Сегмент виден
 * только при `me.features.media_pipeline_admin`.
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
  return (
    <Section
      title="Гусь (аватар)"
      hint={
        settings.avatar_env_enabled
          ? 'Говорящий гусь вместо спикера через Hedra. Сцена-референс и проверка на 10 секундах появятся в следующем выпуске.'
          : 'Гусь на этом сервере выключен: нет ключа Hedra. Лимит и качество можно задать заранее.'
      }
    >
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
          </p>
        </div>
        <div>
          <Label htmlFor="media-res">Качество по умолчанию</Label>
          <Select
            id="media-res"
            value={settings.avatar_resolution}
            disabled={pending}
            onChange={(e) =>
              onSave({
                avatar_resolution: e.target.value as MediaAdminSettings['avatar_resolution'],
              })
            }
          >
            <option value="540p">540p · $1,50/мин</option>
            <option value="720p">720p · $3,00/мин</option>
            <option value="1080p">1080p · $3,75/мин</option>
          </Select>
        </div>
      </div>
    </Section>
  )
}
