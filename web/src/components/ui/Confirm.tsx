import { Button } from '@/components/ui/Button'
import { ResponsiveDialog } from '@/components/ui/ResponsiveDialog'

/**
 * Подтверждение необратимого или платного действия: шторка ниже `lg`,
 * модалка на десктопе (`ResponsiveDialog`). Вынесен из «Управление → Гонка»
 * (0057), чтобы конвейер видео (0066) не копировал его в третий раз.
 */
export function Confirm({
  open,
  onOpenChange,
  title,
  text,
  confirmLabel,
  destructive,
  pending = false,
  onConfirm,
}: {
  open: boolean
  onOpenChange: (v: boolean) => void
  title: string
  text: React.ReactNode
  confirmLabel: string
  destructive?: boolean
  pending?: boolean
  onConfirm: () => void
}) {
  return (
    <ResponsiveDialog
      open={open}
      onOpenChange={onOpenChange}
      title={title}
      footer={
        <>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Отмена
          </Button>
          <Button
            variant={destructive ? 'destructive' : 'default'}
            disabled={pending}
            onClick={onConfirm}
          >
            {pending ? 'Выполняем…' : confirmLabel}
          </Button>
        </>
      }
    >
      {typeof text === 'string' ? <p className="text-[14px] text-text2">{text}</p> : text}
    </ResponsiveDialog>
  )
}
