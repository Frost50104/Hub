import { type AnyExtension } from '@tiptap/core'
import { Color } from '@tiptap/extension-color'
import { Highlight } from '@tiptap/extension-highlight'
import { Link } from '@tiptap/extension-link'
import { Placeholder } from '@tiptap/extension-placeholder'
import { Table } from '@tiptap/extension-table'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import { TableRow } from '@tiptap/extension-table-row'
import { FontSize, TextStyle } from '@tiptap/extension-text-style'
import { Underline } from '@tiptap/extension-underline'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import {
  Bold,
  Eraser,
  Highlighter,
  Italic,
  Link2,
  List,
  ListOrdered,
  Minus,
  Quote,
  Strikethrough,
  Table as TableIcon,
  Underline as UnderlineIcon,
} from 'lucide-react'
import { useEffect, useState } from 'react'

import { cn } from '@/lib/cn'

import { Callout, CALLOUT_META, type CalloutKind } from './callout'
import { type RichDoc } from './RichRenderer'
import { sanitizeRichDoc } from './sanitizeRichDoc'

/**
 * TipTap-редактор (Ф2). Живёт в ОТДЕЛЬНОМ lazy-chunk'е — грузится только
 * когда author/publisher открывает форму контента; линейный персонал и
 * прохождение контента (RichRenderer) ProseMirror не тянут.
 *
 * Значение — {schema: 1, doc} (сервер валидирует whitelist нод).
 */

const TEXT_COLORS = ['#FFB200', '#e05252', '#3fae6a', '#5b8def', '#a06bd8']

// Размеры «как в Ворде» (ОС 12.08); сервер допускает 10..48px.
const FONT_SIZES = ['12', '14', '16', '18', '20', '24', '28', '32']

const HEADING_LEVELS = [1, 2, 3, 4] as const

const toolbarSelectClass =
  'h-7 rounded border border-glass-border bg-glass px-1 text-xs text-text2 focus:outline-none focus:ring-1 focus:ring-amber/60'

function ToolbarButton({
  active,
  onClick,
  title,
  children,
}: {
  active?: boolean
  onClick: () => void
  title: string
  children: React.ReactNode
}) {
  return (
    <button
      type="button"
      title={title}
      onMouseDown={(e) => {
        e.preventDefault()
        onClick()
      }}
      className={cn(
        'rounded p-1.5 text-text3 transition-colors hover:bg-glass hover:text-text',
        active && 'bg-surface text-amber',
      )}
    >
      {children}
    </button>
  )
}

/** Таблицы (ОС 12.08): вставка с выбором размера + управление строками/
 * столбцами по месту. Контролы видны только при курсоре внутри таблицы —
 * тулбар в обычном состоянии не распухает. */
function TableControls({ editor }: { editor: Editor }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState(3)
  const [cols, setCols] = useState(3)
  const [withHeader, setWithHeader] = useState(true)

  const inTable = editor.isActive('table')

  const insert = () => {
    editor
      .chain()
      .focus()
      .insertTable({
        rows: Math.min(Math.max(rows, 1), 20),
        cols: Math.min(Math.max(cols, 1), 10),
        withHeaderRow: withHeader,
      })
      .run()
    setOpen(false)
  }

  const cellBtn = (title: string, label: string, run: () => boolean, enabled: boolean) => (
    <button
      type="button"
      title={title}
      disabled={!enabled}
      onMouseDown={(e) => {
        e.preventDefault()
        run()
      }}
      className="rounded px-1.5 py-1 text-[11px] text-text3 transition-colors hover:bg-glass hover:text-text disabled:opacity-40"
    >
      {label}
    </button>
  )

  if (inTable) {
    const can = editor.can()
    return (
      <span className="flex shrink-0 items-center gap-0.5 rounded bg-surface/60 px-0.5">
        <TableIcon className="mx-1 h-4 w-4 text-amber" />
        {cellBtn('Строка ниже', '+стр', () => editor.chain().focus().addRowAfter().run(), can.addRowAfter())}
        {cellBtn('Удалить строку', '−стр', () => editor.chain().focus().deleteRow().run(), can.deleteRow())}
        {cellBtn('Колонка справа', '+кол', () => editor.chain().focus().addColumnAfter().run(), can.addColumnAfter())}
        {cellBtn('Удалить колонку', '−кол', () => editor.chain().focus().deleteColumn().run(), can.deleteColumn())}
        {cellBtn('Строка заголовков вкл/выкл', 'шапка', () => editor.chain().focus().toggleHeaderRow().run(), can.toggleHeaderRow())}
        {cellBtn('Удалить таблицу', '✕ табл', () => editor.chain().focus().deleteTable().run(), can.deleteTable())}
      </span>
    )
  }

  return (
    <span className="relative shrink-0">
      <ToolbarButton title="Вставить таблицу" active={open} onClick={() => setOpen((v) => !v)}>
        <TableIcon className="h-4 w-4" />
      </ToolbarButton>
      {open && (
        <div className="absolute left-0 top-full z-20 mt-1 w-44 space-y-2 rounded-lg border border-glass-border bg-bg-alt p-2 shadow-glass">
          <label className="flex items-center justify-between gap-2 text-xs text-text2">
            Строк
            <input
              type="number"
              min={1}
              max={20}
              value={rows}
              onChange={(e) => setRows(Number(e.target.value) || 1)}
              className="w-14 rounded border border-glass-border bg-glass px-1.5 py-0.5 text-right text-xs text-text focus:outline-none"
            />
          </label>
          <label className="flex items-center justify-between gap-2 text-xs text-text2">
            Колонок
            <input
              type="number"
              min={1}
              max={10}
              value={cols}
              onChange={(e) => setCols(Number(e.target.value) || 1)}
              className="w-14 rounded border border-glass-border bg-glass px-1.5 py-0.5 text-right text-xs text-text focus:outline-none"
            />
          </label>
          <label className="flex cursor-pointer items-center gap-2 text-xs text-text2">
            <input
              type="checkbox"
              checked={withHeader}
              onChange={(e) => setWithHeader(e.target.checked)}
              className="h-3.5 w-3.5 accent-[#FFB200]"
            />
            Строка заголовков
          </label>
          <button
            type="button"
            onMouseDown={(e) => {
              e.preventDefault()
              insert()
            }}
            className="w-full rounded bg-amber px-2 py-1 text-xs font-semibold text-on-amber hover:opacity-90"
          >
            Вставить
          </button>
        </div>
      )}
    </span>
  )
}

function Toolbar({ editor }: { editor: Editor }) {
  const [, setTick] = useState(0)
  useEffect(() => {
    const rerender = () => setTick((t) => t + 1)
    editor.on('selectionUpdate', rerender)
    editor.on('transaction', rerender)
    return () => {
      editor.off('selectionUpdate', rerender)
      editor.off('transaction', rerender)
    }
  }, [editor])

  const setLink = () => {
    const prev = editor.getAttributes('link').href as string | undefined
    // Однострочный inline-ввод ссылки поверх выделения.
    const url = window.prompt('Ссылка (https://…)', prev ?? 'https://')
    if (url === null) return
    if (!url || url === 'https://') {
      editor.chain().focus().unsetLink().run()
      return
    }
    if (!/^(https?:\/\/|mailto:|tel:)/i.test(url)) return
    editor.chain().focus().setLink({ href: url }).run()
  }

  return (
    <div className="flex flex-wrap items-center gap-0.5 border-b border-glass-border p-1">
      <ToolbarButton
        title="Жирный"
        active={editor.isActive('bold')}
        onClick={() => editor.chain().focus().toggleBold().run()}
      >
        <Bold className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Курсив"
        active={editor.isActive('italic')}
        onClick={() => editor.chain().focus().toggleItalic().run()}
      >
        <Italic className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Подчёркнутый"
        active={editor.isActive('underline')}
        onClick={() => editor.chain().focus().toggleUnderline().run()}
      >
        <UnderlineIcon className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Зачёркнутый"
        active={editor.isActive('strike')}
        onClick={() => editor.chain().focus().toggleStrike().run()}
      >
        <Strikethrough className="h-4 w-4" />
      </ToolbarButton>
      <span className="mx-1 h-5 w-px bg-glass-border" />
      {/* Стиль абзаца + размер текста (ОС 12.08 «как в Ворде»). */}
      <select
        title="Стиль текста"
        className={toolbarSelectClass}
        value={
          HEADING_LEVELS.find((level) => editor.isActive('heading', { level }))?.toString() ?? 'p'
        }
        onChange={(e) => {
          const v = e.target.value
          if (v === 'p') editor.chain().focus().setParagraph().run()
          else editor.chain().focus().setHeading({ level: Number(v) as 1 | 2 | 3 | 4 }).run()
        }}
      >
        <option value="p">Обычный текст</option>
        {HEADING_LEVELS.map((level) => (
          <option key={level} value={level}>
            Заголовок {level}
          </option>
        ))}
      </select>
      <select
        title="Размер текста"
        className={toolbarSelectClass}
        value={
          (editor.getAttributes('textStyle').fontSize as string | undefined)?.replace('px', '') ??
          ''
        }
        onChange={(e) => {
          const v = e.target.value
          if (v === '') editor.chain().focus().unsetFontSize().run()
          else editor.chain().focus().setFontSize(`${v}px`).run()
        }}
      >
        <option value="">Размер</option>
        {FONT_SIZES.map((size) => (
          <option key={size} value={size}>
            {size} px
          </option>
        ))}
      </select>
      <ToolbarButton
        title="Маркированный список"
        active={editor.isActive('bulletList')}
        onClick={() => editor.chain().focus().toggleBulletList().run()}
      >
        <List className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Нумерованный список"
        active={editor.isActive('orderedList')}
        onClick={() => editor.chain().focus().toggleOrderedList().run()}
      >
        <ListOrdered className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Цитата"
        active={editor.isActive('blockquote')}
        onClick={() => editor.chain().focus().toggleBlockquote().run()}
      >
        <Quote className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Разделитель"
        onClick={() => editor.chain().focus().setHorizontalRule().run()}
      >
        <Minus className="h-4 w-4" />
      </ToolbarButton>
      <span className="mx-1 h-5 w-px bg-glass-border" />
      <ToolbarButton title="Ссылка" active={editor.isActive('link')} onClick={setLink}>
        <Link2 className="h-4 w-4" />
      </ToolbarButton>
      <TableControls editor={editor} />
      <ToolbarButton
        title="Выделение фоном"
        active={editor.isActive('highlight')}
        onClick={() => editor.chain().focus().toggleHighlight().run()}
      >
        <Highlighter className="h-4 w-4" />
      </ToolbarButton>
      {TEXT_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          title="Цвет текста"
          onMouseDown={(e) => {
            e.preventDefault()
            editor.chain().focus().setColor(color).run()
          }}
          className="h-5 w-5 rounded-full border border-glass-border"
          style={{ backgroundColor: color }}
        />
      ))}
      <ToolbarButton
        title="Сбросить форматирование"
        onClick={() => editor.chain().focus().unsetAllMarks().clearNodes().run()}
      >
        <Eraser className="h-4 w-4" />
      </ToolbarButton>
      <span className="mx-1 h-5 w-px bg-glass-border" />
      {/* shrink-0 без wrap внутри: группа callout-кнопок переносится целиком,
          а не рвётся посередине при узком тулбаре. */}
      <span className="flex shrink-0 items-center gap-0.5">
        {(Object.keys(CALLOUT_META) as CalloutKind[]).map((kind) => (
          <button
            key={kind}
            type="button"
            title={CALLOUT_META[kind].label}
            onMouseDown={(e) => {
              e.preventDefault()
              editor.chain().focus().toggleCallout(kind).run()
            }}
            className={cn(
              'rounded px-1.5 py-1 text-xs',
              editor.isActive('callout', { kind })
                ? 'bg-surface text-amber'
                : 'text-text3 hover:bg-glass hover:text-text',
            )}
          >
            {CALLOUT_META[kind].emoji}
          </button>
        ))}
      </span>
    </div>
  )
}

export default function RichEditor({
  value,
  onChange,
  placeholder = 'Текст…',
  className,
  extraExtensions,
  extraNodeTypes,
  extraToolbar,
}: {
  value: RichDoc | null
  onChange: (doc: RichDoc) => void
  placeholder?: string
  className?: string
  /** Доменные ноды поверх базового набора (уроки Ф3a — lessonNodes.ts). */
  extraExtensions?: AnyExtension[]
  /** Типы доменных нод — санитайзер пропускает их нетронутыми. */
  extraNodeTypes?: ReadonlySet<string>
  /** Дополнительные кнопки тулбара (загрузка медиа и т.п.). */
  extraToolbar?: (editor: Editor) => React.ReactNode
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        heading: { levels: [1, 2, 3, 4] },
        // code/codeBlock вне серверного whitelist — выключаем на уровне
        // схемы, чтобы паста их не создавала (контент деградирует в текст).
        code: false,
        codeBlock: false,
        // v3-StarterKit включает link/underline сам — не дублируем с явными.
        link: false,
        underline: false,
      }),
      Underline,
      Link.configure({
        openOnClick: false,
        autolink: true,
        protocols: ['https', 'http', 'mailto', 'tel'],
      }),
      TextStyle,
      FontSize,
      Color,
      Highlight.configure({ multicolor: true }),
      Table.configure({ resizable: false }),
      TableRow,
      TableCell,
      TableHeader,
      Callout,
      Placeholder.configure({ placeholder }),
      ...(extraExtensions ?? []),
    ],
    content: value?.doc ?? undefined,
    editorProps: {
      attributes: {
        class:
          'prose-hub min-h-[160px] max-w-none px-3 py-2 text-sm text-text focus:outline-none',
      },
    },
    onUpdate: ({ editor: e }) => {
      // Санитизация на ВЫХОДЕ: editor-state не трогаем (undo цел), наружу
      // уходит зеркальный серверному whitelist doc (см. sanitizeRichDoc).
      const doc = sanitizeRichDoc(e.getJSON() as RichDoc['doc'], extraNodeTypes)
      onChange({ schema: 1, doc })
    },
  })

  if (!editor) return null
  return (
    <div
      className={cn(
        'rounded-lg border border-glass-border bg-glass focus-within:border-amber',
        className,
      )}
    >
      <Toolbar editor={editor} />
      {extraToolbar && (
        <div className="flex flex-wrap items-center gap-0.5 border-b border-glass-border p-1">
          {extraToolbar(editor)}
        </div>
      )}
      <EditorContent editor={editor} />
    </div>
  )
}
