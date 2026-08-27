import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'

import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { useDeleteProject } from '@/hooks/useProjects'
import {
  confirmKeyMatches,
  describeProjectBlastRadius,
} from '@/lib/projectAbout'
import { type Project } from '@/lib/projects'

/**
 * Подтверждение удаления проекта.
 *
 * Ввод ключа — защита от ПРОМАХА, не от диверсии, поэтому ключ показан рядом
 * с полем, а регистр и пробелы не важны: заставлять жать Caps Lock ради «PLP»
 * враждебно. Сервер проверяет ключ второй раз — он ловит другое: рассинхрон
 * между тем, что человек прочитал в диалоге, и id, ушедшим в запрос.
 *
 * Радиус поражения считаем из счётчика, который уже есть в ответе проекта
 * (`task_count`), отдельной ручки ради этого не заводим. Он считает неархивные
 * задачи ВЕРХНЕГО уровня, то есть занижен относительно каскада — текст поэтому
 * говорит и про «вместе с задачами», не обещая точного числа.
 */
export function DeleteProjectDialog({
  project,
  open,
  onOpenChange,
}: {
  project: Project
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [input, setInput] = useState('')
  const remove = useDeleteProject(project.id)
  const navigate = useNavigate()

  useEffect(() => {
    if (open) setInput('')
  }, [open])

  const armed = confirmKeyMatches(input, project.key)

  const submit = async () => {
    if (!armed || remove.isPending) return
    try {
      await remove.mutateAsync(project.key)
      toast.success(`Проект «${project.name}» удалён`)
      // Уходим ПОСЛЕ onSuccess: иначе removeQueries отработает на уже
      // размонтированном дереве и страница успеет мигнуть ошибкой.
      navigate('/projects', { replace: true })
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      // Пока удаляем — диалог не закрываем: закрыть нечем, а исчезнувшая
      // модалка выглядит как «получилось».
      onOpenChange={(v) => !remove.isPending && onOpenChange(v)}
      title={`Удалить проект «${project.name}»?`}
      description="Это необратимо. Корзины нет — восстановить можно будет только из ночного бэкапа."
      desktopWidth={480}
      footer={
        <>
          <Button
            type="button"
            variant="secondary"
            onClick={() => onOpenChange(false)}
            disabled={remove.isPending}
          >
            Отмена
          </Button>
          <Button
            type="button"
            variant="destructive"
            onClick={submit}
            disabled={!armed || remove.isPending}
          >
            {remove.isPending ? 'Удаляем…' : 'Удалить навсегда'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-4">
        <p className="m-0 rounded-xl border border-hair bg-tint p-3 text-sm text-text">
          {describeProjectBlastRadius({
            tasks: project.task_count ?? 0,
            attachments: 0,
          })}
        </p>
        <div className="flex flex-col gap-1.5">
          <label className="text-sm text-text2" htmlFor="confirm-key">
            Чтобы подтвердить, введите ключ проекта —{' '}
            <span className="font-mono font-semibold text-text">{project.key}</span>
          </label>
          <Input
            id="confirm-key"
            value={input}
            autoComplete="off"
            spellCheck={false}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') void submit()
            }}
            placeholder={project.key}
          />
        </div>
      </div>
    </ResponsiveDialog>
  )
}
