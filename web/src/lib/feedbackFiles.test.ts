import { describe, expect, it } from 'vitest'

import {
  addFeedbackFiles,
  FEEDBACK_FILES_MAX,
  FEEDBACK_TOTAL_MAX,
  feedbackFileError,
  feedbackFilesSize,
} from './feedbackFiles'

/** File без реальных байтов: конструктору хватает размера и имени. */
function mkFile(name: string, size = 1024, lastModified = 1): File {
  const file = new File([], name, { lastModified })
  Object.defineProperty(file, 'size', { value: size })
  return file
}

describe('feedbackFileError', () => {
  it('чужой тип не пропускает', () => {
    expect(feedbackFileError(mkFile('virus.exe'))).toMatch(/тип файла/i)
  })

  it('файл тяжелее лимита не пропускает', () => {
    expect(feedbackFileError(mkFile('big.png', 21 * 1024 * 1024))).toMatch(/больше/i)
  })

  it('обычный скриншот проходит', () => {
    expect(feedbackFileError(mkFile('screen.png'))).toBeNull()
  })
})

describe('addFeedbackFiles', () => {
  it('добавляет несколько файлов разом', () => {
    const { files, errors } = addFeedbackFiles([], [mkFile('a.png'), mkFile('b.pdf')])
    expect(files.map((f) => f.name)).toEqual(['a.png', 'b.pdf'])
    expect(errors).toEqual([])
  })

  it('дописывает к уже набранным, а не заменяет их', () => {
    const first = addFeedbackFiles([], [mkFile('a.png')]).files
    expect(addFeedbackFiles(first, [mkFile('b.png')]).files).toHaveLength(2)
  })

  it('тот же файл дважды берётся один раз и МОЛЧА', () => {
    // Повтор — не ошибка человека, а промах мышью: тост тут только раздражает.
    const same = mkFile('a.png', 10, 7)
    const { files, errors } = addFeedbackFiles([same], [mkFile('a.png', 10, 7)])
    expect(files).toHaveLength(1)
    expect(errors).toEqual([])
  })

  it('одноимённые, но разные файлы — оба', () => {
    // «screenshot.png» с рабочего стола и из загрузок: отбросить второй значит
    // потерять половину бага.
    const { files } = addFeedbackFiles(
      [mkFile('screenshot.png', 10, 1)],
      [mkFile('screenshot.png', 20, 2)],
    )
    expect(files).toHaveLength(2)
  })

  it('негодный файл объясняет себя и не рушит остальные', () => {
    const { files, errors } = addFeedbackFiles(
      [],
      [mkFile('ok.png'), mkFile('bad.exe'), mkFile('ok2.pdf')],
    )
    expect(files.map((f) => f.name)).toEqual(['ok.png', 'ok2.pdf'])
    expect(errors).toHaveLength(1)
    expect(errors[0]).toContain('bad.exe')
  })

  it('упирается в потолок количества и говорит об этом один раз', () => {
    const many = Array.from({ length: FEEDBACK_FILES_MAX + 3 }, (_, i) =>
      mkFile(`f${i}.png`, 10, i),
    )
    const { files, errors } = addFeedbackFiles([], many)
    expect(files).toHaveLength(FEEDBACK_FILES_MAX)
    expect(errors).toHaveLength(1)
  })

  it('следит за суммарным весом набора, а не только за каждым файлом', () => {
    // По отдельности каждый проходит (10 МБ < 20), втроём — 30 МБ при потолке
    // в 24: третий не берём и говорим, почему именно он.
    //
    // Потолок набора — 24 МБ, а не 50, с 15.09: прежнее число было БОЛЬШЕ, чем
    // принимает nginx (`client_max_body_size 25M`), и набор на 30 МБ проходил
    // все четыре проверки формы, чтобы получить голый 413 без текста.
    const mb10 = 10 * 1024 * 1024
    const { files, errors } = addFeedbackFiles(
      [],
      [mkFile('a.png', mb10, 1), mkFile('b.png', mb10, 2), mkFile('c.png', mb10, 3)],
    )
    expect(files.map((f) => f.name)).toEqual(['a.png', 'b.png'])
    expect(errors).toHaveLength(1)
    expect(errors[0]).toContain('c.png')
    expect(feedbackFilesSize(files)).toBeLessThanOrEqual(FEEDBACK_TOTAL_MAX)
  })

  it('исходный массив не меняется', () => {
    // Состояние React нельзя править на месте — иначе список не перерисуется.
    const current = [mkFile('a.png')]
    addFeedbackFiles(current, [mkFile('b.png')])
    expect(current).toHaveLength(1)
  })
})

describe('feedbackFilesSize', () => {
  it('складывает размеры', () => {
    expect(feedbackFilesSize([mkFile('a', 100, 1), mkFile('b', 250, 2)])).toBe(350)
  })

  it('пустой набор — ноль', () => {
    expect(feedbackFilesSize([])).toBe(0)
  })
})
