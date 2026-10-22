import { describe, expect, it } from 'vitest'

import { VOICE_STOP_MARGIN_SEC, voiceAutoStopMs, voiceErrorText } from './voiceInput'

describe('voiceAutoStopMs', () => {
  it('останавливает запись с запасом до серверного предела', () => {
    expect(voiceAutoStopMs(60)).toBe((60 - VOICE_STOP_MARGIN_SEC) * 1000)
  })

  it('без предела (старый сервер, провайдер openai) — не останавливает', () => {
    expect(voiceAutoStopMs(null)).toBeNull()
    expect(voiceAutoStopMs(undefined)).toBeNull()
    expect(voiceAutoStopMs(0)).toBeNull()
    expect(voiceAutoStopMs(Number.NaN)).toBeNull()
  })

  it('крошечный предел не даёт нуля и отрицательного таймера', () => {
    expect(voiceAutoStopMs(3)).toBe(1000)
  })
})

describe('voiceErrorText', () => {
  it('показывает причину, которую сформулировал сервер', () => {
    const err = { response: { status: 413, data: { detail: 'Запись длиннее 60 с — скажите короче' } } }
    expect(voiceErrorText(err)).toBe('Запись длиннее 60 с — скажите короче')
  })

  it('503 «запускается» — тоже текст сервера, а не «не подключено»', () => {
    const detail = 'Распознавание речи запускается — попробуйте через минуту или наберите текстом'
    expect(voiceErrorText({ response: { status: 503, data: { detail } } })).toBe(detail)
  })

  it('обрыв сети и пустой ответ — общий русский текст', () => {
    const fallback = 'Не удалось распознать запись — наберите команду текстом'
    expect(voiceErrorText(new Error('Network Error'))).toBe(fallback)
    expect(voiceErrorText({ response: { status: 502, data: {} } })).toBe(fallback)
    expect(voiceErrorText({ response: { status: 422, data: { detail: [{ msg: 'x' }] } } })).toBe(
      fallback,
    )
    expect(voiceErrorText(null)).toBe(fallback)
  })
})
