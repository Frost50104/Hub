import { api } from './api'

export type CustomFieldType =
  | 'text'
  | 'number'
  | 'date'
  | 'select'
  | 'multi_select'
  | 'person'
  | 'checkbox'

export interface CustomFieldOption {
  id: string
  label: string
  color?: string | null
}

export interface CustomFieldDefinition {
  id: string
  project_id: string
  name: string
  type: CustomFieldType
  options: CustomFieldOption[]
  position: string | number
  created_at: string
}

export interface CustomFieldDefinitionCreate {
  name: string
  type: CustomFieldType
  options?: CustomFieldOption[]
}

export interface CustomFieldDefinitionUpdate {
  name?: string
  options?: CustomFieldOption[]
  position?: string | number
}

export interface CustomFieldValue {
  task_id: string
  field_id: string
  /** Shape depends on the definition's type — see `app/services/custom_field_validator.py`. */
  value: unknown
  updated_at: string
}

export const CUSTOM_FIELD_TYPE_LABEL: Record<CustomFieldType, string> = {
  text: 'Текст',
  number: 'Число',
  date: 'Дата',
  select: 'Выбор',
  multi_select: 'Мультивыбор',
  person: 'Человек',
  checkbox: 'Чекбокс',
}

export const customFieldsApi = {
  list: (projectId: string): Promise<CustomFieldDefinition[]> =>
    api
      .get<CustomFieldDefinition[]>(`/projects/${projectId}/custom-fields`)
      .then((r) => r.data),
  create: (
    projectId: string,
    body: CustomFieldDefinitionCreate,
  ): Promise<CustomFieldDefinition> =>
    api
      .post<CustomFieldDefinition>(`/projects/${projectId}/custom-fields`, body)
      .then((r) => r.data),
  update: (
    projectId: string,
    fieldId: string,
    body: CustomFieldDefinitionUpdate,
  ): Promise<CustomFieldDefinition> =>
    api
      .patch<CustomFieldDefinition>(
        `/projects/${projectId}/custom-fields/${fieldId}`,
        body,
      )
      .then((r) => r.data),
  remove: (projectId: string, fieldId: string): Promise<void> =>
    api
      .delete(`/projects/${projectId}/custom-fields/${fieldId}`)
      .then(() => undefined),

  taskValues: (taskId: string): Promise<CustomFieldValue[]> =>
    api
      .get<CustomFieldValue[]>(`/tasks/${taskId}/custom-fields`)
      .then((r) => r.data),
  setValue: (
    taskId: string,
    fieldId: string,
    value: unknown,
  ): Promise<CustomFieldValue> =>
    api
      .put<CustomFieldValue>(`/tasks/${taskId}/custom-fields/${fieldId}`, {
        value,
      })
      .then((r) => r.data),
  clearValue: (taskId: string, fieldId: string): Promise<void> =>
    api
      .delete(`/tasks/${taskId}/custom-fields/${fieldId}`)
      .then(() => undefined),
}
