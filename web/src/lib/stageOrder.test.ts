import { describe, expect, it } from 'vitest'

import { renameStage, reorderStages } from './stageOrder'
import { type TaskStage } from './stages'

const stage = (id: string, position: number): TaskStage => ({
  id,
  project_id: 'p',
  name: id.toUpperCase(),
  position,
  created_at: '2026-08-26T10:00:00Z',
})

const stages = [stage('a', 0), stage('b', 1), stage('c', 2)]

describe('reorderStages', () => {
  it('в начало', () => {
    const move = reorderStages(stages, 'c', 'a')
    expect(move?.position).toBe(0)
    expect(move?.next.map((s) => s.id)).toEqual(['c', 'a', 'b'])
  })

  it('в конец', () => {
    const move = reorderStages(stages, 'a', 'c')
    expect(move?.position).toBe(2)
    expect(move?.next.map((s) => s.id)).toEqual(['b', 'c', 'a'])
  })

  it('между соседями', () => {
    const move = reorderStages(stages, 'a', 'b')
    expect(move?.next.map((s) => s.id)).toEqual(['b', 'a', 'c'])
  })

  it('позиции перенумерованы подряд — как их держит сервер', () => {
    const move = reorderStages(stages, 'c', 'a')
    expect(move?.next.map((s) => s.position)).toEqual([0, 1, 2])
  })

  it('бросок на себя запроса не порождает', () => {
    expect(reorderStages(stages, 'b', 'b')).toBeNull()
  })

  it('чужой id — не двигаем ничего (бросили на карточку, а не на колонку)', () => {
    expect(reorderStages(stages, 'a', 'task-42')).toBeNull()
    expect(reorderStages(stages, 'нет такой', 'b')).toBeNull()
  })

  it('исходный массив не мутируется', () => {
    reorderStages(stages, 'c', 'a')
    expect(stages.map((s) => s.id)).toEqual(['a', 'b', 'c'])
  })
})

describe('renameStage', () => {
  it('меняет имя одной колонки', () => {
    expect(renameStage(stages, 'b', 'Согласование').map((s) => s.name)).toEqual([
      'A',
      'Согласование',
      'C',
    ])
  })

  it('незнакомый id ничего не ломает', () => {
    expect(renameStage(stages, 'нет', 'X')).toHaveLength(3)
  })
})
