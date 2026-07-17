import { Color } from '@tiptap/extension-color'
import { Highlight } from '@tiptap/extension-highlight'
import { Link } from '@tiptap/extension-link'
import { Placeholder } from '@tiptap/extension-placeholder'
import { Table } from '@tiptap/extension-table'
import { TableCell } from '@tiptap/extension-table-cell'
import { TableHeader } from '@tiptap/extension-table-header'
import { TableRow } from '@tiptap/extension-table-row'
import { TextStyle } from '@tiptap/extension-text-style'
import { Underline } from '@tiptap/extension-underline'
import { EditorContent, useEditor, type Editor } from '@tiptap/react'
import StarterKit from '@tiptap/starter-kit'
import {
  Bold,
  Eraser,
  Heading2,
  Heading3,
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

/**
 * TipTap-редактор (Ф2). Живёт в ОТДЕЛЬНОМ lazy-chunk'е — грузится только
 * когда author/publisher открывает форму контента; линейный персонал и
 * прохождение контента (RichRenderer) ProseMirror не тянут.
 *
 * Значение — {schema: 1, doc} (сервер валидирует whitelist нод).
 */

const TEXT_COLORS = ['#FFB200', '#e05252', '#3fae6a', '#5b8def', '#a06bd8']

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
      <ToolbarButton
        title="Заголовок"
        active={editor.isActive('heading', { level: 2 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 2 }).run()}
      >
        <Heading2 className="h-4 w-4" />
      </ToolbarButton>
      <ToolbarButton
        title="Подзаголовок"
        active={editor.isActive('heading', { level: 3 })}
        onClick={() => editor.chain().focus().toggleHeading({ level: 3 }).run()}
      >
        <Heading3 className="h-4 w-4" />
      </ToolbarButton>
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
      <ToolbarButton
        title="Таблица 3×3"
        active={editor.isActive('table')}
        onClick={() =>
          editor.isActive('table')
            ? editor.chain().focus().deleteTable().run()
            : editor.chain().focus().insertTable({ rows: 3, cols: 3, withHeaderRow: true }).run()
        }
      >
        <TableIcon className="h-4 w-4" />
      </ToolbarButton>
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
    </div>
  )
}

export default function RichEditor({
  value,
  onChange,
  placeholder = 'Текст…',
  className,
}: {
  value: RichDoc | null
  onChange: (doc: RichDoc) => void
  placeholder?: string
  className?: string
}) {
  const editor = useEditor({
    extensions: [
      StarterKit.configure({ heading: { levels: [2, 3, 4] } }),
      Underline,
      Link.configure({
        openOnClick: false,
        autolink: true,
        protocols: ['https', 'http', 'mailto', 'tel'],
      }),
      TextStyle,
      Color,
      Highlight.configure({ multicolor: true }),
      Table.configure({ resizable: false }),
      TableRow,
      TableCell,
      TableHeader,
      Callout,
      Placeholder.configure({ placeholder }),
    ],
    content: value?.doc ?? undefined,
    editorProps: {
      attributes: {
        class:
          'prose-hub min-h-[160px] max-w-none px-3 py-2 text-sm text-text focus:outline-none',
      },
    },
    onUpdate: ({ editor: e }) => {
      onChange({ schema: 1, doc: e.getJSON() as RichDoc['doc'] })
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
      <EditorContent editor={editor} />
    </div>
  )
}
