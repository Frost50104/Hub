import { mergeAttributes, Node } from '@tiptap/core'

import { type CalloutKind } from './calloutMeta'

export { CALLOUT_META, type CalloutKind } from './calloutMeta'

declare module '@tiptap/core' {
  interface Commands<ReturnType> {
    callout: {
      toggleCallout: (kind: CalloutKind) => ReturnType
    }
  }
}

/**
 * Смысловой блок ТЗ §5.1 («Важно», «Совет», «Ошибка»…). Хранится как
 * {type: "callout", attrs: {kind}, content: [...]} — сервер валидирует kind.
 */
export const Callout = Node.create({
  name: 'callout',
  group: 'block',
  content: 'block+',
  defining: true,

  addAttributes() {
    return {
      kind: {
        default: 'important',
        parseHTML: (el) => el.getAttribute('data-kind') || 'important',
        renderHTML: (attrs) => ({ 'data-kind': attrs.kind }),
      },
    }
  },

  parseHTML() {
    return [{ tag: 'div[data-callout]' }]
  },

  renderHTML({ HTMLAttributes }) {
    return [
      'div',
      mergeAttributes(HTMLAttributes, { 'data-callout': '', class: 'hub-callout' }),
      0,
    ]
  },

  addCommands() {
    return {
      toggleCallout:
        (kind) =>
        ({ commands, editor }) => {
          if (editor.isActive('callout', { kind })) {
            return commands.lift('callout')
          }
          if (editor.isActive('callout')) {
            return commands.updateAttributes('callout', { kind })
          }
          return commands.wrapIn('callout', { kind })
        },
    }
  },
})
