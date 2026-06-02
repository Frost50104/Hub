import axios from 'axios'

/**
 * Anonymous axios client for the `/api/public/*` surface.
 *
 * Crucially does NOT call `attachAxiosAuth` — public links must work in
 * incognito tabs where no SSO cookie / refresh-token exists. The endpoint
 * intentionally returns 404 on revoked/expired/missing tokens; the UI shows
 * a generic "ссылка недействительна".
 */
export const publicApi = axios.create({
  baseURL: '/api',
  headers: {
    'X-Auth-Mode': 'public',
  },
})

export interface PublicTaskAttachmentMeta {
  filename: string
  size_bytes: number
  mime: string
}

export interface PublicComment {
  author_initials: string | null
  body: string
  created_at: string
}

export interface PublicTaskView {
  kind: 'task'
  title: string
  description: string | null
  status: string
  priority: string
  start_at: string | null
  due_at: string | null
  assignee_initials: string | null
  created_by_initials: string | null
  created_at: string
  comments: PublicComment[]
  attachments: PublicTaskAttachmentMeta[]
}

export interface PublicTaskHit {
  id: string
  title: string
  status: string
  priority: string
  due_at: string | null
  assignee_initials: string | null
  has_attachments: boolean
}

export interface PublicSection {
  id: string
  name: string
  tasks: PublicTaskHit[]
}

export interface PublicProjectComment {
  task_title: string
  author_initials: string | null
  body: string
  created_at: string
}

export interface PublicProjectView {
  kind: 'project'
  name: string
  description: string | null
  sections: PublicSection[]
  recent_comments: PublicProjectComment[]
}

export type PublicView = PublicTaskView | PublicProjectView

export const publicShareApi = {
  resolve: (token: string): Promise<PublicView> =>
    publicApi.get<PublicView>(`/public/${token}`).then((r) => r.data),
}
