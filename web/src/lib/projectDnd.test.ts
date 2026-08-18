import { describe, expect, it } from 'vitest'

import { UNFILED } from './groupProjects'
import {
  folderDropId,
  parseFolderDropId,
  projectDragId,
  resolveFolderMove,
} from './projectDnd'

describe('folderDropId / parseFolderDropId', () => {
  it('round-trip для обычной папки', () => {
    expect(parseFolderDropId(folderDropId('f1'))).toEqual({ folderId: 'f1' })
  })

  it('round-trip для «Без папки» (null ↔ UNFILED)', () => {
    const id = folderDropId(null)
    expect(id).toContain(UNFILED)
    expect(parseFolderDropId(id)).toEqual({ folderId: null })
  })

  it('чужой id не наш — null', () => {
    expect(parseFolderDropId('task-1')).toBeNull()
    expect(parseFolderDropId('fav:abc')).toBeNull()
  })
})

describe('projectDragId', () => {
  it('разводит два вхождения одного проекта', () => {
    expect(projectDragId('fav', 'p1')).not.toBe(projectDragId('group', 'p1'))
  })
})

describe('resolveFolderMove', () => {
  const fromUnfiled = { projectId: 'p1', folderId: null }
  const fromF1 = { projectId: 'p1', folderId: 'f1' }

  it('переносит из «Без папки» в папку', () => {
    expect(resolveFolderMove(fromUnfiled, folderDropId('f1'))).toEqual({
      projectId: 'p1',
      folderId: 'f1',
    })
  })

  it('вынимает из папки в «Без папки»', () => {
    expect(resolveFolderMove(fromF1, folderDropId(null))).toEqual({
      projectId: 'p1',
      folderId: null,
    })
  })

  it('дроп в ту же папку — null (запроса не нужно)', () => {
    expect(resolveFolderMove(fromF1, folderDropId('f1'))).toBeNull()
    expect(resolveFolderMove(fromUnfiled, folderDropId(null))).toBeNull()
  })

  it('дроп мимо зоны — null', () => {
    expect(resolveFolderMove(fromF1, 'task-9')).toBeNull()
    expect(resolveFolderMove(fromF1, undefined)).toBeNull()
  })

  it('без данных драга — null', () => {
    expect(resolveFolderMove(undefined, folderDropId('f1'))).toBeNull()
  })
})
