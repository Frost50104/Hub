import { useEffect, useMemo, useState } from 'react'

import { Button } from '@/components/ui/Button'
import { DateField } from '@/components/ui/DateField'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { SegmentGroup } from '@/components/ui/SegmentGroup'
import { Select } from '@/components/ui/Select'
import { useOrgSnapshot } from '@/hooks/useLearn'
import { cn } from '@/lib/cn'
import type { ContestDraft } from '@/lib/race'
import { contestEndsOn, leagueOverlaps, racesPreview, validateContestDraft, type ContestFormDraft } from '@/lib/raceAdmin'
import { humanDate, todayKey } from '@/lib/taskDates'
import { plural } from '@/lib/typography'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
  initial: ContestFormDraft
  /** Даты/длину/базу можно менять только в черновике; лиги — до старта. */
  shapeEditable: boolean
  leaguesEditable: boolean
  submitLabel: string
  pending: boolean
  onSubmit: (draft: ContestDraft) => void
}

/**
 * Форма конкурса: название, старт, длина заезда с превью автосгенерированных
 * заездов, режим и ретро-период базы, лиги из «групп точек» с проверкой
 * пересечений (зеркало серверного 422). Submit заблокирован до `ok`.
 */
export function ContestFormDialog({ open, onOpenChange, initial, shapeEditable, leaguesEditable, submitLabel, pending, onSubmit }: Props) {
  const org = useOrgSnapshot()
  const [draft, setDraft] = useState<ContestFormDraft>(initial)
  const [touched, setTouched] = useState(false)
  useEffect(() => {
    if (open) {
      setDraft(initial)
      setTouched(false)
    }
  }, [open, initial])

  const today = todayKey()
  const { ok, errors } = validateContestDraft(draft, today, !shapeEditable)
  const groups = useMemo(() => org.data?.store_groups ?? [], [org.data])
  const stores = useMemo(() => org.data?.stores ?? [], [org.data])
  const overlaps = useMemo(() => leagueOverlaps(draft.league_group_ids, groups, stores), [draft.league_group_ids, groups, stores])
  const preview = racesPreview(draft.starts_on, draft.weeks_total, draft.race_length_days)
  const liveStoreIds = useMemo(() => new Set(stores.filter((s) => !s.archived_at).map((s) => s.id)), [stores])
  const canSubmit = ok && overlaps.length === 0 && !pending

  const set = <K extends keyof ContestFormDraft>(key: K, value: ContestFormDraft[K]) => {
    setTouched(true)
    setDraft((d) => ({ ...d, [key]: value }))
  }
  const err = (key: keyof ContestFormDraft) => (touched && errors[key] ? <p className="mt-1 text-[13px] text-red">{errors[key]}</p> : null)

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={submitLabel === 'Создать' ? 'Новое соревнование' : 'Настройки соревнования'}
      description="Заезды сгенерируются автоматически при планировании."
      desktopWidth={640}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button disabled={!canSubmit} onClick={() => onSubmit({ ...draft, title: draft.title.trim() })}>
            {pending ? 'Сохраняем…' : submitLabel}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <div>
          <Label htmlFor="race-title">Название</Label>
          <Input id="race-title" value={draft.title} maxLength={120} onChange={(e) => set('title', e.target.value)} />
          {err('title')}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="race-start">Старт</Label>
            <DateField id="race-start" value={draft.starts_on} onChange={(v) => set('starts_on', v)} disabled={!shapeEditable} />
            {err('starts_on')}
            {draft.starts_on && !errors.starts_on && !errors.weeks_total && (
              <p className="mt-1 text-[13px] text-text2">Окончание: {humanDate(contestEndsOn(draft.starts_on, draft.weeks_total))}</p>
            )}
          </div>
          <div>
            <Label htmlFor="race-weeks">Недель</Label>
            <Input
              id="race-weeks"
              type="number"
              min={1}
              max={12}
              value={draft.weeks_total}
              disabled={!shapeEditable}
              onChange={(e) => set('weeks_total', Number(e.target.value))}
            />
            {err('weeks_total')}
          </div>
        </div>
        <div>
          <Label>Длина заезда</Label>
          <SegmentGroup
            ariaLabel="Длина заезда"
            options={[
              { value: '7', label: '7 дней', disabled: !shapeEditable },
              { value: '14', label: '14 дней', disabled: !shapeEditable },
            ]}
            value={String(draft.race_length_days)}
            onChange={(v) => set('race_length_days', v === '14' ? 14 : 7)}
            size="md"
          />
          {err('race_length_days')}
          {preview.length > 0 && (
            <ul className="mt-2 flex flex-col gap-0.5 text-[13px] text-text2">
              {preview.map((r) => (
                <li key={r.seq}>
                  Заезд {r.seq} · {humanDate(r.starts_on)} — {humanDate(r.ends_on)}
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="grid gap-4 sm:grid-cols-2">
          <div>
            <Label htmlFor="race-mode">Базовый уровень</Label>
            <Select id="race-mode" value={draft.baseline_mode} disabled={!shapeEditable} onChange={(e) => set('baseline_mode', e.target.value as 'contest' | 'race')}>
              <option value="contest">На всё соревнование</option>
              <option value="race">На каждый заезд заново</option>
            </Select>
            <p className="mt-1 text-[13px] text-text2">
              {draft.baseline_mode === 'contest' ? 'База считается один раз перед стартом.' : 'Перед каждым заездом база пересчитывается по ретро-периоду до него.'}
            </p>
          </div>
          <div>
            <Label htmlFor="race-retro">Ретро-период базы, дней</Label>
            <Input id="race-retro" type="number" min={7} max={92} value={draft.baseline_days} disabled={!shapeEditable} onChange={(e) => set('baseline_days', Number(e.target.value))} />
            {err('baseline_days')}
          </div>
        </div>
        <div>
          <Label>Лиги (группы точек)</Label>
          {groups.length === 0 ? (
            <p className="text-[13px] text-text2">Групп точек нет — заведите их в «Оргструктуре», если нужны лиги. Без лиг гонка идёт одним забегом.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {groups.map((g) => {
                const checked = draft.league_group_ids.includes(g.id)
                const size = g.member_ids.filter((id) => liveStoreIds.has(id)).length
                return (
                  <label key={g.id} className={cn('flex items-center gap-3 rounded-lg border px-3 py-2 text-[14px]', checked ? 'border-amber/55 bg-amber/[0.06]' : 'border-hair', !leaguesEditable && 'opacity-60')}>
                    <input
                      type="checkbox"
                      className="h-4 w-4 accent-amber"
                      checked={checked}
                      disabled={!leaguesEditable}
                      onChange={(e) =>
                        set('league_group_ids', e.target.checked ? [...draft.league_group_ids, g.id] : draft.league_group_ids.filter((x) => x !== g.id))
                      }
                    />
                    <span className="min-w-0 flex-1 truncate text-text">{g.name}</span>
                    <span className="shrink-0 text-[12px] text-text2">{plural(size, 'точка', 'точки', 'точек')}</span>
                  </label>
                )
              })}
            </div>
          )}
          {overlaps.length > 0 && (
            <p className="mt-2 text-[13px] text-red">
              Точки в двух лигах: {overlaps.map((o) => `${o.name} (${o.groupNames.join(', ')})`).join('; ')}. Уберите точку из одной группы.
            </p>
          )}
        </div>
      </div>
    </ResponsiveDialog>
  )
}
