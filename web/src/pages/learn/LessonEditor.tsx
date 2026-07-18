import { type Editor } from '@tiptap/core'
import {
  CircleHelp,
  ClipboardList,
  FileText,
  FileUp,
  Film,
  ImagePlus,
  Images,
  LayoutTemplate,
  Save,
  X,
} from 'lucide-react'
import {
  lazy,
  Suspense,
  useRef,
  useState,
  type ChangeEvent,
  type ReactNode,
} from 'react'
import { toast } from 'sonner'

import { LESSON_NODE_EXTENSIONS } from '@/components/learn/rich/lessonNodes'
import { Button } from '@/components/ui/Button'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/Dialog'
import { Input } from '@/components/ui/Input'
import { Label } from '@/components/ui/Label'
import { Select } from '@/components/ui/Select'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { Switch } from '@/components/ui/Switch'
import {
  useCourseMutation,
  useLesson,
  useLessonTemplates,
  useSurveys,
} from '@/hooks/useLearn'
import { extractErrorDetail } from '@/lib/errors'
import {
  learnApi,
  type LessonMeta,
  type LessonUnlockRule,
  type RichDoc,
} from '@/lib/learn'

const RichEditor = lazy(() => import('@/components/learn/rich/RichEditor'))

/**
 * Редактор урока (Ф3a): blocks-режим (TipTap + доменные ноды + загрузка
 * медиа) или PDF-режим (готовый файл). Часть chunk'а CourseBuilderPage.
 */

const UNLOCK_LABEL: Record<LessonUnlockRule, string> = {
  inherit: 'Как в курсе',
  free: 'Всегда открыт',
  after_prev_test: 'После предыдущего',
}

function ToolButton({
  title,
  onClick,
  disabled,
  children,
}: {
  title: string
  onClick: () => void
  disabled?: boolean
  children: ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      disabled={disabled}
      onMouseDown={(e) => {
        e.preventDefault()
        onClick()
      }}
      className="inline-flex items-center gap-1 rounded px-1.5 py-1 text-xs text-text3 transition-colors hover:bg-glass hover:text-text disabled:opacity-50"
    >
      {children}
    </button>
  )
}

export function LessonEditor({
  lessonMeta,
  onClose,
}: {
  lessonMeta: LessonMeta
  onClose: () => void
}) {
  const lesson = useLesson(lessonMeta.id)

  return (
    <div className="space-y-3 rounded-xl border border-amber/40 bg-glass p-4">
      <div className="flex items-center justify-between gap-2">
        <p className="text-sm font-semibold text-text">Редактор урока</p>
        <button
          type="button"
          onClick={onClose}
          className="rounded p-1.5 text-text3 hover:bg-surface hover:text-text"
          aria-label="Закрыть редактор"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
      {lesson.isLoading && <SkeletonRows rows={4} />}
      {lesson.data && <LessonEditorInner key={lesson.data.id} lesson={lesson.data} />}
    </div>
  )
}

function LessonEditorInner({
  lesson,
}: {
  lesson: NonNullable<ReturnType<typeof useLesson>['data']>
}) {
  const [title, setTitle] = useState(lesson.title)
  const [unlockRule, setUnlockRule] = useState<LessonUnlockRule>(lesson.unlock_rule)
  const [format, setFormat] = useState(lesson.content_format)
  const [forbidDownload, setForbidDownload] = useState(lesson.forbid_download)
  const [content, setContent] = useState<RichDoc | null>(lesson.content)
  const [pdfUrl, setPdfUrl] = useState<string | null>(lesson.pdf_url)
  const [pdfMediaId, setPdfMediaId] = useState<string | null>(null)

  const [checkOpen, setCheckOpen] = useState(false)
  const [surveyOpen, setSurveyOpen] = useState(false)
  const [videoUpload, setVideoUpload] = useState<File | null>(null)
  const [templatesOpen, setTemplatesOpen] = useState(false)
  const [saveTemplateOpen, setSaveTemplateOpen] = useState(false)

  const imageInput = useRef<HTMLInputElement | null>(null)
  const galleryInput = useRef<HTMLInputElement | null>(null)
  const videoInput = useRef<HTMLInputElement | null>(null)
  const pdfEmbedInput = useRef<HTMLInputElement | null>(null)
  const pdfLessonInput = useRef<HTMLInputElement | null>(null)
  const [uploading, setUploading] = useState(false)
  const editorRef = useRef<Editor | null>(null)

  const save = useCourseMutation(() =>
    learnApi.updateLesson(lesson.id, {
      title: title.trim(),
      unlock_rule: unlockRule,
      content_format: format,
      forbid_download: forbidDownload,
      ...(format === 'blocks' && content ? { content } : {}),
      ...(pdfMediaId ? { pdf_media_id: pdfMediaId } : {}),
    }),
  )

  const upload = async (file: File) => {
    setUploading(true)
    try {
      return await learnApi.uploadMedia(file)
    } catch (e) {
      toast.error('Не удалось загрузить файл', { description: extractErrorDetail(e) })
      return null
    } finally {
      setUploading(false)
    }
  }

  const onImagePick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const media = await upload(file)
    if (media) {
      editorRef.current
        ?.chain()
        .focus()
        .insertFigure({ mediaId: media.id, src: media.url, caption: '' })
        .run()
    }
  }

  const onGalleryPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = [...(e.target.files ?? [])].slice(0, 20)
    e.target.value = ''
    if (!files.length) return
    const items: { mediaId: string; src: string; caption: string }[] = []
    for (const file of files) {
      const media = await upload(file)
      if (media) items.push({ mediaId: media.id, src: media.url, caption: '' })
    }
    if (items.length) {
      editorRef.current?.chain().focus().insertGallery(items).run()
    }
  }

  const onVideoPick = (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (file) setVideoUpload(file) // опции досмотра — в диалоге
  }

  const onPdfEmbedPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const media = await upload(file)
    if (media) {
      editorRef.current?.chain().focus().insertPdfEmbed({ mediaId: media.id, src: media.url }).run()
    }
  }

  const onLessonPdfPick = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    e.target.value = ''
    if (!file) return
    const media = await upload(file)
    if (media) {
      setPdfMediaId(media.id)
      setPdfUrl(media.url)
      toast.success('PDF загружен — не забудьте сохранить урок')
    }
  }

  const lessonToolbar = (editor: Editor) => {
    editorRef.current = editor
    return (
      <>
        <ToolButton title="Изображение" onClick={() => imageInput.current?.click()} disabled={uploading}>
          <ImagePlus className="h-4 w-4" /> Фото
        </ToolButton>
        <ToolButton title="Галерея (шаги)" onClick={() => galleryInput.current?.click()} disabled={uploading}>
          <Images className="h-4 w-4" /> Галерея
        </ToolButton>
        <ToolButton title="Видео (MP4)" onClick={() => videoInput.current?.click()} disabled={uploading}>
          <Film className="h-4 w-4" /> Видео
        </ToolButton>
        <ToolButton title="Вложенный PDF" onClick={() => pdfEmbedInput.current?.click()} disabled={uploading}>
          <FileText className="h-4 w-4" /> PDF
        </ToolButton>
        <ToolButton title="Контрольный вопрос" onClick={() => setCheckOpen(true)}>
          <CircleHelp className="h-4 w-4" /> Вопрос
        </ToolButton>
        <ToolButton title="Встроить опрос" onClick={() => setSurveyOpen(true)}>
          <ClipboardList className="h-4 w-4" /> Опрос
        </ToolButton>
        {uploading && <span className="px-1 text-xs text-text3">Загрузка…</span>}
      </>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
        <div className="sm:col-span-2">
          <Label htmlFor="lesson-title">Название урока</Label>
          <Input
            id="lesson-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
          />
        </div>
        <div>
          <Label htmlFor="lesson-unlock">Доступ к уроку</Label>
          <Select
            id="lesson-unlock"
            value={unlockRule}
            onChange={(e) => setUnlockRule(e.target.value as LessonUnlockRule)}
          >
            {(Object.keys(UNLOCK_LABEL) as LessonUnlockRule[]).map((rule) => (
              <option key={rule} value={rule}>
                {UNLOCK_LABEL[rule]}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-1 rounded-lg border border-glass-border p-0.5">
          {(['blocks', 'pdf'] as const).map((f) => (
            <button
              key={f}
              type="button"
              onClick={() => setFormat(f)}
              className={`rounded px-2.5 py-1 text-xs font-medium ${
                format === f ? 'bg-surface text-amber' : 'text-text3 hover:text-text'
              }`}
            >
              {f === 'blocks' ? 'Конструктор блоков' : 'Готовый PDF'}
            </button>
          ))}
        </div>
        {format === 'pdf' && (
          <label className="flex items-center gap-2 text-xs text-text2">
            <Switch checked={forbidDownload} onCheckedChange={setForbidDownload} />
            запретить скачивание
          </label>
        )}
      </div>

      {format === 'pdf' ? (
        <div className="space-y-2 rounded-lg border border-glass-border bg-surface p-3">
          {pdfUrl ? (
            <p className="flex items-center gap-2 text-sm text-text2">
              <FileText className="h-4 w-4 text-amber" /> PDF загружен
              <a
                href={pdfUrl}
                target="_blank"
                rel="noopener noreferrer"
                className="text-amber hover:opacity-80"
              >
                посмотреть
              </a>
            </p>
          ) : (
            <p className="text-sm text-text3">Файл ещё не загружен.</p>
          )}
          <Button size="sm" variant="secondary" disabled={uploading} onClick={() => pdfLessonInput.current?.click()}>
            <FileUp className="h-4 w-4" /> {pdfUrl ? 'Заменить PDF' : 'Загрузить PDF'}
          </Button>
        </div>
      ) : (
        <Suspense fallback={<SkeletonRows rows={4} />}>
          <RichEditor
            value={content}
            onChange={setContent}
            placeholder="Содержимое урока…"
            extraExtensions={LESSON_NODE_EXTENSIONS}
            extraToolbar={lessonToolbar}
          />
        </Suspense>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Button
          size="sm"
          disabled={!title.trim() || save.isPending || (format === 'pdf' && !pdfUrl)}
          onClick={() =>
            void save
              .mutateAsync(undefined as never)
              .then(() => toast.success('Урок сохранён'))
          }
        >
          <Save className="h-4 w-4" /> Сохранить урок
        </Button>
        {format === 'blocks' && (
          <>
            <Button size="sm" variant="ghost" onClick={() => setTemplatesOpen(true)}>
              <LayoutTemplate className="h-4 w-4" /> Из шаблона
            </Button>
            <Button
              size="sm"
              variant="ghost"
              disabled={!content}
              onClick={() => setSaveTemplateOpen(true)}
            >
              Сохранить как шаблон
            </Button>
          </>
        )}
      </div>

      {/* Скрытые file-инпуты */}
      <input ref={imageInput} type="file" accept="image/png,image/jpeg,image/webp" hidden onChange={(e) => void onImagePick(e)} />
      <input ref={galleryInput} type="file" accept="image/png,image/jpeg,image/webp" multiple hidden onChange={(e) => void onGalleryPick(e)} />
      <input ref={videoInput} type="file" accept="video/mp4" hidden onChange={onVideoPick} />
      <input ref={pdfEmbedInput} type="file" accept="application/pdf" hidden onChange={(e) => void onPdfEmbedPick(e)} />
      <input ref={pdfLessonInput} type="file" accept="application/pdf" hidden onChange={(e) => void onLessonPdfPick(e)} />

      {checkOpen && (
        <CheckQuestionDialog
          onClose={() => setCheckOpen(false)}
          onInsert={(attrs) => {
            editorRef.current?.chain().focus().insertCheckQuestion(attrs).run()
            setCheckOpen(false)
          }}
        />
      )}
      {surveyOpen && (
        <SurveyPickDialog
          onClose={() => setSurveyOpen(false)}
          onPick={(surveyId) => {
            editorRef.current?.chain().focus().insertSurveyEmbed(surveyId).run()
            setSurveyOpen(false)
          }}
        />
      )}
      {videoUpload && (
        <VideoOptionsDialog
          file={videoUpload}
          onClose={() => setVideoUpload(null)}
          onInsert={async (opts) => {
            const media = await upload(videoUpload)
            if (media) {
              editorRef.current
                ?.chain()
                .focus()
                .insertVideo({ mediaId: media.id, src: media.url, ...opts })
                .run()
            }
            setVideoUpload(null)
          }}
        />
      )}
      {templatesOpen && (
        <TemplatePickDialog
          onClose={() => setTemplatesOpen(false)}
          onPick={(doc) => {
            setContent(doc)
            setTemplatesOpen(false)
            toast.info('Шаблон подставлен — сохраните урок, чтобы применить')
          }}
        />
      )}
      {saveTemplateOpen && content && (
        <SaveTemplateDialog content={content} onClose={() => setSaveTemplateOpen(false)} />
      )}
    </div>
  )
}

// ─── Диалоги ─────────────────────────────────────────────────────────────────

function CheckQuestionDialog({
  onClose,
  onInsert,
}: {
  onClose: () => void
  onInsert: (attrs: {
    blockId: string
    question: string
    options: string[]
    correct: number
    gateNext: boolean
  }) => void
}) {
  const [question, setQuestion] = useState('')
  const [options, setOptions] = useState<string[]>(['', ''])
  const [correct, setCorrect] = useState(0)
  const [gateNext, setGateNext] = useState(true)

  const filled = options.map((o) => o.trim()).filter(Boolean)
  const valid = question.trim().length > 0 && filled.length >= 2 && correct < filled.length

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Контрольный вопрос</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <div>
            <Label htmlFor="cq-question">Вопрос</Label>
            <Input
              id="cq-question"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              placeholder="Как правильно…?"
            />
          </div>
          <Label>Варианты (отметьте правильный)</Label>
          {options.map((option, i) => (
            <div key={i} className="flex items-center gap-2">
              <input
                type="radio"
                name="cq-correct"
                checked={correct === i}
                onChange={() => setCorrect(i)}
                className="accent-amber"
                aria-label={`Правильный — вариант ${i + 1}`}
              />
              <Input
                value={option}
                onChange={(e) =>
                  setOptions((prev) => prev.map((v, j) => (j === i ? e.target.value : v)))
                }
                placeholder={`Вариант ${i + 1}`}
              />
              {options.length > 2 && (
                <button
                  type="button"
                  onClick={() => {
                    setOptions((prev) => prev.filter((_, j) => j !== i))
                    if (correct >= i && correct > 0) setCorrect(correct - 1)
                  }}
                  className="rounded p-1.5 text-text3 hover:text-red"
                  aria-label="Убрать вариант"
                >
                  <X className="h-4 w-4" />
                </button>
              )}
            </div>
          ))}
          {options.length < 10 && (
            <Button size="sm" variant="ghost" onClick={() => setOptions((prev) => [...prev, ''])}>
              + вариант
            </Button>
          )}
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={gateNext} onCheckedChange={setGateNext} />
            без ответа урок нельзя завершить
          </label>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose}>
            Отмена
          </Button>
          <Button
            disabled={!valid}
            onClick={() =>
              onInsert({
                blockId: crypto.randomUUID(),
                question: question.trim(),
                options: filled,
                correct,
                gateNext,
              })
            }
          >
            Вставить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function SurveyPickDialog({
  onClose,
  onPick,
}: {
  onClose: () => void
  onPick: (surveyId: string) => void
}) {
  const surveys = useSurveys(false)
  const published = (surveys.data?.items ?? []).filter((s) => s.status === 'published')
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Встроить опрос</DialogTitle>
        </DialogHeader>
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {published.map((s) => (
            <button
              key={s.id}
              type="button"
              onClick={() => onPick(s.id)}
              className="flex w-full items-center gap-2 rounded-lg border border-glass-border px-3 py-2 text-left text-sm text-text hover:border-amber/50"
            >
              <ClipboardList className="h-4 w-4 shrink-0 text-amber" />
              <span className="min-w-0 flex-1 truncate">{s.title}</span>
            </button>
          ))}
          {surveys.data && published.length === 0 && (
            <p className="py-4 text-center text-sm text-text3">
              Нет опубликованных опросов.
            </p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function VideoOptionsDialog({
  file,
  onClose,
  onInsert,
}: {
  file: File
  onClose: () => void
  onInsert: (opts: { requireFullWatch: boolean; disableSeek: boolean }) => Promise<void>
}) {
  const [requireFullWatch, setRequireFullWatch] = useState(true)
  const [disableSeek, setDisableSeek] = useState(false)
  const [busy, setBusy] = useState(false)
  return (
    <Dialog open onOpenChange={(v) => !v && !busy && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Видео: {file.name}</DialogTitle>
        </DialogHeader>
        <div className="space-y-2">
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={requireFullWatch} onCheckedChange={setRequireFullWatch} />
            обязательный досмотр (≥90% для завершения урока)
          </label>
          <label className="flex items-center gap-2 text-sm text-text2">
            <Switch checked={disableSeek} onCheckedChange={setDisableSeek} />
            запретить перемотку вперёд
          </label>
          <p className="text-xs text-text3">
            Только MP4 (H.264) c «web optimized» / faststart — иначе сервер отклонит файл.
          </p>
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button
            disabled={busy}
            onClick={() => {
              setBusy(true)
              void onInsert({ requireFullWatch, disableSeek }).finally(() => setBusy(false))
            }}
          >
            {busy ? 'Загружаем…' : 'Загрузить и вставить'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

function TemplatePickDialog({
  onClose,
  onPick,
}: {
  onClose: () => void
  onPick: (doc: RichDoc) => void
}) {
  const templates = useLessonTemplates(true)
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Шаблоны уроков</DialogTitle>
        </DialogHeader>
        <div className="max-h-72 space-y-1 overflow-y-auto">
          {(templates.data ?? []).map((t) => (
            <div
              key={t.id}
              className="flex items-center gap-2 rounded-lg border border-glass-border px-3 py-2"
            >
              <button
                type="button"
                onClick={() => onPick(t.content)}
                className="min-w-0 flex-1 truncate text-left text-sm text-text hover:text-amber"
              >
                {t.title}
              </button>
              <button
                type="button"
                aria-label="Удалить шаблон"
                onClick={() => {
                  void learnApi.deleteLessonTemplate(t.id).then(() => templates.refetch())
                }}
                className="rounded p-1 text-text3 hover:text-red"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
          ))}
          {templates.data && templates.data.length === 0 && (
            <p className="py-4 text-center text-sm text-text3">Шаблонов пока нет.</p>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

function SaveTemplateDialog({
  content,
  onClose,
}: {
  content: RichDoc
  onClose: () => void
}) {
  const [title, setTitle] = useState('')
  const [busy, setBusy] = useState(false)
  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Сохранить как шаблон</DialogTitle>
        </DialogHeader>
        <div>
          <Label htmlFor="tpl-title">Название шаблона</Label>
          <Input
            id="tpl-title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            maxLength={255}
          />
        </div>
        <DialogFooter>
          <Button variant="secondary" onClick={onClose} disabled={busy}>
            Отмена
          </Button>
          <Button
            disabled={!title.trim() || busy}
            onClick={() => {
              setBusy(true)
              void learnApi
                .createLessonTemplate({ title: title.trim(), content })
                .then(() => {
                  toast.success('Шаблон сохранён')
                  onClose()
                })
                .catch((e) =>
                  toast.error('Не удалось сохранить шаблон', {
                    description: extractErrorDetail(e),
                  }),
                )
                .finally(() => setBusy(false))
            }}
          >
            Сохранить
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
