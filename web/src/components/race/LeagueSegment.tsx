import { SegmentGroup } from '@/components/ui/SegmentGroup'
import type { RaceView, ViewOption } from '@/lib/raceBoard'

export function LeagueSegment({ options, value, onChange, isDesktop }: { options: ViewOption[]; value: RaceView; onChange: (v: RaceView) => void; isDesktop: boolean }) {
  if (options.length <= 1) return null
  return (
    <div className="-mx-5 overflow-x-auto px-5 pb-1 [scrollbar-width:none] lg:mx-0 lg:px-0">
      <SegmentGroup
        ariaLabel="Лига"
        options={options.map((o) => ({ value: o.value, label: o.label }))}
        value={value}
        onChange={onChange}
        size={isDesktop ? 'md' : 'lg'}
        className="w-max"
      />
    </div>
  )
}
