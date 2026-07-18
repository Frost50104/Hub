import { mergeAttributes, Node } from '@tiptap/core'

/**
 * TipTap-ноды урока (Ф3a): figure / gallery / video / pdfEmbed / surveyEmbed /
 * checkQuestion. ТОЛЬКО для редактора (lazy-chunk LessonEditor) — прохождение
 * рендерит их LessonRenderer'ом без ProseMirror.
 *
 * attrs.src — подписанный URL из upload-ответа: живёт в JSONB как «протухший
 * кэш» для превью в редакторе; consumer-API всегда переподписывает src.
 * Правильный ответ checkQuestion (attrs.correct) хранится в черновике и
 * вырезается сервером при отдаче потребителю.
 */

export interface GalleryItemAttrs {
  mediaId: string
  src?: string
  caption?: string
}

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    lessonNodes: {
      insertFigure: (attrs: { mediaId: string; src: string; caption?: string }) => ReturnType
      insertGallery: (items: GalleryItemAttrs[]) => ReturnType
      insertVideo: (attrs: {
        mediaId: string
        src: string
        requireFullWatch?: boolean
        disableSeek?: boolean
      }) => ReturnType
      insertPdfEmbed: (attrs: { mediaId: string; src: string }) => ReturnType
      insertSurveyEmbed: (surveyId: string) => ReturnType
      insertCheckQuestion: (attrs: {
        blockId: string
        question: string
        options: string[]
        correct: number
        gateNext?: boolean
      }) => ReturnType
    }
  }
}

export const LessonFigure = Node.create({
  name: 'figure',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      mediaId: { default: null },
      src: { default: null },
      caption: { default: '' },
      lightbox: { default: false },
    }
  },

  parseHTML() {
    return [{ tag: 'figure[data-lesson-figure]' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    return [
      'figure',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-figure': '',
        class: 'my-2 rounded-lg border border-glass-border p-1',
      }),
      [
        'img',
        {
          src: String(node.attrs.src ?? ''),
          alt: String(node.attrs.caption ?? ''),
          class: 'max-h-64 rounded',
        },
      ],
      [
        'figcaption',
        { class: 'px-1 pt-1 text-xs text-text3' },
        String(node.attrs.caption || 'Изображение'),
      ],
    ]
  },

  addCommands() {
    return {
      insertFigure:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },
})

export const LessonGallery = Node.create({
  name: 'gallery',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      items: { default: [] },
      mode: { default: 'steps' },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-lesson-gallery]' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    const items = (node.attrs.items ?? []) as GalleryItemAttrs[]
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-gallery': '',
        class: 'my-2 flex gap-2 overflow-x-auto rounded-lg border border-glass-border p-2',
      }),
      ...items.map(
        (item, i) =>
          [
            'img',
            {
              src: item.src ?? '',
              alt: item.caption ?? `Шаг ${i + 1}`,
              class: 'h-24 w-32 shrink-0 rounded object-cover',
            },
          ] as const,
      ),
    ]
  },

  addCommands() {
    return {
      insertGallery:
        (items) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { items, mode: 'steps' } }),
    }
  },
})

export const LessonVideo = Node.create({
  name: 'video',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      mediaId: { default: null },
      src: { default: null },
      requireFullWatch: { default: false },
      disableSeek: { default: false },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-lesson-video]' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    const badges: string[] = []
    if (node.attrs.requireFullWatch) badges.push('обязательный досмотр')
    if (node.attrs.disableSeek) badges.push('без перемотки')
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-video': '',
        class: 'my-2 rounded-lg border border-glass-border p-1',
      }),
      [
        'video',
        {
          src: String(node.attrs.src ?? ''),
          controls: 'true',
          playsinline: 'true',
          preload: 'metadata',
          class: 'w-full rounded bg-black',
        },
      ],
      [
        'p',
        { class: 'px-1 pt-1 text-xs text-text3' },
        badges.length ? `Видео · ${badges.join(' · ')}` : 'Видео',
      ],
    ]
  },

  addCommands() {
    return {
      insertVideo:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },
})

export const LessonPdfEmbed = Node.create({
  name: 'pdfEmbed',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      mediaId: { default: null },
      src: { default: null },
      forbidDownload: { default: false },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-lesson-pdf]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-pdf': '',
        class:
          'my-2 rounded-lg border border-glass-border bg-surface px-3 py-2 text-sm text-text2',
      }),
      '📄 Вложенный PDF-документ',
    ]
  },

  addCommands() {
    return {
      insertPdfEmbed:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },
})

export const LessonSurveyEmbed = Node.create({
  name: 'surveyEmbed',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return { surveyId: { default: null } }
  },

  parseHTML() {
    return [{ tag: 'div[data-lesson-survey]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-survey': '',
        class:
          'my-2 rounded-lg border border-amber/40 bg-amber/5 px-3 py-2 text-sm text-text2',
      }),
      '📋 Встроенный опрос',
    ]
  },

  addCommands() {
    return {
      insertSurveyEmbed:
        (surveyId) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs: { surveyId } }),
    }
  },
})

export const LessonCheckQuestion = Node.create({
  name: 'checkQuestion',
  group: 'block',
  atom: true,
  draggable: true,

  addAttributes() {
    return {
      blockId: { default: null },
      question: { default: '' },
      options: { default: [] },
      correct: { default: 0 },
      gateNext: { default: false },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-lesson-check]' }]
  },

  renderHTML({ node, HTMLAttributes }) {
    const options = (node.attrs.options ?? []) as string[]
    return [
      'div',
      mergeAttributes(HTMLAttributes, {
        'data-lesson-check': '',
        class: 'my-2 rounded-lg border border-amber/40 bg-glass px-3 py-2',
      }),
      ['p', { class: 'text-xs font-semibold uppercase text-text3' }, '❓ Проверьте себя'],
      ['p', { class: 'text-sm text-text' }, String(node.attrs.question || '(без вопроса)')],
      [
        'p',
        { class: 'text-xs text-text3' },
        `${options.length} вариантов · верный: №${Number(node.attrs.correct) + 1}` +
          (node.attrs.gateNext ? ' · гейт завершения' : ''),
      ],
    ]
  },

  addCommands() {
    return {
      insertCheckQuestion:
        (attrs) =>
        ({ commands }) =>
          commands.insertContent({ type: this.name, attrs }),
    }
  },
})

export const LESSON_NODE_EXTENSIONS = [
  LessonFigure,
  LessonGallery,
  LessonVideo,
  LessonPdfEmbed,
  LessonSurveyEmbed,
  LessonCheckQuestion,
]
