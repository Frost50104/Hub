import { authClient } from '@/lib/auth'

export function Topbar() {
  return (
    <header className="glass sticky top-0 z-10 mx-3 mt-3 flex items-center justify-between px-5 py-3">
      <div className="flex items-center gap-3">
        <img
          src="/brand/signaris-horizontal-on-dark.svg"
          alt="Signaris"
          className="h-7"
        />
        <span className="font-display text-2xl font-black leading-none tracking-tight">
          Hub
        </span>
      </div>
      <button
        onClick={() => {
          void authClient.logout()
        }}
        className="rounded-lg border border-glass-border px-3 py-1.5 text-sm text-text2 transition hover:text-text"
      >
        Выйти
      </button>
    </header>
  )
}
