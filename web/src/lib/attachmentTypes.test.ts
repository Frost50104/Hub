import { describe, expect, it } from 'vitest'

import {
  ALLOWED_EXTENSIONS,
  ATTACHMENT_ACCEPT,
  ATTACHMENT_MAX_BYTES,
  ATTACHMENT_VIDEO_MAX_BYTES,
  attachmentSizeError,
  attachmentSizeLimit,
  attachmentTypeError,
  fileExtension,
  formatBytes,
  isVideoFile,
} from './attachmentTypes'

/**
 * Зеркало сервера (`app/services/attachments.py`). Расходиться им нельзя:
 * клиент лишь объясняет отказ до запроса, но если он строже сервера — функция
 * просто не работает, а если мягче — человек ждёт загрузку ради 415.
 */
const file = (name: string, size = 1) => ({ name, size })

describe('типы', () => {
  it('видео принимается в трёх контейнерах', () => {
    // Решение владельца 15.09: mp4 (Android, запись экрана), mov (iPhone),
    // webm (браузерная запись).
    expect(attachmentTypeError(file('VID_20260915.mp4'))).toBeNull()
    expect(attachmentTypeError(file('IMG_0042.MOV'))).toBeNull()
    expect(attachmentTypeError(file('screen.webm'))).toBeNull()
  })

  it('форматы, которые браузер не проигрывает, по-прежнему отклоняются', () => {
    expect(attachmentTypeError(file('clip.avi'))).toContain('не поддерживается')
    expect(attachmentTypeError(file('clip.mkv'))).toContain('не поддерживается')
  })

  it('SVG остаётся запрещённым', () => {
    // stored-XSS: это XML с поддержкой <script>.
    expect(attachmentTypeError(file('logo.svg'))).toContain('не поддерживается')
    expect(ALLOWED_EXTENSIONS).not.toContain('.svg')
  })

  it('accept и список расширений — одно и то же', () => {
    expect(ATTACHMENT_ACCEPT.split(',')).toEqual([...ALLOWED_EXTENSIONS])
  })

  it('регистр расширения значения не имеет', () => {
    // iOS отдаёт имена заглавными: «IMG_0042.MOV».
    expect(fileExtension('IMG_0042.MOV')).toBe('.mov')
    expect(isVideoFile('IMG_0042.MOV')).toBe(true)
  })
})

describe('размер', () => {
  it('у видео свой потолок, у остальных — прежний', () => {
    expect(attachmentSizeLimit('a.mp4')).toBe(ATTACHMENT_VIDEO_MAX_BYTES)
    expect(attachmentSizeLimit('a.mov')).toBe(ATTACHMENT_VIDEO_MAX_BYTES)
    expect(attachmentSizeLimit('a.webm')).toBe(ATTACHMENT_VIDEO_MAX_BYTES)
    expect(attachmentSizeLimit('a.pdf')).toBe(ATTACHMENT_MAX_BYTES)
    expect(attachmentSizeLimit('a.png')).toBe(ATTACHMENT_MAX_BYTES)
  })

  it('вид определяется по РАСШИРЕНИЮ, а не по MIME от браузера', () => {
    // Браузер часто не знает тип видео и отдаёт пустую строку или
    // octet-stream — ровно поэтому на сервере есть `_EXT_FALLBACK_MIME`.
    // Опора на `file.type` применила бы к видео лимит документа и не пустила
    // бы до сервера файл, который сервер как раз принимает.
    expect(attachmentSizeError({ name: 'clip.mp4', size: 300 * 1024 * 1024 })).toBeNull()
  })

  it('видео сверх гигабайта отклоняется ДО запроса', () => {
    const problem = attachmentSizeError({
      name: 'long.mp4',
      size: ATTACHMENT_VIDEO_MAX_BYTES + 1,
    })
    expect(problem).toContain('1.0 ГБ')
  })

  it('документ сверх 20 МБ отклоняется и лимит видео на него не распространяется', () => {
    const problem = attachmentSizeError({ name: 'big.pdf', size: 21 * 1024 * 1024 })
    expect(problem).toContain('20.0 МБ')
  })

  it('ровно по границе — проходит', () => {
    expect(
      attachmentSizeError({ name: 'edge.mp4', size: ATTACHMENT_VIDEO_MAX_BYTES }),
    ).toBeNull()
    expect(attachmentSizeError({ name: 'edge.pdf', size: ATTACHMENT_MAX_BYTES })).toBeNull()
  })
})

describe('formatBytes', () => {
  it('гигабайты появились вместе с видео', () => {
    // «1024.0 МБ» в тексте отказа читается как ошибка вёрстки, а не как лимит.
    expect(formatBytes(ATTACHMENT_VIDEO_MAX_BYTES)).toBe('1.0 ГБ')
    expect(formatBytes(20 * 1024 * 1024)).toBe('20.0 МБ')
    expect(formatBytes(512)).toBe('512 Б')
    expect(formatBytes(2048)).toBe('2 КБ')
  })
})
