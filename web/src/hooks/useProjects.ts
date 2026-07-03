import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query'

import {
  membersApi,
  projectsApi,
  sectionsApi,
  type CreateProjectBody,
  type Project,
  type ProjectMember,
  type ProjectRole,
  type Section,
  type UpdateProjectBody,
} from '@/lib/projects'

export const projectKeys = {
  all: ['projects'] as const,
  list: (includeArchived: boolean) => ['projects', { includeArchived }] as const,
  detail: (id: string) => ['projects', id] as const,
  members: (id: string) => ['projects', id, 'members'] as const,
  sections: (id: string) => ['projects', id, 'sections'] as const,
}

export function useProjects(includeArchived = false): UseQueryResult<Project[]> {
  return useQuery({
    queryKey: projectKeys.list(includeArchived),
    queryFn: () => projectsApi.list(includeArchived),
  })
}

export function useProject(id: string | undefined): UseQueryResult<Project> {
  return useQuery({
    queryKey: id ? projectKeys.detail(id) : ['projects', 'none'],
    queryFn: () => projectsApi.get(id!),
    enabled: !!id,
  })
}

export function useProjectMembers(id: string | undefined): UseQueryResult<ProjectMember[]> {
  return useQuery({
    queryKey: id ? projectKeys.members(id) : ['projects', 'none', 'members'],
    queryFn: () => membersApi.list(id!),
    enabled: !!id,
  })
}

export function useProjectSections(id: string | undefined): UseQueryResult<Section[]> {
  return useQuery({
    queryKey: id ? projectKeys.sections(id) : ['projects', 'none', 'sections'],
    queryFn: () => sectionsApi.list(id!),
    enabled: !!id,
  })
}

export function useCreateProject() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: CreateProjectBody) => projectsApi.create(body),
    meta: { errorMessage: 'Не удалось создать проект' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  })
}

export function useUpdateProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: UpdateProjectBody) => projectsApi.update(id, body),
    meta: { errorMessage: 'Не удалось обновить проект' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(id) })
      qc.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}

export function useArchiveProject(id: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (archive: boolean) =>
      archive ? projectsApi.archive(id) : projectsApi.unarchive(id),
    meta: { errorMessage: 'Не удалось обновить проект' },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: projectKeys.detail(id) })
      qc.invalidateQueries({ queryKey: projectKeys.all })
    },
  })
}

export function useSetFavorite(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (isFavorite: boolean) => projectsApi.setFavorite(projectId, isFavorite),
    meta: { errorMessage: 'Не удалось обновить избранное' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.all }),
  })
}

export function useAddMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { employee_id: string; role: ProjectRole }) =>
      membersApi.add(projectId, body),
    meta: { errorMessage: 'Не удалось добавить участника' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  })
}

export function useUpdateMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: ProjectRole }) =>
      membersApi.update(projectId, memberId, { role }),
    meta: { errorMessage: 'Не удалось изменить роль' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  })
}

export function useRemoveMember(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (memberId: string) => membersApi.remove(projectId, memberId),
    meta: { errorMessage: 'Не удалось удалить участника' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.members(projectId) }),
  })
}

export function useCreateSection(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { name: string; position?: number }) =>
      sectionsApi.create(projectId, body),
    meta: { errorMessage: 'Не удалось создать секцию' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.sections(projectId) }),
  })
}

export function useUpdateSection(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: ({
      sectionId,
      ...body
    }: {
      sectionId: string
      name?: string
      position?: number
    }) => sectionsApi.update(sectionId, body),
    meta: { errorMessage: 'Не удалось обновить секцию' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.sections(projectId) }),
  })
}

export function useDeleteSection(projectId: string) {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (sectionId: string) => sectionsApi.remove(sectionId),
    meta: { errorMessage: 'Не удалось удалить секцию' },
    onSuccess: () => qc.invalidateQueries({ queryKey: projectKeys.sections(projectId) }),
  })
}
