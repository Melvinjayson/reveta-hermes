import { cn } from '@/lib/utils'

const assetPath = (path: string) => `${import.meta.env.BASE_URL}${path}`

// Reveta derivative: use the authorised Aura mark. Leave shell sizing, actions,
// navigation and all Hermes runtime behaviour unchanged.
export function BrandMark({ className, ...props }: React.ComponentProps<'span'>) {
  return (
    <span className={cn('inline-flex size-14 shrink-0 items-center justify-center', className)} {...props}>
      <img alt="" className="size-full object-contain" src={assetPath('brand/aura-mark.svg')} draggable={false} />
    </span>
  )
}
