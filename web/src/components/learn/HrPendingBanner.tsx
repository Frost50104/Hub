import { useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { extractErrorDetail } from '@/lib/errors'
import { HR_FIELD_LABEL, hrValueLabel, type HrField } from '@/lib/hrLock'
import { learnApi, ORG_ROLE_LABEL, type HrPending } from '@/lib/learn'
import { plural } from '@/lib/typography'

const DIRECTORY_KIND: Record<string, string> = {
  position: 'Должность',
  franchisee: 'Франчайзи',
  department: 'Отдел',
  store: 'Точка',
}

const DIRECTORY_ACTION: Record<string, string> = {
  archive: 'в архив',
  restore: 'из архива',
  rename: 'переименование →',
  update: 'описание или порядок',
  reparent: 'новый родитель →',
  franchisee: 'франчайзи →',
}

function fieldLabel(field: string): string {
  return HR_FIELD_LABEL[field as HrField | 'tu_stores'] ?? field
}

/**
 * Предохранитель кадровых данных сработал (16d): из auth пришло больше
 * изменений, чем порог. Плашка — янтарь (акцент «нужно действие»), видна
 * только hub-admin'у: экран «Сотрудники» — его. «Применить» применяет РОВНО
 * показанный набор: сервер сверяет отпечаток и отвечает 409, если в auth
 * за это время что-то поменялось.
 */
export function HrPendingBanner() {
  const [open, setOpen] = useState(false)
  const pending = useQuery({
    queryKey: ['learn-hr-pending'],
    queryFn: learnApi.hrPending,
  })
  const data = pending.data
  if (!data) return null
  return (
    <>
      <div className="flex flex-col gap-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2.5 sm:flex-row sm:items-center sm:gap-3">
        <div className="flex min-w-0 flex-1 items-start gap-2">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber" strokeWidth={1.8} />
          <p className="min-w-0 text-sm text-text">
            Из auth пришло {plural(data.cards, 'изменение', 'изменения', 'изменений')} карточек
            {data.mandatory > 0 &&
              ` и ${plural(data.mandatory, 'новое обязательное членство', 'новых обязательных членства', 'новых обязательных членств')}`}{' '}
            — больше порога. Пока их не подтвердят, они не применяются.
          </p>
        </div>
        <Button size="sm" className="shrink-0 self-start sm:self-auto" onClick={() => setOpen(true)}>
          Посмотреть и применить
        </Button>
      </div>
      {open && <HrPendingDialog pending={data} onClose={() => setOpen(false)} />}
    </>
  )
}

function HrPendingDialog({ pending, onClose }: { pending: HrPending; onClose: () => void }) {
  const qc = useQueryClient()
  const [applying, setApplying] = useState(false)

  const apply = async () => {
    setApplying(true)
    try {
      await learnApi.applyHrPending(pending.fingerprint)
      toast.success('Изменения из auth применены')
      onClose()
    } catch (err) {
      // 409 «набор изменился» / «идёт синхронизация» — текст сервера как есть.
      toast.error(extractErrorDetail(err))
    } finally {
      setApplying(false)
      void qc.invalidateQueries({ queryKey: ['learn-hr-pending'] })
      void qc.invalidateQueries({ queryKey: ['learn-employees'] })
      void qc.invalidateQueries({ queryKey: ['learn-org'] })
    }
  }

  return (
    <Dialog open onOpenChange={(v) => !v && !applying && onClose()}>
      <DialogContent className="max-h-[85vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Изменения из auth ждут подтверждения</DialogTitle>
          <DialogDescription>
            Кадровые данные ведутся в auth. Изменений больше порога
            {pending.reason ? ` (${pending.reason})` : ''}, поэтому Hub их не применил сам.
            «Применить» применит ровно этот набор; если в auth за это время что-то
            поменялось, откройте его снова.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 text-sm">
          {Object.keys(pending.fields).length > 0 && (
            <p className="text-text2">
              {Object.entries(pending.fields)
                .map(([field, n]) => `${fieldLabel(field)}: ${n}`)
                .join(' · ')}
              {pending.mandatory > 0 &&
                ` · новых обязательных членств: ${pending.mandatory}`}
            </p>
          )}

          {pending.items.length > 0 && (
            <ul className="divide-y divide-glass-border rounded-lg border border-glass-border">
              {pending.items.map((item) => (
                <li key={item.id} className="px-3 py-2">
                  <p className="font-medium text-text">{item.full_name}</p>
                  {item.changes.map((c) => (
                    <p key={c.field} className="text-xs text-text2">
                      {fieldLabel(c.field)}: {hrValueLabel(c.field, c.old, ORG_ROLE_LABEL)} →{' '}
                      <span className="text-text">{hrValueLabel(c.field, c.new, ORG_ROLE_LABEL)}</span>
                    </p>
                  ))}
                </li>
              ))}
            </ul>
          )}

          {pending.archive.length > 0 && (
            <div>
              <p className="font-medium text-text">
                В архив — учётка отключена в auth ({pending.archive.length})
              </p>
              <p className="text-xs text-text2">
                {pending.archive.map((p) => p.full_name).join(', ')}
              </p>
            </div>
          )}
          {pending.returns.length > 0 && (
            <div>
              <p className="font-medium text-text">
                Вернутся из архива — учётку включили ({pending.returns.length})
              </p>
              <p className="text-xs text-text2">
                {pending.returns.map((p) => p.full_name).join(', ')}
              </p>
            </div>
          )}

          {pending.directory.length > 0 && (
            <div>
              <p className="font-medium text-text">Справочники</p>
              <ul className="space-y-0.5 text-xs text-text2">
                {pending.directory.map((d, i) => (
                  <li key={i}>
                    {DIRECTORY_KIND[d.kind] ?? d.kind} «{d.name ?? '—'}»:{' '}
                    {DIRECTORY_ACTION[d.action] ?? d.action}
                    {d.value ? ` ${d.value}` : ''}
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button type="button" variant="secondary" onClick={onClose} disabled={applying}>
            Отмена
          </Button>
          <Button type="button" onClick={() => void apply()} disabled={applying}>
            {applying ? 'Применяем…' : 'Применить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
