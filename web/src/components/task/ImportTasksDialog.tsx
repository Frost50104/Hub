import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { labelKeys } from '@/hooks/useLabels'
import { cn } from '@/lib/cn'
import { tasksApi, type TaskImportReport } from '@/lib/tasks'

/**
 * «Импорт из CSV» — копия ImportDialog сотрудников: файл → «Проверить»
 * (dry-run, отчёт без записи) → «Импортировать». Колонки фиксированного
 * шаблона описаны прямо здесь; сопоставление произвольных колонок — не
 * делаем, пока не понадобится реальный формат.
 */
export function ImportTasksDialog({
  open,
  onOpenChange,
  projectId,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  projectId: string
}) {
  const qc = useQueryClient()
  const [file, setFile] = useState<File | null>(null)
  const [report, setReport] = useState<TaskImportReport | null>(null)
  const [onlyErrors, setOnlyErrors] = useState(false)
  const run = useMutation({
    mutationFn: (dryRun: boolean) => tasksApi.importCsv(projectId, file!, { dryRun }),
    meta: { errorMessage: 'Не удалось импортировать задачи' },
    onSuccess: (result) => {
      setReport(result)
      if (!result.dry_run) {
        toast.success(`Импорт завершён: создано ${result.created}, пропущено ${result.skipped}`)
        qc.invalidateQueries({ queryKey: ['tasks', projectId] })
        qc.invalidateQueries({ queryKey: ['stages', projectId] })
        // Импорт — это созданные мной задачи: «Ваша статистика» их считает.
        qc.invalidateQueries({ queryKey: ['me-tasks'] })
        qc.invalidateQueries({ queryKey: ['me-stats'] })
        qc.invalidateQueries({ queryKey: ['projects'] })
        // Импорт создаёт метки и вешает их на строки — без инвалидации
        // назначений чипы появлялись только после F5 (QA-0821 #8).
        qc.invalidateQueries({ queryKey: labelKeys.all(projectId) })
      }
    },
  })
  const errors = report?.errors ?? []

  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={(v) => {
        onOpenChange(v)
        if (!v) {
          setFile(null)
          setReport(null)
        }
      }}
      title="Импорт задач из CSV"
      description="Колонки: title (обязательная), description, assignee_email, due (ДД.ММ.ГГГГ или ГГГГ-ММ-ДД), priority, section, stage, labels (через |). Разделитель — «;» или «,». Секции, колонки и метки — только существующие; неизвестные — предупреждением, задача всё равно создаётся."
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={run.isPending}>
            Закрыть
          </Button>
          <Button
            variant="secondary"
            disabled={!file || run.isPending}
            onClick={() => run.mutate(true)}
          >
            Проверить
          </Button>
          <Button disabled={!file || run.isPending} onClick={() => run.mutate(false)}>
            {run.isPending ? 'Импортируем…' : 'Импортировать'}
          </Button>
        </>
      }
    >
      <Input
        type="file"
        accept=".csv,text/csv"
        className="h-11 lg:h-10"
        onChange={(e) => {
          setFile(e.target.files?.[0] ?? null)
          setReport(null)
        }}
      />
      {report && (
        <div className="flex flex-col gap-2 rounded-xl border border-glass-border bg-tint p-3.5 text-[14px]">
          <p className="text-text">
            {report.dry_run ? 'Проверка (без сохранения):' : 'Результат:'} создано{' '}
            <b>{report.created}</b>, пропущено <b>{report.skipped}</b>
            {errors.length > 0 && (
              <>
                , замечаний <b>{errors.length}</b>
              </>
            )}
          </p>
          {errors.length > 0 && (
            <>
              <label className="flex items-center gap-2 text-[13px] text-text2">
                <input
                  type="checkbox"
                  checked={onlyErrors}
                  onChange={(e) => setOnlyErrors(e.target.checked)}
                  className="h-4 w-4 accent-[rgb(var(--amber))]"
                />
                Только ошибки строк
              </label>
              <ul className={cn('max-h-48 space-y-1 overflow-y-auto text-[13px] text-text2')}>
                {errors
                  .filter((e) => !onlyErrors || /пропущена|не найден|не распознан/.test(e))
                  .map((err, i) => (
                    <li key={i}>{err}</li>
                  ))}
              </ul>
            </>
          )}
        </div>
      )}
    </ResponsiveDialog>
  )
}
