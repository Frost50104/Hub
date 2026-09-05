/** PWA установлена на домашний экран (iOS/Android standalone).
 *
 *  Едина для сертификата (печать через браузер) и библиотеки (файл через
 *  системную шторку «Поделиться»): у standalone-контекста нет ни печати,
 *  ни просмотрщика файлов — обе фичи маршрутизируются в обход. */
export function isStandalone(): boolean {
  return (
    window.matchMedia('(display-mode: standalone)').matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  )
}
