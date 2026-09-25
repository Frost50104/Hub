"""Pydantic settings for Signaris Hub backend.

All env vars are prefixed SIGNARIS_HUB_* — e.g. SIGNARIS_HUB_DATABASE_URL.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _read_version_file() -> str:
    """Версия сборки из файла `VERSION` в корне проекта.

    Файл пишет `deploy.sh` (git-hash + dirty + timestamp) и rsync'ает вместе
    с кодом — тот же источник, что `web/public/version.json`. Локально и в
    тестах файла может не быть → `0.0.0-dev`. Env SIGNARIS_HUB_APP_VERSION
    по-прежнему побеждает (pydantic читает env поверх default).
    """
    try:
        value = (_PROJECT_ROOT / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0.0.0-dev"
    return value or "0.0.0-dev"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SIGNARIS_HUB_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # Environment
    environment: str = Field(default="staging")
    app_version: str = Field(default_factory=_read_version_file)
    # Часовой пояс для ЧЕЛОВЕКОЧИТАЕМЫХ дат в уведомлениях/экспортах
    # (app/services/timefmt.py). Tenant-tz нет; сеть UPPETIT — Москва.
    display_timezone: str = Field(default="Europe/Moscow")
    port: int = Field(default=5060)
    debug_rls: bool = Field(default=False)

    # Database (app role for runtime; migrate role for alembic upgrades)
    database_url: str = Field(default="postgresql+asyncpg://signaris_hub@localhost:5432/signaris_hub_db")
    database_migration_url: str | None = Field(default=None)

    # Redis (DB 4 prod / 5 staging — see CLAUDE.md)
    redis_url: str = Field(default="redis://127.0.0.1:6379/5")

    # signaris-auth integration
    signaris_auth_jwks_url: str = Field(default="https://auth.signaris.ru/.well-known/jwks.json")
    signaris_auth_issuer: str = Field(default="auth.signaris.ru")
    signaris_auth_base_url: str = Field(default="https://auth.signaris.ru")
    signaris_service_key: str | None = Field(default=None)
    deletion_sync_enabled: bool = Field(default=True)
    deletion_sync_poll_sec: float = Field(default=60.0)
    # Staff-sync (0052): pull штата продукта из auth — тени + кеш ролей +
    # автосоздание учебных карточек. Ключ ОТДЕЛЬНЫЙ (метка hub в auth):
    # ошибка в общем signaris_service_key молча отняла бы отзыв SSO-сессий
    # (sid-sync), поэтому смешивать их нельзя. На staging воркер держим
    # выключенным: VAPID-ключ общий с прод, и bootstrap-залп по staging-копии
    # подписок ушёл бы на реальные устройства.
    staff_service_key: str | None = Field(default=None)
    staff_sync_enabled: bool = Field(default=True)
    staff_sync_interval_sec: float = Field(default=900.0)
    # Sites-sync (0053): зеркало реестра объектов auth. Планировщика НЕТ
    # сознательно (данные меняются ~4 раза в год) — только ручной триггер;
    # флаг гейтит живой прогон ручки (при false она форсит dry-run). Ключ —
    # тот же staff_service_key (auth добавил метке hub право на объекты).
    sites_sync_enabled: bool = Field(default=True)
    # Свежесть снимка зеркала — ФИКСИРОВАННЫЕ сутки (не 2×интервал: интервала
    # не существует). Протухший снимок откатывает карточки к локальным полям
    # с меткой «данные реестра устарели».
    sites_snapshot_fresh_days: int = Field(default=14)

    # Кадровые данные из auth (шаг 16d, 0063). План —
    # ~/.claude/plans/pure-plotting-hartmanis.md.
    # - hr_consumer_enabled — читать снимок справочников `/org-directory`,
    #   вести состояние заморозки, отчёт и счётчики правила K. Выключено — ключ
    #   `hr` игнорируется, как до 16d. После каткатa выключатель останавливает
    #   обновления, но НЕ снимает заморозку: она читает `hr_sync_state`.
    # - hr_apply_tenants — slug-и тенантов через запятую, где кадровые данные
    #   ПРИМЕНЯЮТСЯ. Пусто — везде только отчёт. Это не заморозка (её ведёт
    #   `hr_mode` в auth, ручной флаг контракт запрещает), а наш рубильник
    #   записи: каткат тенанта = добавить его сюда.
    # - N / M / K — предохранитель (карточек, новых обязательных членств) и
    #   число прогонов подряд с отключённой учёткой до архива.
    hr_consumer_enabled: bool = Field(default=False)
    hr_apply_tenants: str = Field(default="")
    hr_valve_max_cards: int = Field(default=10, ge=0)
    hr_valve_max_mandatory: int = Field(default=20, ge=0)
    hr_deactivation_runs: int = Field(default=3, ge=2, le=50)
    # Учётку включили, а имя не совпало со снимком при архиве: true — это другой
    # человек (auth оживлял отключённую учётку приглашением на ту же почту),
    # вход старой карточки отвязываем. auth закрыл это 25.09 (приглашение на
    # адрес с живой учёткой → 409); ПОСЛЕ их выката выставить false на обоих
    # env — тогда несовпадение = тот же человек с новой фамилией: возврат + WARN.
    hr_release_on_name_mismatch: bool = Field(default=True)

    @property
    def hr_apply_tenant_slugs(self) -> frozenset[str]:
        return frozenset(
            part.strip().lower() for part in self.hr_apply_tenants.split(",") if part.strip()
        )

    # Sid-sync (Phase 2 SLO) — фоновый воркер опрашивает фид ревокации SSO-сессий
    # (GET /api/products/revoked-sids, X-Service-Key) и держит локальный
    # blacklist `sso_session_id`'ов. `require_auth` отказывает в access-токенах
    # с ревокнутым sid мгновенно (≤ poll-интервал), не дожидаясь access-TTL.
    # См. `app/services/sid_sync.py`.
    sid_sync_enabled: bool = Field(default=True)
    sid_sync_poll_sec: float = Field(default=30.0)

    # «Гусиная гонка» (0057). Два рубильника:
    # - race_enabled — модуль существует вообще (второй, тенантный, — ключ
    #   `race_enabled` в learning_settings, дефолт false); выключено = ручки
    #   404, меню и маршруты спрятаны, джобы выходят, данные остаются;
    # - race_sync_enabled — любые обращения к iiko из модуля и пуши гонки.
    #   На staging ВСЕГДА false: креды iiko общие с продом, а Redis-DB разные —
    #   лок слота лицензии с staging проду не виден; VAPID тоже общий.
    race_enabled: bool = Field(default=True)
    race_sync_enabled: bool = Field(default=True)

    # Шаблоны проектов (0060) — модуль существует вообще; второй, тенантный,
    # рубильник — ключ `project_templates_enabled` в learning_settings
    # (дефолт false). Выключено = ручки библиотеки/копирования 404, страница
    # шаблона 404, меню спрятано; шаблоны остаются в БД и невидимы.
    project_templates_enabled: bool = Field(default=True)

    # Личные напоминания по задачам (0062). Не «модуль-остров», а часть ядра
    # трекера — тенантного тумблера нет; env-флаг — аварийный выключатель:
    # гасит ручки (404), воркер, `/api/me.features.task_reminders` и строку в
    # настройках уведомлений. Опрос воркера — раз в N секунд (точность «ко
    # времени» ≈ опрос + отправка).
    task_reminders_enabled: bool = Field(default=True)
    task_reminders_poll_sec: float = Field(default=20.0, ge=5.0, le=300.0)

    # CORS — staging + prod fronts
    cors_origins: list[str] = Field(
        default_factory=lambda: [
            "https://hub-staging.signaris.ru",
            "https://hub.signaris.ru",
        ]
    )

    # VAPID (Web Push, Hub-MVP.4)
    vapid_public_key: str | None = Field(default=None)
    vapid_private_key_path: Path | None = Field(default=None)
    vapid_subject: str = Field(default="mailto:ops@signaris.ru")
    # Сколько дней подписка живёт без подтверждения. Продлевается на каждом
    # `POST /push/subscribe`, а его шлёт тихая переподписка при запуске PWA
    # (`web/src/lib/pushRefresh.ts`). Пара «гейт + продление» неразделима:
    # гейт без продления — это выключатель пушей.
    push_freshness_days: int = Field(default=30, ge=1, le=365)

    # Sentry (Hub-MVP.5)
    sentry_dsn: str | None = Field(default=None)

    # Attachments (Hub-MVP.5)
    attachments_root: Path = Field(default=Path("/opt/signaris-hub/attachments"))
    # Инструкции по работе в Hub: две готовые HTML-страницы, приезжают обычным
    # rsync'ом деплоя вместе с кодом. На staging путь другой — задаётся env.
    guides_root: Path = Field(default=Path("/opt/signaris-hub/guides"))
    attachment_max_bytes: int = Field(default=20 * 1024 * 1024)
    # Видео — отдельный потолок: минута съёмки с телефона в 1080p весит ~100 МБ,
    # и общий двадцатимегабайтный лимит делал вложение-видео невозможным
    # (ОС 15.09). Лимит выбирает `attachments.attachment_size_limit(mime)`;
    # клиентское зеркало — `web/src/lib/attachmentTypes.ts`.
    attachment_video_max_bytes: int = Field(default=1024 * 1024 * 1024)

    # Проект приёма обратной связи из настроек. Ключ, а не id: переживает
    # переименование проекта и читается человеком в .env.
    feedback_project_key: str = Field(default="RH")

    # Learn-медиа (Ф3a): подписанные URL для <video>/<img>/pdf (Bearer в тегах
    # не работает). Секрет — HMAC-ключ подписей; если не задан, derive из
    # database_url (стабильно per-env). media_accel: отдача через nginx
    # X-Accel-Redirect (в тестах/локально False → FileResponse напрямую).
    media_url_secret: str | None = Field(default=None)
    media_accel_enabled: bool = Field(default=True)
    media_url_ttl_sec: int = Field(default=6 * 3600)
    # Отказ загрузки при малом свободном месте: диск общий с Postgres/WAL.
    media_min_free_bytes: int = Field(default=5 * 1024 * 1024 * 1024)

    # AI-помощник (Ф6). Провайдер: yandex | gigachat | openai (последний —
    # OpenAI-compatible API: OpenAI/Mistral/DeepSeek/прокси, переключение
    # конфигом без кода). Без api_key ассистент отвечает 503 «не настроен».
    ai_enabled: bool = Field(default=True)
    ai_provider: str = Field(default="yandex")
    ai_api_key: str | None = Field(default=None)
    # yandex: folder_id обязателен; openai: base_url обязателен.
    ai_folder_id: str | None = Field(default=None)
    ai_base_url: str | None = Field(default=None)
    ai_chat_model: str | None = Field(default=None)
    ai_embed_model: str | None = Field(default=None)
    # Модель для витков с инструментами (ассистент). Разведена с ai_chat_model
    # намеренно: разбор «поставь Дмитрию на пятницу, срочно» в валидный JSON —
    # самое хрупкое место фичи, и его можно увести на модель посильнее, не
    # трогая обычные ответы по базе знаний. Пусто → та же ai_chat_model.
    ai_tool_model: str | None = Field(default=None)

    # iiko OLAP (волна 2 ассистента). Без хоста/кредов отчёты отвечают 503 и
    # фронт показывает экран «Ассистент ещё не подключён».
    # ВАЖНО: каждое подключение занимает слот лицензии iiko — клиент обязан
    # разлогиниваться, а сервис кэширует и сериализует запросы per-tenant.
    iiko_base_url: str | None = Field(default=None)
    iiko_login: str | None = Field(default=None)
    iiko_password: str | None = Field(default=None)
    iiko_verify_ssl: bool = Field(default=True)
    # Ниже nginx-потолка локации /api/ai/ (120s) и бюджета витка ассистента.
    iiko_timeout_sec: float = Field(default=30.0)
    iiko_cache_ttl_sec: int = Field(default=900)

    # Голосовой ввод ассистента (волна 3). `local` — faster-whisper в
    # ОТДЕЛЬНОМ systemd-юните: замерено на VPS 2026-08-20, модель `small`
    # даёт пик 759 МБ и ~5.5с на команду, поэтому её вес не должен жить в
    # API-процессе. `base` вдвое легче, но слышит «на пятницу» как «на 5
    # ниццу» — неверный срок задачи дороже трёх секунд ожидания.
    stt_enabled: bool = Field(default=False)
    stt_provider: str = Field(default="local")
    stt_model: str = Field(default="small")
    stt_language: str = Field(default="ru")
    stt_compute_type: str = Field(default="int8")
    stt_cpu_threads: int = Field(default=2)
    # Куда основное приложение проксирует запись при provider=local.
    stt_url: str = Field(default="http://127.0.0.1:5071")
    # Выгрузка модели по простою — на этой машине держать 759 МБ занятыми
    # круглые сутки нельзя.
    stt_idle_unload_sec: float = Field(default=300.0)
    # 2 МБ ≈ десять минут opus: команда голосом — это секунды.
    stt_max_bytes: int = Field(default=2 * 1024 * 1024)
    # Ниже nginx-потолка /api/ai/ (120с): первый запрос после простоя платит
    # ~9с за загрузку модели плюс ~6с на расшифровку.
    stt_timeout_sec: float = Field(default=60.0)
    # Платная альтернатива (provider=openai).
    stt_api_key: str | None = Field(default=None)
    stt_base_url: str | None = Field(default=None)

    # Public links (3.6.12) — view-only no-auth deep-links to a task/project.
    # Feature-flag so we can kill-switch the entire surface without a redeploy.
    public_links_enabled: bool = Field(default=True)
    # Used to build the absolute URL returned by `POST /api/.../share`.
    public_base_url: str = Field(default="https://hub.signaris.ru")


@lru_cache
def get_settings() -> Settings:
    return Settings()
