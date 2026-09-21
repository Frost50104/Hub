import { Settings } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { Markdown } from '@/components/Markdown'
import { DeleteProjectDialog } from '@/components/project/DeleteProjectDialog'
import { SaveAsTemplateDialog } from '@/components/project/SaveAsTemplateDialog'
import { ProjectBadgePicker } from '@/components/project/ProjectBadgePicker'
import { ProjectKeyChip } from '@/components/project/ProjectKeyChip'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { InfoRow, InfoRows } from '@/components/ui/InfoRows'
import { Input, Textarea } from '@/components/ui/Input'
import { Skeleton } from '@/components/ui/Skeleton'
import { DrawerSection } from '@/components/task/DrawerSection'
import { useMe } from '@/hooks/useMe'
import { useArchiveProject, useProjectMembers, useUpdateProject } from '@/hooks/useProjects'
import {
  forgetProjectDraft,
  projectAboutGate,
  projectNameError,
  projectProfileDirty,
  projectProfileDraft,
  projectProfilePatch,
  projectSummaryRows,
  rememberProjectDraft,
  restoreProjectDraft,
  type ProjectAboutGate,
  type ProjectProfileDraft,
} from '@/lib/projectAbout'
import { templatesEnabled } from '@/lib/projectTemplates'
import { PROJECT_ROLE_LABEL, type Project } from '@/lib/projects'

const DESCRIPTION_MAX = 20_000

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString('ru-RU', {
    day: 'numeric',
    month: 'long',
    year: 'numeric',
  })
}

/**
 * «О проекте» — карточка проекта, а под кнопкой «Настройки проекта» его правка.
 *
 * Экран видят ВСЕ, включая наблюдателя: описание может быть на страницу, а в
 * шапке оно урезано в строку и на телефоне не показывается вовсе. Поэтому по
 * умолчанию здесь чтение, а форма — отдельный режим.
 *
 * Права считает ОДНА чистая функция `projectAboutGate` (`lib/projectAbout.ts`),
 * а не набор тернарников по разметке: правил шесть, и два из них не выводятся
 * из ролей (архив и удаление недоступны у личного проекта, импорт — у
 * архивного). В JSX такие правила гниют молча.
 *
 * Гейт правки — `can_edit`: с 27.08 `PATCH /projects/{id}` и обе ручки бейджа
 * стоят на `EDIT_ROLES`, то есть редактор правит профиль наравне с владельцем.
 * Архив и удаление остались у владельца.
 *
 * Режим — локальный `useState`, НЕ параметр URL. Ссылка `?edit=1`, посланная
 * наблюдателю, была бы обещанием, которое приложение обязано нарушить, — и
 * пришлось бы, как на `/learn/admin`, переписывать недоступный параметр
 * эффектом на монтировании. Плата: «Назад» уводит со страницы проекта, а не из
 * настроек; это согласуется с тем, что и смена вкладки идёт через `replace`.
 *
 * Три кнопки — три разных смысла, не «консолидировать»:
 *   Сохранить — сохранить и остаться;
 *   Отменить  — вернуть серверные значения и остаться;
 *   Готово    — сохранить и выйти в чтение.
 */
export function AboutTab({
  project,
  onImport,
}: {
  project: Project
  onImport: () => void
}) {
  const [mode, setMode] = useState<'read' | 'settings'>('read')
  const [focusDescription, setFocusDescription] = useState(false)
  const [draft, setDraft] = useState(() => restoreProjectDraft(project.id, project))
  const update = useUpdateProject(project.id)
  // Через ref, а не через зависимость: иначе эффект-«запомни» пересоздавался бы
  // на каждое нажатие клавиши и коммитил бы черновик не в тот момент.
  const draftRef = useRef(draft)
  draftRef.current = draft

  const me = useMe().data
  const gate = projectAboutGate(project, {
    templatesOn: templatesEnabled(me),
    canCreateProjects: me?.can_create_projects === true,
  })

  // Сервер — источник истины, но только когда он ДЕЙСТВИТЕЛЬНО изменился.
  // Сравнение с предыдущим ответом обязательно: без него эффект срабатывает и
  // на монтировании, то есть стирает черновик, который только что восстановил
  // useState. Зависимости — примитивы, а не сам `project`: объект приходит из
  // кэша новым на каждый refetch.
  const serverRef = useRef({ name: project.name, description: project.description })
  useEffect(() => {
    const prev = serverRef.current
    if (prev.name === project.name && prev.description === project.description) return
    serverRef.current = { name: project.name, description: project.description }
    forgetProjectDraft(project.id)
    setDraft(projectProfileDraft(project))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project.id, project.name, project.description])

  // Уходя со вкладки — запоминаем несохранённое: вид переключается кнопкой, и
  // 20 000 знаков не должны исчезать молча.
  useEffect(
    () => () => {
      rememberProjectDraft(project.id, draftRef.current)
    },
    [project.id],
  )

  // Права закрылись посреди сессии (роль понизили, прилетел фоновый рефетч по
  // фокусу окна) — форма обязана исчезнуть. Иначе у понижённого редактора
  // остаётся живой экран, каждое сохранение из которого отвечает 403.
  useEffect(() => {
    if (!gate.canOpenSettings) {
      setMode('read')
      forgetProjectDraft(project.id)
    }
  }, [gate.canOpenSettings, project.id])

  const patch = projectProfilePatch(draft, project)
  const nameError = projectNameError(draft.name)

  const save = async (): Promise<boolean> => {
    if (nameError || update.isPending) return false
    if (!patch) return true
    try {
      await update.mutateAsync(patch)
      forgetProjectDraft(project.id)
      toast.success('Проект обновлён')
      return true
    } catch {
      // тост показывает глобальный onError мутаций
      return false
    }
  }

  const resetDraft = () => {
    forgetProjectDraft(project.id)
    setDraft(projectProfileDraft(project))
  }

  if (mode === 'settings') {
    return (
      <AboutSettings
        project={project}
        gate={gate}
        draft={draft}
        setDraft={setDraft}
        nameError={nameError}
        dirty={patch !== null}
        saving={update.isPending}
        autoFocusDescription={focusDescription}
        onSave={save}
        onReset={resetDraft}
        onImport={onImport}
        onDone={async () => {
          // «Готово» означает «готово»: сохраняем и выходим. Иначе режим чтения
          // показал бы серверный текст поверх живого черновика, а молчание
          // читается как «сохранилось».
          if (await save()) setMode('read')
        }}
      />
    )
  }

  return (
    <AboutRead
      project={project}
      gate={gate}
      hasDraft={gate.canEditProfile && projectProfileDirty(draft, project)}
      onOpenSettings={(focus) => {
        setFocusDescription(focus === 'description')
        setMode('settings')
      }}
      onResetDraft={resetDraft}
    />
  )
}

/* ── Режим чтения ────────────────────────────────────────────────────────── */

function AboutRead({
  project,
  gate,
  hasDraft,
  onOpenSettings,
  onResetDraft,
}: {
  project: Project
  gate: ProjectAboutGate
  hasDraft: boolean
  onOpenSettings: (focus?: 'description') => void
  onResetDraft: () => void
}) {
  // Ручка участников READ-tier — наблюдателю разрешена, и обычно это попадание
  // в кэш: список задач зовёт тот же хук.
  const members = useProjectMembers(project.id)
  const isArchived = Boolean(project.archived_at)

  const rows = projectSummaryRows({
    key: project.key,
    createdLabel: formatDate(project.created_at),
    task_count: project.task_count,
    done_count: project.done_count,
    memberCount: members.data?.length ?? (members.isError ? 0 : null),
    ownerNames: (members.data ?? [])
      .filter((m) => m.role === 'owner')
      .map((m) => m.full_name || m.email || 'без имени'),
  })
  if (project.created_from_template?.name) {
    rows.push({ kind: 'text', label: 'Создан по шаблону', value: project.created_from_template.name })
  }

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-7">
      {/* flex-wrap + basis: ниже ~420px кнопка уезжает на свою строку, а не
          сжимает название в столбик по букве. */}
      <div className="flex flex-wrap items-start gap-3">
        <ProjectKeyChip project={project} size="xl" />
        <div className="min-w-0 flex-1 basis-[200px]">
          <h2 className="m-0 font-display text-xl font-bold leading-[1.2] text-text">
            {project.name}
          </h2>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            {isArchived && <Badge variant="secondary">архив</Badge>}
            {project.my_role && (
              <Badge variant="secondary">{PROJECT_ROLE_LABEL[project.my_role]}</Badge>
            )}
          </div>
        </div>
        {gate.canOpenSettings && (
          <Button
            type="button"
            variant="secondary"
            size="sm"
            className="shrink-0 bg-transparent"
            onClick={() => onOpenSettings()}
          >
            <Settings className="h-4 w-4" />
            Настройки проекта
          </Button>
        )}
      </div>

      <InfoRows>
        {rows.map((row) => (
          <InfoRow key={row.label} label={row.label}>
            {row.kind === 'pending' ? (
              <Skeleton className="ml-auto h-4 w-24" />
            ) : row.kind === 'key' ? (
              <Badge variant="outline" className="font-mono">
                {row.value}
              </Badge>
            ) : (
              row.value
            )}
          </InfoRow>
        ))}
      </InfoRows>

      {hasDraft && (
        // Нейтральная карточка, не амбер: амбер в системе — акцент и создание,
        // залитая карточка прочиталась бы как призыв к действию.
        <div className="flex flex-col items-start gap-2 rounded-xl border border-hair bg-tint p-4">
          <p className="m-0 text-sm text-text2">
            Есть несохранённые правки названия или описания — они ждут в настройках.
          </p>
          <div className="flex flex-wrap items-center gap-2">
            <Button type="button" size="sm" onClick={() => onOpenSettings()}>
              Продолжить правку
            </Button>
            <Button type="button" size="sm" variant="secondary" onClick={onResetDraft}>
              Отменить правки
            </Button>
          </div>
        </div>
      )}

      {isArchived && (
        <p className="m-0 text-sm text-text2">
          Проект в архиве: он скрыт из списков, но цел — задачи, история и вложения
          на месте.
          {!gate.canArchive && ' Вернуть его может владелец.'}
        </p>
      )}

      <DrawerSection title="Описание">
        {project.description ? (
          <Markdown text={project.description} />
        ) : gate.canEditProfile ? (
          // Пустое состояние приглашает, а не сообщает — идиома карточки задачи.
          <button
            type="button"
            onClick={() => onOpenSettings('description')}
            className="w-full rounded-lg border border-dashed border-glass-border px-3 py-2.5 text-left text-[15px] text-text2 transition-colors hover:border-amber hover:text-text"
          >
            Суть проекта, договорённости, ссылки. Поддерживается markdown.
          </button>
        ) : (
          <p className="m-0 text-sm text-text2">Описания пока нет.</p>
        )}
      </DrawerSection>
    </div>
  )
}

/* ── Режим настроек ──────────────────────────────────────────────────────── */

function AboutSettings({
  project,
  gate,
  draft,
  setDraft,
  nameError,
  dirty,
  saving,
  autoFocusDescription,
  onSave,
  onReset,
  onImport,
  onDone,
}: {
  project: Project
  gate: ProjectAboutGate
  draft: ProjectProfileDraft
  setDraft: (fn: (d: ProjectProfileDraft) => ProjectProfileDraft) => void
  nameError: string | null
  dirty: boolean
  saving: boolean
  autoFocusDescription: boolean
  onSave: () => Promise<boolean>
  onReset: () => void
  onImport: () => void
  onDone: () => void
}) {
  const [badgeOpen, setBadgeOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false)
  const archive = useArchiveProject(project.id)
  const isArchived = Boolean(project.archived_at)

  const toggleArchive = async () => {
    try {
      await archive.mutateAsync(!isArchived)
      toast.success(isArchived ? 'Проект возвращён из архива' : 'Проект в архиве')
    } catch {
      // тост показывает глобальный onError мутаций
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-[720px] flex-col gap-7">
      <div className="flex flex-wrap items-center gap-3">
        <h2 className="m-0 min-w-0 flex-1 basis-[200px] font-display text-xl font-bold leading-[1.2] text-text">
          Настройки проекта
        </h2>
        {/* Та же позиция, что у «Настроек проекта» в чтении: глаз не ищет. */}
        <Button
          type="button"
          variant="secondary"
          size="sm"
          className="shrink-0 bg-transparent"
          onClick={onDone}
          disabled={Boolean(nameError) || saving}
          title={nameError ?? undefined}
        >
          {saving ? 'Сохраняем…' : 'Готово'}
        </Button>
      </div>

      {gate.canEditProfile && (
        <DrawerSection title="Значок и название">
          <div className="flex items-start gap-3">
            <div className="flex flex-col items-center gap-1.5">
              <ProjectKeyChip project={project} size="xl" />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                onClick={() => setBadgeOpen(true)}
              >
                Изменить
              </Button>
            </div>
            <div className="flex min-w-0 flex-1 flex-col gap-1.5">
              <Input
                value={draft.name}
                aria-label="Название проекта"
                maxLength={255}
                onChange={(e) => setDraft((d) => ({ ...d, name: e.target.value }))}
              />
              {nameError && <p className="m-0 text-sm text-red">{nameError}</p>}
              <p className="m-0 flex items-center gap-2 text-sm text-text2">
                <Badge variant="outline" className="font-mono">
                  {project.key}
                </Badge>
                Ключ не меняется: он стоит в номерах задач и в ссылках на них.
              </p>
            </div>
          </div>
        </DrawerSection>
      )}

      {gate.canEditProfile && (
        <DrawerSection
          title="Описание"
          count={`${draft.description.length} / ${DESCRIPTION_MAX}`}
        >
          <Textarea
            value={draft.description}
            aria-label="Описание проекта"
            rows={10}
            maxLength={DESCRIPTION_MAX}
            autoFocus={autoFocusDescription}
            placeholder="Суть проекта, договорённости, ссылки. Поддерживается markdown."
            onChange={(e) => setDraft((d) => ({ ...d, description: e.target.value }))}
          />
          {draft.description && (
            <details className="text-sm text-text2">
              <summary className="cursor-pointer select-none">Просмотр</summary>
              <div className="mt-2">
                <Markdown text={draft.description} />
              </div>
            </details>
          )}
        </DrawerSection>
      )}

      {dirty && (
        <div className="flex items-center gap-2 lg:sticky lg:bottom-0 lg:bg-bg lg:py-2">
          <Button
            type="button"
            onClick={() => void onSave()}
            disabled={Boolean(nameError) || saving}
          >
            {saving ? 'Сохраняем…' : 'Сохранить'}
          </Button>
          <Button type="button" variant="secondary" onClick={onReset} disabled={saving}>
            Отменить
          </Button>
        </div>
      )}

      {gate.canImport && (
        <DrawerSection title="Импорт задач">
          <div className="flex flex-col items-start gap-2">
            <Button type="button" variant="secondary" onClick={onImport}>
              Импорт из CSV…
            </Button>
            <p className="m-0 text-sm text-text2">
              Загрузит задачи списком: название, исполнитель, срок, приоритет, метки.
            </p>
          </div>
        </DrawerSection>
      )}

      {gate.canSaveAsTemplate && (
        <DrawerSection title="Шаблон">
          <div className="flex flex-col items-start gap-2">
            <Button type="button" variant="secondary" onClick={() => setSaveTemplateOpen(true)}>
              Сохранить как шаблон…
            </Button>
            <p className="m-0 text-sm text-text2">
              Колонки, метки, задачи со сроками и люди станут заготовкой в общей библиотеке.
              Проект останется как есть.
            </p>
          </div>
        </DrawerSection>
      )}

      {gate.canArchive && (
        <DrawerSection title="Архив">
          <div className="flex flex-col items-start gap-2">
            <Button
              type="button"
              variant="secondary"
              onClick={toggleArchive}
              disabled={archive.isPending}
            >
              {isArchived ? 'Разархивировать' : 'Архивировать'}
            </Button>
            <p className="m-0 text-sm text-text2">
              Архивный проект прячется из списков, но остаётся целиком: задачи, история
              и вложения на месте.
            </p>
          </div>
        </DrawerSection>
      )}

      {gate.canDelete && (
        <DrawerSection title="Опасная зона">
          {/* Карточка нейтральная, красная только кнопка: красный в системе
              означает просрочку и ошибку, а удаление — не ошибка. */}
          <div className="flex flex-col items-start gap-2 rounded-xl border border-hair bg-tint p-4">
            <Button
              type="button"
              variant="destructive"
              onClick={() => setDeleteOpen(true)}
            >
              {project.is_template ? 'Удалить шаблон' : 'Удалить проект'}
            </Button>
            <p className="m-0 text-sm text-text2">
              {project.is_template
                ? 'Шаблон уйдёт вместе со всеми задачами и вложениями. Проекты, уже созданные по нему, не пострадают.'
                : 'Проект уйдёт вместе со всеми задачами, комментариями и вложениями. Восстановить будет нельзя — если нужно просто убрать с глаз, архивируйте.'}
            </p>
          </div>
        </DrawerSection>
      )}

      {gate.settingsLimitNote && (
        // Отсутствие секций должно читаться как правило, а не как баг.
        <p className="m-0 text-sm text-text2">{gate.settingsLimitNote}</p>
      )}

      {gate.canEditProfile && (
        <ProjectBadgePicker project={project} open={badgeOpen} onOpenChange={setBadgeOpen} />
      )}
      {gate.canSaveAsTemplate && (
        <SaveAsTemplateDialog
          project={project}
          open={saveTemplateOpen}
          onOpenChange={setSaveTemplateOpen}
        />
      )}
      {gate.canDelete && (
        <DeleteProjectDialog
          project={project}
          open={deleteOpen}
          onOpenChange={setDeleteOpen}
        />
      )}
    </div>
  )
}
