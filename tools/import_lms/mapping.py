"""Ручные данные миграции: то, чего нет в выгрузке ServiceGuru.

Три вещи выгрузка потеряла, и восстановить их автоматически нельзя:

1. **Названия листов обрезаны до 28 символов** (40 из 165) — Excel-лимит.
   `FULL_TITLES` восстанавливает по содержимому урока/теста.
2. **Связь теста с уроком** — в выгрузке её нет вообще (тесты названы
   «Для закрепления 72» и т.п.). `QUIZ_TO_LESSON` восстановлена по смыслу
   вопросов; `FINAL_QUIZZES` — тесты уровня курса (итоговые).
3. **Имена файлов `RackMultipart*`** — Rails затёр оригинальные при загрузке.
   `FILE_TITLES` даёт человеческие названия по содержимому.

Плюс редакторские решения: тип/порядок курсов, аудитории (контуры),
структура разделов библиотеки.
"""

from __future__ import annotations

# ─── Курсы ──────────────────────────────────────────────────────────────────
# slug → (название, course_type, org_roles-аудитория | None = всем, position)
COURSES: dict[str, tuple[str, str, frozenset[str] | None, int]] = {
    "dobro-pozhalovat": ("Добро пожаловать в UPPETIT", "mandatory", None, 0),
    "pischevaya-bezopasnost": ("Пищевая безопасность", "mandatory", None, 1),
    "nasha-komanda": ("Наша команда", "info", None, 2),
    "rabota-s-gostyami": ("Работа с гостями", "info", None, 3),
    "prodazhi-pervye-shagi": ("Продажи: первые шаги", "info", None, 4),
    "tehnika-prodazh": ("Техника продаж", "info", None, 5),
    "tipy-pokupateley": ("Типы покупателей", "info", None, 6),
    "konfliktnye-situatsii": ("Конфликтные ситуации", "info", None, 7),
    "baristika": ("Баристика", "info", None, 8),
    "rabota-s-iiko": ("Работа с iiko", "info", None, 9),
    "priem-tovara-i-rabota-s-nakladnymi": (
        "Приём товара и работа с накладными",
        "info",
        None,
        10,
    ),
    "osnovy-kommunikatsii-v-professionalnoy-deyatelnosti": (
        "Основы коммуникации в профессиональной деятельности",
        "info",
        None,
        11,
    ),
    "nastavnik-guru-v-svoem-dele": ("Наставник: гуру в своём деле", "career", None, 12),
    "administrator": ("Администратор", "career", None, 13),
    "upravlenie-v-deystvii-rukovodstvo-motivatsiya-i-konflikty": (
        "Управление в действии: руководство, мотивация и конфликты",
        "career",
        None,
        14,
    ),
    # Офис добавлен к целевым контурам: курс остаётся адресным, но офисные
    # сотрудники видят его для справки (решение пользователя 2026-08-16).
    "territorialnyy-upravlyayuschiy": (
        "Территориальный управляющий",
        "career",
        frozenset({"tu", "office"}),
        15,
    ),
    "franchayzi-uppetit-gotovimsya-k-vzletu": (
        "Франчайзи UPPETIT: готовимся к взлёту",
        "career",
        frozenset({"franchisee_owner", "office"}),
        16,
    ),
}

VIDEO_COURSE_SLUG = "videoinstruktsii"
VIDEO_COURSE = ("Видеоинструкции", "info", None, 17)

# ─── Восстановленные названия (обрезаны Excel'ем до 28 символов) ────────────
FULL_TITLES: dict[str, str] = {
    # administrator
    "Роль администратора в магази": "Роль администратора в магазине",
    # baristika
    "Кофейная ягода. Обработка.Об": "Кофейная ягода. Обработка. Обжарка",
    "Регламент работы с барной зо": "Регламент работы с барной зоной",
    "Технико - технологическая ка": "Технико-технологическая карта (ТТК)",
    "Закрепление терруар, арабика": "Закрепление: терруар, арабика, робуста",
    "Закрепление кофейная ягода,": "Закрепление: кофейная ягода, обработка, обжарка",
    # dobro-pozhalovat
    "Карьерный рост в компании UP": "Карьерный рост в компании UPPETIT",
    "Ежедневный чек-лист сотрудни": "Ежедневный чек-лист сотрудника",
    "Заполнение и ведение журнало": "Заполнение и ведение журналов",
    # franchayzi
    "Разграничение обязанностей ф": "Разграничение обязанностей франчайзера и франчайзи",
    # nastavnik
    "Работа с беседой Наставничес": "Работа с беседой «Наставничество»",
    "План стажировки Мобильного П": "План стажировки мобильного продавца",
    "Скрипты общения наставника с": "Скрипты общения наставника со стажёром",
    "План стажировки Администрато": "План стажировки администратора",
    "План стажировки Продавца-Бар": "План стажировки продавца-бариста",
    # osnovy-kommunikatsii
    "Профилактика Синдрома выгора": "Профилактика синдрома выгорания",
    "Конфликт и возможности его у": "Конфликт и возможности его урегулирования",
    "Характеристики процесса обще": "Характеристика процесса общения",
    "Проблемы межгруппового взаим": "Проблемы межгруппового взаимодействия",
    "Общение как обмен информацие": "Общение как обмен информацией",
    "Развитие группы и групповые": "Развитие группы и групповые процессы",
    # pischevaya-bezopasnost
    "Предотвращение заражения про": "Предотвращение заражения продуктов",
    "Чистота и санитарная обработ": "Чистота и санитарная обработка",
    # priem-tovara
    "Формат заморозка. Полная мат": "Формат «заморозка». Полная матрица",
    # rabota-s-iiko
    "Работа с остатками и автозак": "Работа с остатками и автозаказом",
    "Работа с системой iiko. iiko": "Работа с системой iiko. iikoFront",
    # tehnika-prodazh (тесты)
    "Принципы специалиста по прод": "Принципы специалиста по продажам",
    "Стандарты продаж что это и д": "Стандарты продаж: что это и для чего",
    "Правила эффективного специал": "Правила эффективного специалиста",
    # territorialnyy
    "Обязанности Территориального": "Обязанности территориального управляющего",
    "Базовые знания Трудового код": "Базовые знания Трудового кодекса РФ",
    # tipy-pokupateley
    "Как определить тип покупател": "Как определить тип покупателя",
    # upravlenie-v-deystvii
    "Выявление, устранение и пред": "Выявление, устранение и предотвращение конфликтов",
    "Делегирование Искусство дове": "Делегирование: искусство доверять",
}

# ─── Тест → урок (восстановлено по смыслу вопросов) ─────────────────────────
# Ключ: (slug курса, имя листа теста) → имя листа урока (как в выгрузке).
QUIZ_TO_LESSON: dict[tuple[str, str], str] = {
    ("administrator", "Тест SMART"): "SMART-цели",
    ("administrator", "Тест Обратная связь"): "Обратная связь",
    ("administrator", "Тест мотивация"): "Мотивация",
    ("baristika", "Закрепление терруар, арабика"): "Терруар, Арабика, Робуста.",
    ("baristika", "Закрепление экстракция."): "Экстракция кофе.",
    ("baristika", "Закрепление кофейная ягода,"): "Кофейная ягода. Обработка.Об",
    ("baristika", "Рецептура напитков"): "Технико - технологическая ка",
    ("dobro-pozhalovat", "Для закрепления"): "Ценности бренда UPPETIT",
    ("dobro-pozhalovat", "Для закрепления 72"): "Давай познакомимся поближе",
    ("dobro-pozhalovat", "Для закрепления 86"): "Акции и Комбо",
    ("dobro-pozhalovat", "Для закрепления 52"): "Карьерный рост в компании UP",
    ("dobro-pozhalovat", "Для закрепления 57"): "Заполнение и ведение журнало",
    ("dobro-pozhalovat", "Для закрепления 34"): "Стартовая инструкция",
    ("dobro-pozhalovat", "Для закрепления 55"): "Чаты и правила коммуникации",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления"): "Очень важно",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 63"): (
        "Планирование на производстве"
    ),
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 53"): "Маркетинг в UPPETIT",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 56"): "Показатели в магазине",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 93"): "Работа с командой",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 67"): "Клиентский опыт",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 9"): "Еще кое-что",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 49"): "Управление финансами",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 51"): "Бухгалтерия магазина",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 41"): "Инвентаризация в UPPETIT",
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Для закрепления 66"): (
        "Разграничение обязанностей ф"
    ),
    ("nastavnik-guru-v-svoem-dele", "Закрепим знания"): "Наставничество",
    ("nastavnik-guru-v-svoem-dele", "Закрепим знания 59"): "Скрипты общения наставника с",
    ("nastavnik-guru-v-svoem-dele", "Закрепим знания 18"): "Работа с беседой Наставничес",
    ("nastavnik-guru-v-svoem-dele", "Закрепим знания 37"): "План стажировки Продавца-Бар",
    ("pischevaya-bezopasnost", "Проверка знаний"): "Введение",
    ("pischevaya-bezopasnost", "Проверка знаний 96"): "Предотвращение заражения про",
    ("pischevaya-bezopasnost", "Проверим знания"): "Хранение продукции",
    ("priem-tovara-i-rabota-s-nakladnymi", "Для закрепления"): "Заполнение шаблонов заказов",
    ("priem-tovara-i-rabota-s-nakladnymi", "Для закрепления 39"): "Прием и оприходование товара",
    ("prodazhi-pervye-shagi", "Тест"): "Доп.продажи",
    ("prodazhi-pervye-shagi", "Тест 93"): "Расположение товаров",
    ("rabota-s-gostyami", "Для закрепления"): "Ответы на вопросы гостей",
    ("rabota-s-gostyami", "Проверим знания"): "Забота о госте",
    ("rabota-s-gostyami", "Проверим знания 49"): "Кассовые операции",
    ("rabota-s-iiko", "Для закрепления"): "Работа с остатками и автозак",
    ("rabota-s-iiko", "Для закрепления 44"): "Списание продукции",
    ("rabota-s-iiko", "Для закрепления 71"): "Питание сотрудников",
    ("rabota-s-iiko", "Для закрепления 84"): "Работа с системой iiko. iiko",
    ("rabota-s-iiko", "Для закрепления 83"): "Доставка",
    ("tehnika-prodazh", "Принципы специалиста по прод"): "Принципы работы",
    ("tehnika-prodazh", "Этапы продаж - важное"): "Этапы продаж",
    ("tehnika-prodazh", "Стандарты продаж что это и д"): "Стандарты",
    ("tehnika-prodazh", "Правила эффективного специал"): "Основные правила работы",
    ("territorialnyy-upravlyayuschiy", "Проверим знания"): "Обязанности Территориального",
    ("territorialnyy-upravlyayuschiy", "Проверим знания 26"): "Работа с командой ч.1",
    ("territorialnyy-upravlyayuschiy", "Проверим знания 28"): "Продажи магазинов",
    ("territorialnyy-upravlyayuschiy", "Проверим знания 81"): "Финансовые показатели",
}

# Тесты уровня курса (итоговые) — привязываются к курсу, а не к уроку.
FINAL_QUIZZES: set[tuple[str, str]] = {
    ("baristika", "Итоговый тест"),
    ("franchayzi-uppetit-gotovimsya-k-vzletu", "Итоговый тест"),
    ("konfliktnye-situatsii", "Итоговый тест"),
    ("rabota-s-iiko", "Итоговый тест"),
    ("osnovy-kommunikatsii-v-professionalnoy-deyatelnosti", "Тест"),
}

# Листы тестов, которые не импортируем (пустые/битые).
SKIP_QUIZZES: set[tuple[str, str]] = {("pischevaya-bezopasnost", "Empty name")}

# ─── Библиотека: раздел → правило отбора файлов ─────────────────────────────
LIBRARY_SECTIONS: list[str] = [
    "Заказы поставщикам",
    "HR и кадровые документы",
    "Оборудование и кофе",
    "Планограммы",
    "ТТК, КБЖУ и сроки",
    "Журналы",
    "Чек-листы",
    "Прочее",
]

# Человеческие названия для файлов с потерянными именами (RackMultipart*)
# и для нечитаемых транслитов. Ключ — имя файла в «Инструкции/».
FILE_TITLES: dict[str, str] = {
    "RackMultipart20260601-4111394-womzry.docx": "Очистка варочного модуля (еженедельно)",
    "RackMultipart20260601-4122906-1re1pp.docx": "Программа ежедневной очистки кофемашины",
    "RackMultipart20260601-4128353-9z7dx2.docx": "Регламент промывки кофемашины",
    "RackMultipart20260703-3536048-f2vblt.docx": (
        "Программа санитарно-противоэпидемических мероприятий (производственный контроль)"
    ),
    "RackMultipart20260601-3568944-2yki6m.xlsx": "КБЖУ (таблица)",
    "RackMultipart20260601-3569378-cnhrpi.pdf": "ТТК без приготовления (лето)",
    "RackMultipart20260730-2535286-gdmn45.pdf": "ТТК без приготовления (осень)",
    "RackMultipart20260703-3535637-4v7xie.pdf": "Сроки хранения UPPETIT (лето 2026)",
    "RackMultipart20260730-2531099-6xy6tx.pdf": "Сроки хранения UPPETIT (осень 2026)",
    "RackMultipart20260715-1213282-doagy3.pdf": (
        "Инструкция по маркировке вскрытых и расфасованных барных ингредиентов"
    ),
    "RackMultipart20260618-851279-u9oa41.pdf": "Наставничество и депремирование",
    "RackMultipart20260810-188124-5cmsa0.pdf": "Взбивание молока: пошаговая памятка",
    "RackMultipart20260810-186399-bsuop7.zip": "Мониторы и музыка: инструкция для магазинов",
    "Delta._Instruktsiya.pdf": "Delta: инструкция",
    "Terruar._Arabika._Robusta.pdf": "Терруар. Арабика. Робуста",
    "Kofeynaya_yagoda._Obrabotka._Obzharka.pdf": "Кофейная ягода. Обработка. Обжарка",
    "Latte-Art_Mayya_Mihaylova.pdf": "Латте-арт (Майя Михайлова)",
    "Nastroyka_Kofemolki_i_kofemashiny.pdf": "Настройка кофемолки и кофемашины",
    "Instruktsiya_pri_neispravnosti_kofeynogo_oborudovaniya.docx": (
        "Инструкция при неисправности кофейного оборудования"
    ),
    "Prigotovlenie_i_spisanie_espresso.docx": "Приготовление и списание эспрессо",
    "Chek-list_stazhirovki_Prodavtsa-Barista.pdf": "Чек-лист стажировки продавца-бариста",
    "Chek-list-stazhirovki-Administratora__1_.pdf": "Чек-лист стажировки администратора",
    "Chek-list_peredachi_TT_administrator_UPPETIT.docx": (
        "Чек-лист передачи торговой точки (администратор)"
    ),
    "Chek-list_podgotovki_k_otkrytiyu.xlsx": "Чек-лист подготовки к открытию",
    "Chek-listy_voprosy_.xlsx": "Чек-листы: вопросы",
    "CHL_IS.docx": "Чек-лист IS",
    "Zayavlenie_na_vedenie_trudovoy_knizhki.pdf": "Заявление на ведение трудовой книжки",
    "Prikaz_ob_otkaze_ot_LNA.docx": "Приказ об отказе от ЛНА",
    "Proshito_i_pronumerovano.docx": "«Прошито и пронумеровано» (форма)",
    "Forma_Akt_ob_otkaze_rabotnika_oznakomitsya_pod_podpis_s_ak.RTF.docx": (
        "Акт об отказе работника ознакомиться под подпись"
    ),
    "Dolzhnostnaya_instruktsiya_prodavtsa.pdf": "Должностная инструкция продавца",
    "Instruktsiya_po_oformleniyu_sotrudnika.pdf": "Инструкция по оформлению сотрудника",
    "Instruktsiya_po_ballnoy_sisteme_motivatsii.pdf": "Инструкция по балльной системе мотивации",
    "Zhurnal_instruktazh_na_rabochem_meste_obrazets_UPD.pdf": (
        "Журнал инструктажа на рабочем месте (образец)"
    ),
    "ZHURNAL_UCHETA_PROVEROK_obrazets_UPD.pdf": "Журнал учёта проверок (образец)",
    "Zhurnal_po_ognetushitelyam__1_.docx": "Журнал по огнетушителям",
    "Mobilnye_prodavtsy.pdf": "Мобильные продавцы",
    "Problemy_s_edoy_i_Kontrol_Kachestva_TU.xlsx": "Проблемы с едой и контроль качества (ТУ)",
    "Instruktsiya_po_nastroyke_i_ispolzovaniyu_prilozheniya__Srok_godnosti_.pdf": (
        "Настройка и использование приложения «Срок годности»"
    ),
    "Prodstar_SHABLON.xlsx": "Prodstar: шаблон заказа",
    "aktsiya__za_otmetku_.docx": "Акция «За отметку»",
    "proga_forma.mp4": "Программа: работа с формой (видео)",
    "Konti_proga.mp4": "Konti: работа с программой (видео)",
    "Programma_knopki.mp4": "Программа: кнопки (видео)",
    "video_2026-02-27_18-08-08.mp4": "Видеоинструкция",
    "Видео замывка кофемашины.mp4": "Замывка кофемашины (видео)",
    "RackMultipart20260601-4121138-yi9h1n.mp4": "Очистка кофемашины: полный цикл (видео)",
    "RackMultipart20260601-4121138-v0h4r.mp4": "Очистка кофемашины: часть 2 (видео)",
    "RackMultipart20260601-4119548-e43slb.mp4": "Обслуживание кофейного оборудования (видео)",
    "RackMultipart20260601-3568601-pog8df.mp4": "Работа с оборудованием (видео)",
    "RackMultipart20260601-4121138-kudv8n.mp4": "Очистка кофемашины: часть 3 (видео)",
    # Бланки заказов поставщикам (имена затёрты Rails, восстановлено по содержимому).
    "RackMultipart20260608-127-51sdaj.xlsx": "Бланк заказа: напитки (Happiness)",
    "RackMultipart20260608-127-ekc8ht.xlsx": "Бланк заказа: овощи и заготовки",
    "RackMultipart20260608-127-uz7w8r.xlsx": "Бланк заказа: Русичи",
    "RackMultipart20260608-206-713gf4.xlsx": "Бланк заказа: ЗАО «Денди»",
    "RackMultipart20260608-233-jml663.xlsx": "Бланк заказа: Роял Фуд",
    "RackMultipart20260608-259-vhuzmd.xlsx": "Бланк заказа: Dobro People",
    "RackMultipart20260608-310-irqm8g.xlsx": "Бланк заказа: Тесто-Мясо",
    "RackMultipart20260608-370-137qs5.xlsx": "Бланк заказа: Dessert Fantasy",
    "RackMultipart20260608-370-15b7jk.xlsx": "Бланк заказа: рыба и морепродукты",
    "RackMultipart20260608-395-3bimxm.xlsx": "Бланк заказа: Lepim (блины)",
    "RackMultipart20260608-395-sr3724.xlsx": "Бланк заказа: кондитерка",
    "RackMultipart20260608-417-ywe6xp.xlsx": "Форма ввода номенклатуры (штрихкоды, ЧЗ)",
    "RackMultipart20260608-440-bwvfxb.xlsx": "Бланк заказа: Sweet Life",
    "RackMultipart20260608-465-kqvh3q.xlsx": "Бланк заказа: СТМ",
    "RackMultipart20260608-85-dtnb9h.xlsx": "Бланк заказа: Multon Partners",
    "RackMultipart20260619-2026584-a1m4hr.xlsx": "Бланк заказа (общий, 5 адресов)",
    "RackMultipart20260703-3536674-83m178.xlsx": "Бланк заказа: Иванов (напитки)",
    "RackMultipart20260703-3537427-99nhlp.xlsx": "Бланк заказа: Завитой (молочка)",
    "RackMultipart20260601-4114079-u16aif.pdf": "Инструкция (скан)",
    "RackMultipart20260601-4124861-u72wwe.pdf": "Инструкция (скан, часть 2)",
    # Транслитные имена → человеческие.
    "Akt_otsutstvie_na_rab_meste.jpeg": "Акт об отсутствии на рабочем месте (образец)",
    "Chestnyy_znak.docx": "Честный знак",
    "Dogovor_materialnoy_otvetstvennosti.pdf": "Договор материальной ответственности",
    "Dokumenty_na_ugolok_potrebitelya.docx": "Документы на уголок потребителя",
    "Forma_Uvedomlenie_trebovanie_o_predstavlenii_rabotnikom_o.RTF.docx": (
        "Уведомление о представлении работником объяснений"
    ),
    "Gayd__kak_polzovatsya_otchyotami_dlya_P_L.pdf": "Гайд: как пользоваться отчётами для P&L",
    "Gayd_po_vydeleniyu_aktsiy.pdf": "Гайд по выделению акций",
    "Grafik_uborok_na_blank.docx": "График уборок (бланк)",
    "Grafik_uborok_obrazets_UPD.pdf": "График уборок (образец)",
    "Ingredienty_rashodniki.docx": "Ингредиенты и расходники",
    "Instruktsiya._Reklamnye_materialy_na_tochke_16.07-szhatyy_compressed.pdf": (
        "Рекламные материалы на точке"
    ),
    "Instruktsiya_Oplata_sertifikatami.pdf": "Оплата сертификатами",
    "Instruktsiya_dlya_sotrudnikov__kak_prinyat_sertifikat__elektronnyy_i_bumazhnyy___1_.docx": (
        "Как принять сертификат (электронный и бумажный)"
    ),
    "Instruktsiya_po_peremescheniyu_tovara.docx": "Инструкция по перемещению товара",
    "Instruktsiya_po_provedeniyu_polnoy_i_chastichnoy_inventarizatsii_na_torgovoy.docx": (
        "Проведение полной и частичной инвентаризации на торговой точке"
    ),
    "Instruktsiya_po_rabote_s_blyudami_na_predzakaz__1_.docx": "Работа с блюдами на предзаказ",
    "Instruktsiya_po_rabote_s_tabelem_UPPETIT.pdf": "Работа с табелем UPPETIT",
    "Instruktsiya_po_vygruzke_blanka_dlya_podachi_korrektirovki.docx": (
        "Выгрузка бланка для подачи корректировки"
    ),
    "Instruktsiya_spisanie.docx": "Инструкция: списание",
    "Kak_prinimat_oplatu_cherez_SBP.pdf": "Как принимать оплату через СБП",
    "Kak_vygruzit_i_skopirovat_postavku_iz_ayko.docx": (
        "Как выгрузить и скопировать поставку из iiko"
    ),
    "Karta_Napitkov_Uppetit.pdf": "Карта напитков UPPETIT",
    "Nakleyki_na_banki_Vesna_26_-_List1.pdf": "Наклейки на банки (весна 2026)",
    "Obrazets_zapolneniya_Shtatnogo_raspisaniya.pdf": "Образец заполнения штатного расписания",
    "Obyasnitelnaya_zapiska_primer.png": "Объяснительная записка (пример)",
    "Pamyatka_mobilnye.docx": "Памятка мобильным продавцам",
    "Pamyatka_po_organizatsii_obschepita_na_tochkah_seti.docx": (
        "Памятка по организации общепита на точках сети"
    ),
    "Polozhenie_ob_obrabotke_i_zaschite_personalnyh_dannyh_.pdf": (
        "Положение об обработке и защите персональных данных"
    ),
    "Prikaz_ob_utverzhdenii_Shtatnogo_raspisaniya.docx": (
        "Приказ об утверждении штатного расписания"
    ),
    "Pro_ohranu.pdf": "Про охрану",
    "Programma_Privedi_druga.pdf": "Программа «Приведи друга»",
    "Programma_Privedi_druga_dlya_franchayzi.pdf": "Программа «Приведи друга» для франчайзи",
    "Razgovor_o_mat.otvetstvennosti__3_.docx": "Разговор о материальной ответственности",
    "Razrabotka_dokumentov_po_pozharke_i_OT.pdf": (
        "Разработка документов по пожарной безопасности и охране труда"
    ),
    "Reglament_kolichestva_chelovek_v_smenu.pdf": "Регламент количества человек в смену",
    "Reglament_kolichestva_chelovek_v_smenu.xlsx": (
        "Регламент количества человек в смену (таблица)"
    ),
    "Sluzheb_zapiska_primer.webp": "Служебная записка (пример)",
    "Soglasie_na_obrabotku_PD.docx": "Согласие на обработку персональных данных",
    "TIPOVAYA_FORMA_DOGOVORA.pdf": "Типовая форма договора",
    "ZHURNAL_UCHETA_PROVEROK_blank.docx": "Журнал учёта проверок (бланк)",
    "Zakaz_formy_cherez_optikom.pdf": "Заказ формы через «Оптиком»",
    "Zayavlenie_na_ezhegodnyy_otpusk.pdf": "Заявление на ежегодный отпуск",
    "Zayavlenie_na_otpusk_za_svoy_schet.pdf": "Заявление на отпуск за свой счёт",
    "Zayavlenie_na_uvolnenie.pdf": "Заявление на увольнение",
    "Zayavlenie_o_prieme_na_rabotu.docx": "Заявление о приёме на работу",
    "Zhurnal_instruktazh_na_rabochem_meste_blank.docx": (
        "Журнал инструктажа на рабочем месте (бланк)"
    ),
    "nakleyka__rozovaya___2_.pdf": "Наклейка (розовая)",
    "photo_2024-06-18_13-47-39.jpg": "Фото-инструкция",
    "raskraski_dlya_detey.pdf": "Раскраски для детей",
    "-5_ студетам.docx": "Скидка −5% студентам",
    "Prilozhenie_3__novoe.docx": "Приложение № 3 к договору (направление на медосмотр)",
    "1Копия Инструкция по очистке кофемашины (1).pdf": "Инструкция по очистке кофемашины",
    "3_ЗАМОРОЗКА UPPETIT for all.xlsx": "Заморозка UPPETIT",
    "IceMama.xlsx": "IceMama: шаблон заказа",
    "RUSICHI_leto_26.xlsx": "Русичи: шаблон заказа (лето 2026)",
}

# Файлы, которые не переносим (байт-дубли и служебный мусор).
SKIP_FILES: set[str] = {
    "Programma_Privedi_druga_dlya_franchayzi (1).pdf",  # дубль
    "Пироговый дворик (1).xlsx",  # дубль
}

# Ключевые слова для раскладки файлов по разделам (по порядку проверки).
SECTION_RULES: list[tuple[str, tuple[str, ...]]] = [
    (
        "Заказы поставщикам",
        (
            "шаблон", "заказ", "поставщик", "prodstar", "rusichi", "русичи", "оптиком",
            "апкейк", "icemama", "джелато", "коржов", "некруглая", "ореховый",
            "пироговый", "раздолье", "денди", "базар", "лето-к", "криспи", "мега опт",
            "sweet life", "европекарь", "мазурин", "аркадия", "ривьера", "ретивых",
            "артемьев", "суперфрут", "волмолдом", "русхолтс", "копия тим", "реквизиты",
            "контакты поставщиков", "автозаказ",
        ),
    ),
    (
        "HR и кадровые документы",
        (
            "zayavlenie", "prikaz", "dogovor", "soglasie", "polozhenie", "shtatn",
            "trudov", "uvedomlenie", "akt_", "obyasnitelnaya", "sluzheb", "dolzhnost",
            "должностная", "персонал", "motivatsii", "otvetstvennosti", "sotrudnika",
            "shpargalka", "шпаргалка", "proshito", "lna", "otkaze", "primer",
        ),
    ),
    (
        "Оборудование и кофе",
        (
            "kofe", "кофе", "kofemash", "delta", "terruar", "yagoda", "latte", "латте",
            "espresso", "эспрессо", "ochistk", "очистк", "promyv", "оборудован",
            "monitor", "музык", "proga", "programma", "knopki", "unox",
        ),
    ),
    ("Планограммы", ("планограм", "выкладк", "мороженое 400")),
    (
        "ТТК, КБЖУ и сроки",
        ("ттк", "кбжу", "срок", "заморозк", "полуфабрикат", "дефростация", "моти", "меню"),
    ),
    ("Журналы", ("zhurnal", "журнал")),
    ("Чек-листы", ("chek", "чек-лист", "чек лист", "chl_", "оценка и отпуск")),
]

# ─── Ассортимент ────────────────────────────────────────────────────────────
# «путь к подкатегории» → название категории в Hub (последний сегмент пути,
# кроме напитков — там сегмент осмысленный сам по себе).
MENU_CATEGORY_BY_PATH: dict[str, str] = {
    "Напитки/Кофе": "Кофе",
    "Напитки/Сезонное меню": "Сезонные напитки",
    "Напитки/Чай": "Чай",
    "Напитки/Авторский чай": "Авторский чай",
    "Напитки/Не кофе": "Не кофе",
    "Напитки/Добавки": "Добавки к напиткам",
    "Супы": "Супы",
    "Салаты": "Салаты",
    "Завтраки": "Завтраки",
    "Сэндвичи": "Сэндвичи",
    "Япония": "Япония",
    "Десерты": "Десерты",
    "Горячие блюда": "Горячие блюда",
}

# ─── Видео ──────────────────────────────────────────────────────────────────
# Уроки, где видео было залито в ServiceGuru: presigned-ссылки протухли через
# 10 минут после выгрузки. Импортируем урок с пометкой, файлы добавятся позже.
LOST_VIDEO_NOTE = "📹 Видео будет добавлено позже"

# YouTube-ролики: их скачиваем и хостим у себя (CSP запрещает встраивание).
YOUTUBE_TITLES: dict[str, str] = {
    "kI-tmvKmG8c": "Показатели в магазине: часть 1",
    "OGKfEN6xvsM": "Показатели в магазине: часть 2",
    "bETPx2sIQsI": "Показатели в магазине: часть 3",
    "ucm3A8Z7wK4": "Маркетинг в UPPETIT",
    "saZkY0sArfA": "Управление финансами",
    "Tfgp_4CTUKM": "Печать ценников",
}


def full_title(sheet_title: str) -> str:
    """Полное название листа (или само название, если не обрезано)."""
    return FULL_TITLES.get(sheet_title, sheet_title)


def section_for_file(filename: str) -> str:
    """Раздел библиотеки по имени файла (fallback — «Прочее»)."""
    name = filename.lower()
    title = FILE_TITLES.get(filename, "").lower()
    haystack = f"{name} {title}"
    for section, keywords in SECTION_RULES:
        if any(k in haystack for k in keywords):
            return section
    return "Прочее"


def file_title(filename: str) -> str:
    """Человеческое название материала библиотеки."""
    if filename in FILE_TITLES:
        return FILE_TITLES[filename]
    stem = filename.rsplit(".", 1)[0]
    stem = stem.replace("_", " ").replace("__", " ").strip()
    return stem[:255] or filename
