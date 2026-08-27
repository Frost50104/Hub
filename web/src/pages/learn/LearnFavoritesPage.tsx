import { BookOpen, GraduationCap, Newspaper, ShoppingBag, Star } from 'lucide-react'
import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'

import { FavoriteStar } from '@/components/learn/FavoriteStar'
import { QueryError } from '@/components/QueryError'
import { EmptyState } from '@/components/ui/EmptyState'
import { FilterChip } from '@/components/ui/FilterChip'
import { ListRow } from '@/components/ui/ListRow'
import { SkeletonRows } from '@/components/ui/Skeleton'
import { useFavorites } from '@/hooks/useLearn'
import { useMe } from '@/hooks/useMe'
import { FAVORITE_TYPE_LABEL, favoriteTypesPresent } from '@/lib/favorites'
import { plural } from '@/lib/typography'

/**
 * Экран «Избранное».
 *
 * Ручка `POST /learn/favorites/toggle` существовала с Ф2, звезда стояла только
 * у новости, и увидеть отмеченное было негде (ОС 25.08). Здесь — общий список
 * по всем четырём типам.
 *
 * Уроков в списке нет и быть не может: избранное склеивается с
 * `search_documents`, а туда попадают только материалы, новости, курсы и
 * товары. Индексация уроков — отдельная работа, не эта.
 */

const TYPE_ICON: Record<string, typeof BookOpen> = {
  library_material: BookOpen,
  news_post: Newspaper,
  course: GraduationCap,
  product: ShoppingBag,
}

export function LearnFavoritesPage() {
  const me = useMe()
  const favorites = useFavorites()
  const navigate = useNavigate()
  const [type, setType] = useState<string>('all')

  const items = useMemo(() => favorites.data ?? [], [favorites.data])
  const presentTypes = useMemo(() => favoriteTypesPresent(items), [items])
  // Тип, которого в списке уже нет (сняли последнюю звезду), не должен
  // оставлять экран пустым: фильтр молча возвращается ко «Всем».
  const activeType = type !== 'all' && presentTypes.includes(type) ? type : 'all'
  const shown = useMemo(
    () => (activeType === 'all' ? items : items.filter((i) => i.object_type === activeType)),
    [items, activeType],
  )

  // Избранное живёт на учебном профиле: без него отмечать нечем и нечего.
  const noProfile = me.data !== undefined && !me.data.profile

  return (
    <div className="mx-auto max-w-[860px] px-5 pb-16 pt-4 lg:px-8 lg:pt-11">
      <header className="flex flex-col gap-4 lg:flex-row lg:flex-wrap lg:items-end lg:justify-between lg:gap-3.5">
        <h1 className="font-display text-[28px] font-bold leading-[1.18] tracking-[0.01em] text-text lg:text-[34px] lg:leading-[1.15]">
          Избранное
        </h1>
        {presentTypes.length > 1 && (
          <div className="flex flex-wrap items-center gap-2">
            <FilterChip active={activeType === 'all'} onClick={() => setType('all')}>
              Все
            </FilterChip>
            {presentTypes.map((t) => (
              <FilterChip key={t} active={activeType === t} onClick={() => setType(t)}>
                {FAVORITE_TYPE_LABEL[t] ?? t}
              </FilterChip>
            ))}
          </div>
        )}
      </header>

      <div className="mt-4 lg:mt-[22px]">
        {favorites.isLoading && <SkeletonRows rows={4} />}
        {favorites.isError && <QueryError onRetry={() => void favorites.refetch()} />}

        {noProfile && !favorites.isLoading && (
          <EmptyState
            layout="card"
            icon={<Star className="h-7 w-7" />}
            title="Избранное пока недоступно"
            text="Оно привязано к учебному профилю — его заводит администратор. Как только профиль появится, звёздочки в библиотеке, курсах и ассортименте начнут работать."
          />
        )}

        {!noProfile && favorites.data && items.length === 0 && (
          <EmptyState
            layout="card"
            icon={<Star className="h-7 w-7" />}
            title="Здесь пока пусто"
            text="Отметьте звёздочкой документ, курс, товар или новость — они соберутся на этом экране."
            cta="В библиотеку"
            onCta={() => navigate('/learn/library')}
          />
        )}

        {shown.length > 0 && (
          <>
            <div className="overflow-hidden rounded-[14px] border border-hair">
              {shown.map((item) => {
                const Icon = TYPE_ICON[item.object_type] ?? Star
                return (
                  <ListRow
                    key={`${item.object_type}:${item.object_id}`}
                    lead={
                      <span
                        className={
                          item.available
                            ? 'flex h-9 w-9 items-center justify-center rounded-[10px] bg-surface text-text2'
                            : 'flex h-9 w-9 items-center justify-center rounded-[10px] bg-surface text-text3'
                        }
                      >
                        <Icon className="h-[18px] w-[18px]" strokeWidth={1.9} />
                      </span>
                    }
                    title={
                      <span className={item.available ? 'truncate' : 'truncate text-text2'}>
                        {item.title}
                      </span>
                    }
                    context={
                      item.available
                        ? (FAVORITE_TYPE_LABEL[item.object_type] ?? 'Объект')
                        : `${FAVORITE_TYPE_LABEL[item.object_type] ?? 'Объект'} · недоступен сейчас`
                    }
                    trailing={
                      <FavoriteStar
                        objectType={item.object_type}
                        objectId={item.object_id}
                        title={item.title}
                      />
                    }
                    // Строка без ссылки не притворяется кликабельной: объект
                    // сняли с публикации или отправили в архив, открывать нечего.
                    onClick={item.available ? () => navigate(item.url_path) : undefined}
                    ariaLabel={item.available ? `Открыть: ${item.title}` : undefined}
                    className="last:border-b-0"
                  />
                )
              })}
            </div>
            <p className="mt-3 text-[13px] leading-[1.5] text-text3">
              {plural(shown.length, 'запись', 'записи', 'записей')} в избранном
              {items.some((i) => !i.available) &&
                '. Недоступные — снятые с публикации или отправленные в архив: снимите звезду, если они больше не нужны'}
              .
            </p>
          </>
        )}
      </div>
    </div>
  )
}
