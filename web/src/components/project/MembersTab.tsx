import { Trash2, UserPlus } from 'lucide-react'
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { toast } from 'sonner'
import { useQueryClient } from '@tanstack/react-query'

import { PeoplePicker } from '@/components/PeoplePicker'
import { QueryError } from '@/components/QueryError'
import { Avatar } from '@/components/ui/Avatar'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { useMe } from '@/hooks/useMe'
import {
  projectKeys,
  useAddMember,
  useProjectMembers,
  useRemoveMember,
  useUpdateMember,
} from '@/hooks/useProjects'
import {
  PROJECT_ROLE_LABEL as ROLE_LABEL,
  type ProjectMember,
  type ProjectRole,
} from '@/lib/projects'

const ROLES: ProjectRole[] = ['owner', 'editor', 'viewer']

const SELECT_CLASS =
  'h-8 rounded-md border border-glass-border bg-glass px-2 text-xs text-text focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-amber/60'

interface MembersTabProps {
  projectId: string
  /** owner может добавлять/удалять участников и менять роли. */
  canManage: boolean
}

export function MembersTab({ projectId, canManage }: MembersTabProps) {
  const members = useProjectMembers(projectId)
  const me = useMe()
  const add = useAddMember(projectId)
  const updateMember = useUpdateMember(projectId)
  const removeMember = useRemoveMember(projectId)
  const qc = useQueryClient()
  const nav = useNavigate()

  const [newPersonId, setNewPersonId] = useState<string | null>(null)
  const [newRole, setNewRole] = useState<ProjectRole>('editor')

  const memberIds = (members.data ?? []).map((m) => m.employee_id)

  const onAdd = async () => {
    if (!newPersonId) return
    try {
      await add.mutateAsync({ employee_id: newPersonId, role: newRole })
      toast.success('Участник добавлен')
      setNewPersonId(null)
      setNewRole('editor')
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  const onRemove = async (m: ProjectMember) => {
    const isSelf = m.employee_id === me.data?.employee_id
    const message = isSelf
      ? 'Выйти из проекта? Вы потеряете к нему доступ.'
      : `Убрать ${m.full_name || m.email || 'участника'} из проекта?`
    if (!confirm(message)) return
    try {
      await removeMember.mutateAsync(m.id)
      if (isSelf) {
        await qc.invalidateQueries({ queryKey: projectKeys.all })
        nav('/projects')
      } else {
        toast.success('Участник удалён')
      }
    } catch {
      // тост (включая «последний owner») показывает глобальный onError мутаций
    }
  }

  return (
    <div className="space-y-2">
      {members.isLoading && <p className="text-text2">Загружаем участников…</p>}
      {members.isError && (
        <QueryError
          error={members.error}
          onRetry={() => void members.refetch()}
          title="Не удалось загрузить участников"
        />
      )}
      {members.data && members.data.length === 0 && (
        <p className="text-text2">Пока нет участников.</p>
      )}

      {members.data?.map((m) => (
        <div key={m.id} className="glass flex items-center justify-between gap-3 p-3">
          <div className="flex min-w-0 items-center gap-3">
            <Avatar name={m.full_name} email={m.email} />
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-text">
                {m.full_name || m.email || m.employee_id}
                {m.employee_id === me.data?.employee_id && (
                  <span className="ml-1 text-xs text-text3">(вы)</span>
                )}
              </p>
              {m.email && <p className="truncate text-xs text-text3">{m.email}</p>}
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {canManage ? (
              <select
                value={m.role}
                onChange={(e) =>
                  updateMember.mutate({
                    memberId: m.id,
                    role: e.target.value as ProjectRole,
                  })
                }
                disabled={updateMember.isPending}
                aria-label={`Роль: ${m.full_name || m.email || ''}`}
                className={SELECT_CLASS}
              >
                {ROLES.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </select>
            ) : (
              <Badge variant={m.role === 'owner' ? 'default' : 'secondary'}>
                {ROLE_LABEL[m.role]}
              </Badge>
            )}
            {canManage && (
              <Button
                variant="ghost"
                size="icon"
                onClick={() => void onRemove(m)}
                disabled={removeMember.isPending}
                aria-label={`Убрать из проекта: ${m.full_name || m.email || ''}`}
              >
                <Trash2 className="h-4 w-4 text-red" />
              </Button>
            )}
          </div>
        </div>
      ))}

      {canManage && (
        <div className="space-y-2 pt-3">
          <h3 className="text-xs font-semibold uppercase tracking-wider text-text3">
            Добавить участника
          </h3>
          <div className="flex flex-wrap items-center gap-2">
            <div className="w-full max-w-[260px]">
              <PeoplePicker
                value={newPersonId}
                onChange={setNewPersonId}
                excludeIds={memberIds}
                placeholder="Выберите сотрудника"
                allowClear={false}
              />
            </div>
            <select
              value={newRole}
              onChange={(e) => setNewRole(e.target.value as ProjectRole)}
              aria-label="Роль нового участника"
              className={SELECT_CLASS}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
            <Button
              size="sm"
              onClick={() => void onAdd()}
              disabled={!newPersonId || add.isPending}
            >
              <UserPlus className="h-4 w-4" />
              Добавить
            </Button>
          </div>
          <p className="text-xs text-text3">
            В списке — сотрудники, которые хотя бы раз заходили в Hub.
          </p>
        </div>
      )}
    </div>
  )
}
