import { api } from './api'

export type ProjectRole = 'owner' | 'editor' | 'viewer'

export const PROJECT_ROLE_LABEL: Record<ProjectRole, string> = {
  owner: 'Владелец',
  editor: 'Редактор',
  viewer: 'Наблюдатель',
}

export interface Project {
  id: string
  key: string
  name: string
  description: string | null
  /** Бейдж: эмодзи ЛИБО подписанный адрес картинки. Оба пусты — две буквы
   *  ключа. Опциональны намеренно: в окне деплоя старый бэкенд их не шлёт. */
  badge_emoji?: string | null
  badge_url?: string | null
  archived_at: string | null
  /** Общая для тенанта раскладка (не персональная); null — «Без папки». */
  folder_id: string | null
  created_by: string
  created_at: string
  updated_at: string
  /** ФАКТИЧЕСКОЕ членство — только для бейджа роли. У hub:admin вне проекта
   * null, хотя права при этом полные: их смотри в can_edit/can_manage. */
  my_role: ProjectRole | null
  /** Личное избранное текущего пользователя. */
  is_favorite: boolean
  /** Личное пространство сотрудника. Сервер шлёт его давно, а типа не было:
   *  вкладка «О проекте» прячет по нему архивацию и удаление (сервер на них
   *  отвечает 409). Опционально — старые фикстуры поля не знают. */
  is_personal?: boolean
  /** Эффективные права, посчитанные сервером (членство ИЛИ hub:admin-байпас).
   * Свою копию правила на клиенте НЕ заводим — именно она однажды разъехалась
   * с бэкендом и показывала админу чужой проект read-only. */
  can_edit: boolean
  can_manage: boolean
  /** Неархивные задачи верхнего уровня и сколько из них закрыто. Считают только
   *  список проектов и карточка проекта; мутирующие ручки отдают null. */
  task_count?: number | null
  done_count?: number | null
}

export interface ProjectMember {
  id: string
  employee_id: string
  role: ProjectRole
  added_at: string
  email: string | null
  full_name: string | null
}

export interface CreateProjectBody {
  name: string
  /** Optional — backend auto-generates from name if omitted. */
  key?: string
  description?: string
}

export interface UpdateProjectBody {
  name?: string
  description?: string
}

export const projectsApi = {
  list: (includeArchived = false): Promise<Project[]> =>
    api
      .get<Project[]>('/projects', { params: { include_archived: includeArchived } })
      .then((r) => r.data),
  get: (id: string): Promise<Project> =>
    api.get<Project>(`/projects/${id}`).then((r) => r.data),
  create: (body: CreateProjectBody): Promise<Project> =>
    api.post<Project>('/projects', body).then((r) => r.data),
  update: (id: string, body: UpdateProjectBody): Promise<Project> =>
    api.patch<Project>(`/projects/${id}`, body).then((r) => r.data),
  archive: (id: string): Promise<Project> =>
    api.post<Project>(`/projects/${id}/archive`).then((r) => r.data),
  unarchive: (id: string): Promise<Project> =>
    api.post<Project>(`/projects/${id}/unarchive`).then((r) => r.data),
  // Однополевая мутация со своим глаголом — зеркало setFavorite. В PATCH её
  // не выразить: там идиома «if x is not None», а null обязан значить
  // «вынуть из папки».
  setFolder: (id: string, folderId: string | null): Promise<Project> =>
    api
      .put<Project>(`/projects/${id}/folder`, { folder_id: folderId })
      .then((r) => r.data),
  setFavorite: (id: string, isFavorite: boolean): Promise<Project> =>
    api
      .put<Project>(`/projects/${id}/favorite`, { is_favorite: isFavorite })
      .then((r) => r.data),
  // Тот же довод, что у setFolder: null означает «сними бейдж», и в PATCH
  // это не выразить.
  setBadge: (id: string, emoji: string | null): Promise<Project> =>
    api.put<Project>(`/projects/${id}/badge`, { emoji }).then((r) => r.data),
  uploadBadge: (id: string, file: File): Promise<Project> => {
    const form = new FormData()
    form.append('file', file)
    return api
      .post<Project>(`/projects/${id}/badge/image`, form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      .then((r) => r.data)
  },
  // Ключ проверяет и сервер: он закрывает не опечатку в поле, а рассинхрон
  // между тем, что человек прочитал в диалоге, и тем, какой id ушёл в запрос.
  remove: (id: string, key: string): Promise<void> =>
    api.delete(`/projects/${id}`, { params: { key } }).then(() => undefined),
}

export const membersApi = {
  list: (projectId: string): Promise<ProjectMember[]> =>
    api.get<ProjectMember[]>(`/projects/${projectId}/members`).then((r) => r.data),
  add: (
    projectId: string,
    body: { employee_id: string; role: ProjectRole },
  ): Promise<ProjectMember> =>
    api.post<ProjectMember>(`/projects/${projectId}/members`, body).then((r) => r.data),
  update: (
    projectId: string,
    memberId: string,
    body: { role: ProjectRole },
  ): Promise<ProjectMember> =>
    api
      .patch<ProjectMember>(`/projects/${projectId}/members/${memberId}`, body)
      .then((r) => r.data),
  remove: (projectId: string, memberId: string): Promise<void> =>
    api.delete(`/projects/${projectId}/members/${memberId}`).then(() => undefined),
}
