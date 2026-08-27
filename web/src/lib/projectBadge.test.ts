import { describe, expect, it } from 'vitest'

import {
  BADGE_MAX_BYTES,
  PROJECT_EMOJI,
  normalizeProjectEmoji,
  projectBadgeFileError,
  resolveProjectBadge,
} from './projectBadge'

const base = { key: 'plp', is_favorite: false }

describe('resolveProjectBadge', () => {
  it('картинка бьёт эмодзи', () => {
    const badge = resolveProjectBadge({ ...base, badge_emoji: '🚀', badge_url: '/u' })
    expect(badge).toEqual({ kind: 'image', url: '/u' })
  })

  it('эмодзи бьёт буквы', () => {
    expect(resolveProjectBadge({ ...base, badge_emoji: '🚀' })).toEqual({
      kind: 'emoji',
      emoji: '🚀',
    })
  })

  it('пробелы вместо эмодзи — это не эмодзи', () => {
    expect(resolveProjectBadge({ ...base, badge_emoji: '  ' }).kind).toBe('letters')
  })

  it('старый бэкенд без полей отдаёт буквы, а не падает', () => {
    expect(resolveProjectBadge(base)).toEqual({ kind: 'letters', letters: 'PL' })
  })

  it('буквы всегда в верхнем регистре и не длиннее двух', () => {
    expect(resolveProjectBadge({ key: 'q', is_favorite: false })).toEqual({
      kind: 'letters',
      letters: 'Q',
    })
  })
})

describe('PROJECT_EMOJI', () => {
  it('длина кратна восьми — сетка grid-cols-8 без рваного хвоста', () => {
    expect(PROJECT_EMOJI.length % 8).toBe(0)
  })

  it('без дублей', () => {
    expect(new Set(PROJECT_EMOJI).size).toBe(PROJECT_EMOJI.length)
  })

  it('каждый проходит собственную валидацию без изменений', () => {
    for (const emoji of PROJECT_EMOJI) expect(normalizeProjectEmoji(emoji)).toBe(emoji)
  })
})

describe('normalizeProjectEmoji', () => {
  it('ZWJ-семья не рассыпается', () => {
    expect(normalizeProjectEmoji('👨‍👩‍👧‍👦')).toBe('👨‍👩‍👧‍👦')
  })

  it('радужный флаг остаётся целым', () => {
    expect(normalizeProjectEmoji('🏳️‍🌈')).toBe('🏳️‍🌈')
  })

  it('VS16 сохраняется', () => {
    expect(normalizeProjectEmoji('❤️')).toBe('❤️')
  })

  it('флаг из regional indicators', () => {
    expect(normalizeProjectEmoji('🇷🇺')).toBe('🇷🇺')
  })

  it('берёт первый кластер и отбрасывает хвост', () => {
    expect(normalizeProjectEmoji('👍 ок')).toBe('👍')
  })

  it.each(['ab', '', '   ', '5'])('%o — не эмодзи', (raw) => {
    expect(normalizeProjectEmoji(raw)).toBeNull()
  })
})

describe('projectBadgeFileError', () => {
  it('gif отвергается с внятным текстом', () => {
    expect(projectBadgeFileError({ type: 'image/gif', size: 100 })).toContain('PNG')
  })

  it('перевес назван в килобайтах', () => {
    const msg = projectBadgeFileError({ type: 'image/png', size: BADGE_MAX_BYTES + 1 })
    expect(msg).toContain('512')
  })

  it('нормальный png проходит', () => {
    expect(projectBadgeFileError({ type: 'image/png', size: 30_000 })).toBeNull()
  })
})
