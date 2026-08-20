import { useMutation, useQueryClient } from '@tanstack/react-query'
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
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { extractErrorDetail } from '@/lib/errors'
import { assistantApi, type Plan, type PlanPatchBody } from '@/lib/assistant'

/**
 * «Изменить поля» правит ПАРАМЕТРЫ действия, но не его объект: проект и
 * набор задач не меняются. Сменить объект — значит задать другое действие,
 * и честнее попросить словами, чем прятать это в форму правки.
 *
 * Сервер пересобирает карточку из тех же args, что исполнятся: подтверждать
 * одно, а выполнять другое — невозможно by design.
 */
function currentValue(plan: Plan, label: string): string {
  return plan.fields.find((f) => f.label === label)?.value ?? ''
}

export function PlanEditDialog({
  plan,
  conversationId,
  onClose,
}: {
  plan: Plan
  conversationId: string
  onClose: () => void
}) {
  const qc = useQueryClient()
  const isCreate = plan.tool === 'create_task'
  const isComment = plan.tool === 'add_comment'

  const [title, setTitle] = useState(currentValue(plan, 'Заголовок'))
  const [text, setText] = useState(currentValue(plan, 'Комментарий'))
  const [dueAt, setDueAt] = useState('')
  const [priority, setPriority] = useState(
    plan.fields.find((f) => f.chip === 'priority')?.chip_text ?? '',
  )
  const [assignees, setAssignees] = useState('')

  const save = useMutation({
    mutationFn: () => {
      const body: PlanPatchBody = {}
      if (isCreate && title.trim() && title !== currentValue(plan, 'Заголовок')) {
        body.title = title.trim()
      }
      if (isComment && text.trim() && text !== currentValue(plan, 'Комментарий')) {
        body.text = text.trim()
      }
      if (dueAt) body.due_at = dueAt
      if (priority && priority !== plan.fields.find((f) => f.chip === 'priority')?.chip_text) {
        body.priority = priority as PlanPatchBody['priority']
      }
      if (assignees.trim()) {
        body.assignees = assignees
          .split(',')
          .map((s) => s.trim())
          .filter(Boolean)
      }
      return assistantApi.patchPlan(plan.id, body)
    },
    meta: { suppressGlobalError: true },
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['assistant-messages', conversationId] })
      onClose()
    },
    onError: (e) =>
      toast.error('Не удалось изменить план', { description: extractErrorDetail(e) }),
  })

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Изменить поля</DialogTitle>
          <DialogDescription>
            Проект и объект действия остаются прежними — их меняют новой командой.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-3">
          {isCreate && (
            <div>
              <Label htmlFor="plan-title">Заголовок</Label>
              <Input
                id="plan-title"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
              />
            </div>
          )}
          {isComment && (
            <div>
              <Label htmlFor="plan-text">Комментарий</Label>
              <Input
                id="plan-text"
                value={text}
                onChange={(e) => setText(e.target.value)}
              />
            </div>
          )}
          {!isComment && (
            <>
              <div>
                <Label htmlFor="plan-due">Срок</Label>
                <Input
                  id="plan-due"
                  type="date"
                  value={dueAt}
                  onChange={(e) => setDueAt(e.target.value)}
                />
              </div>
              <div>
                <Label htmlFor="plan-priority">Приоритет</Label>
                <Select
                  id="plan-priority"
                  value={priority}
                  onChange={(e) => setPriority(e.target.value)}
                >
                  <option value="low">Низкий</option>
                  <option value="medium">Обычный</option>
                  <option value="high">Высокий</option>
                  <option value="urgent">Срочный</option>
                </Select>
              </div>
            </>
          )}
          {isCreate && (
            <div>
              <Label htmlFor="plan-assignees">Исполнители</Label>
              <Input
                id="plan-assignees"
                placeholder="Фамилии через запятую — пусто, чтобы не менять"
                value={assignees}
                onChange={(e) => setAssignees(e.target.value)}
              />
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            Отмена
          </Button>
          <Button disabled={save.isPending} onClick={() => save.mutate()}>
            {save.isPending ? 'Сохраняю…' : 'Сохранить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
