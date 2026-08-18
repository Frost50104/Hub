import { api } from './api'

export interface ProjectFolder {
  id: string
  name: string
  position: number
  created_at: string
}

/** Не голый список: при нуле папок флаг прав негде взять, и кнопка «Новая
 *  папка» не показалась бы никогда. Права считает только сервер. */
export interface ProjectFolderList {
  folders: ProjectFolder[]
  can_manage: boolean
}

export const foldersApi = {
  list: (): Promise<ProjectFolderList> =>
    api.get<ProjectFolderList>('/project-folders').then((r) => r.data),
  create: (name: string): Promise<ProjectFolder> =>
    api.post<ProjectFolder>('/project-folders', { name }).then((r) => r.data),
  rename: (id: string, name: string): Promise<ProjectFolder> =>
    api.patch<ProjectFolder>(`/project-folders/${id}`, { name }).then((r) => r.data),
  reorder: (folderIds: string[]): Promise<ProjectFolder[]> =>
    api
      .put<ProjectFolder[]>('/project-folders/reorder', { folder_ids: folderIds })
      .then((r) => r.data),
  remove: (id: string): Promise<void> =>
    api.delete(`/project-folders/${id}`).then(() => undefined),
}
