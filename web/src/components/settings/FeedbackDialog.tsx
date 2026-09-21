import { Paperclip, X } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'

import { AutoGrowTextarea } from '@/components/ui/AutoGrowTextarea'
import { Button } from '@/components/ui/Button'
import { TEXTAREA_CLASS } from '@/components/ui/Input'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'
import { formatBytes } from '@/lib/attachments'
import { cn } from '@/lib/cn'
import { extractErrorDetail } from '@/lib/errors'
import {
  addFeedbackFiles,
  FEEDBACK_ACCEPT,
  FEEDBACK_FILES_MAX,
  FEEDBACK_TEXT_MAX,
  feedbackApi,
  feedbackFilesSize,
} from '@/lib/feedback'
import { plural } from '@/lib/typography'

/**
 * «Обратная связь» из настроек: текст и сколько угодно файлов (до десяти).
 *
 * Формы «выберите проект» здесь нет и не будет: сообщение уходит в проект
 * развития продукта, а куда именно — решает сервер. Человеку показываем ровно
 * то, что от него нужно, и благодарим после отправки. С 02.09 сервер
 * подписывает автора на созданную задачу и даёт viewer-членство в проекте
 * обратной связи — уведомления об ответах приходят пушем и открываются.
 */
export function FeedbackDialog({
  open,
  onOpenChange,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
}) {
  const [text, setText] = useState('')
  const [files, setFiles] = useState<File[]>([])
  const [sending, setSending] = useState(false)
  const fileRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    if (open) {
      setText('')
      setFiles([])
    }
  }, [open])

  const pick = (chosen: File[]) => {
    // Тип, размер, вес и количество проверяем ДО запроса: иначе сервер ответит
    // голым 415, а человек так и не узнает, что не так с файлом. Правила
    // считает чистая `addFeedbackFiles` — она же объясняет каждый отказ.
    const { files: next, errors } = addFeedbackFiles(files, chosen)
    setFiles(next)
    for (const error of errors) toast.error(error)
  }

  const submit = async () => {
    const message = text.trim()
    if (!message || sending) return
    setSending(true)
    try {
      await feedbackApi.send(message, files)
      // Строго ПОСЛЕ ответа: «спасибо» до него было бы обещанием, которого
      // сервер мог не выполнить.
      toast.success(
        'Спасибо! Сообщение отправлено — вы подписаны на задачу и получите уведомления об ответах',
      )
      onOpenChange(false)
    } catch (e) {
      // Отправка идёт голым запросом, а не мутацией, и глобальный тост
      // queryClient её не ловит (axios-перехватчиков в приложении нет): до
      // 21.09 сбой оставлял диалог открытым без единого слова. Текст и файлы
      // в форме остаются — можно отправить ещё раз.
      toast.error('Не удалось отправить сообщение', { description: extractErrorDetail(e) })
    } finally {
      setSending(false)
    }
  }

  return (
    <ResponsiveDialog
      open={open}
      // Пока отправляем — не закрываем: исчезнувшая форма выглядит как «ушло».
      onOpenChange={(v) => !sending && onOpenChange(v)}
      title="Обратная связь"
      description="Что не работает, чего не хватает, что раздражает — напишите как есть. Можно приложить скриншоты и файлы."
      desktopWidth={520}
      footer={
        <>
          <Button variant="secondary" onClick={() => onOpenChange(false)} disabled={sending}>
            Отмена
          </Button>
          <Button onClick={() => void submit()} disabled={sending || !text.trim()}>
            {sending ? 'Отправляем…' : 'Отправить'}
          </Button>
        </>
      }
    >
      <div className="flex flex-col gap-3">
        <AutoGrowTextarea
          autoFocus
          value={text}
          maxLength={FEEDBACK_TEXT_MAX}
          onChange={(e) => setText(e.target.value)}
          placeholder="Например: на телефоне не видно кнопку «Готово» в карточке задачи"
          // Вид поля — из системы (`TEXTAREA_CLASS`), своё здесь только рост:
          // выше обычного (сюда пишут абзац, а не строку) и с потолком —
          // 5 000 символов вырастают в поле на ~1 960px и вытолкнули бы
          // «Отправить» за экран.
          className={cn(TEXTAREA_CLASS, 'max-h-[40vh] min-h-[120px] overflow-y-auto')}
        />

        <div className="flex items-center gap-2">
          <Button
            type="button"
            variant="secondary"
            disabled={sending || files.length >= FEEDBACK_FILES_MAX}
            onClick={() => fileRef.current?.click()}
          >
            <Paperclip className="h-4 w-4" strokeWidth={1.9} />
            {files.length ? 'Добавить ещё' : 'Прикрепить файлы'}
          </Button>
          {files.length > 0 && (
            <span className="min-w-0 truncate text-[13px] text-text2">
              {plural(files.length, 'файл', 'файла', 'файлов')} ·{' '}
              {formatBytes(feedbackFilesSize(files))}
            </span>
          )}
          <span
            className={cn(
              'ml-auto shrink-0 font-mono text-[12px]',
              text.length > FEEDBACK_TEXT_MAX - 200 ? 'text-amber' : 'text-text3',
            )}
          >
            {text.length}/{FEEDBACK_TEXT_MAX}
          </span>
        </div>

        {files.length > 0 && (
          // Список, а не строка через запятую: убрать нужно уметь КОНКРЕТНЫЙ
          // файл, а имена длинные и в одну строку не читаются.
          <ul className="flex flex-col gap-1">
            {files.map((f, i) => (
              <li
                key={`${f.name}:${f.size}:${f.lastModified}`}
                className="flex min-w-0 items-center gap-2 rounded-lg border border-glass-border bg-glass px-2.5 py-1.5"
              >
                <Paperclip className="h-3.5 w-3.5 shrink-0 text-text3" strokeWidth={1.9} />
                <span className="min-w-0 flex-1 truncate text-[13px] text-text">{f.name}</span>
                <span className="shrink-0 font-mono text-[12px] text-text3">
                  {formatBytes(f.size)}
                </span>
                <button
                  type="button"
                  aria-label={`Убрать файл ${f.name}`}
                  disabled={sending}
                  onClick={() => setFiles((prev) => prev.filter((_, j) => j !== i))}
                  className="flex h-6 w-6 shrink-0 items-center justify-center rounded-md text-text2 hover:bg-glass hover:text-text"
                >
                  <X className="h-3.5 w-3.5" strokeWidth={2.2} />
                </button>
              </li>
            ))}
          </ul>
        )}

        <input
          ref={fileRef}
          type="file"
          multiple
          accept={FEEDBACK_ACCEPT}
          className="hidden"
          onChange={(e) => {
            const chosen = [...(e.target.files ?? [])]
            if (chosen.length) pick(chosen)
            // Сброс обязателен: без него повторный выбор ТОГО ЖЕ файла (человек
            // убрал его и передумал) не поднимет `change`.
            e.target.value = ''
          }}
        />
      </div>
    </ResponsiveDialog>
  )
}
