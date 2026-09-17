import { Bird } from 'lucide-react'
import { useNavigate } from 'react-router-dom'

import { EmptyState } from '@/components/ui/EmptyState'
import type { BoardState } from '@/lib/raceBoard'

export function RaceEmptyState({ state, isAdmin }: { state: Extract<BoardState, { kind: 'no-contest' }>; isAdmin: boolean }) {
  const navigate = useNavigate()
  const iikoOff = !state.iikoConfigured
  return (
    <EmptyState
      layout="card"
      icon={<Bird className="h-7 w-7" />}
      title="Гонка ещё не объявлена"
      text={
        iikoOff
          ? 'Гонка считает позиции по чекам iiko, а интеграция на этом окружении не подключена.'
          : 'Когда администратор настроит соревнование, здесь появится дорожка и таблица лидеров.'
      }
      cta={isAdmin ? 'Настроить гонку' : undefined}
      onCta={isAdmin ? () => navigate('/learn/admin?tab=race') : undefined}
    />
  )
}
