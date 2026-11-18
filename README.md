# Keitaro Wrapper

Обёртка над Admin API рекламного трекера [Keitaro](https://keitaro.io): **создаватор кампаний** и **редактор офферов** в существующей кампании.

Стек: **FastAPI + SQLAlchemy 2 + Alembic**, фронт — одна HTML-страница на ванильном JS (без сборки), раздаётся тем же FastAPI.

## Что умеет

### 1. Создаватор кампаний (`/`)
Принимает **название**, **гео** (один или несколько ISO-кодов: `MX, AU, RO`) и **оффер** (поиск с автокомплитом по названию или ID). Создаёт кампанию в Keitaro:

| | Поток | Логика |
|---|---|---|
| 1 | `Geo AU, MX → Google` | фильтр `country` = указанные страны → редирект на `https://google.com` |
| 2 | `Offers` | схема «Лендинги и офферы» → выбранный оффер, доля 100% |

- Домен, группа и источник проставляются из настроек (`kylovoa.com`, группа `FORTESTS`, источник `FORTESTS`).
- К названию автоматически добавляется префикс `test_allamurotov_`.
- `alias` генерируется (Keitaro требует его).
- Если создание второго потока упало, наполовину созданная кампания удаляется (без мусора в трекере).
- Созданная кампания сохраняется в локальной БД.

### 2. Редактор кампании (`/campaigns/{id}`)
- Список кампаний: «мои» (с префиксом или созданные здесь) или все доступные ключу; есть поиск.
- Потоки показаны как в Keitaro: фильтры, цель, офферы и статистика **Клики / Уник. / Боты / Конв.** за выбранный период (сегодня, вчера, 7 дней, 30 дней, всё время). Статистика берётся у Keitaro через `POST /report/build` в разрезе `stream_id` и `stream_id × offer_id`.
- **Добавить оффер**: автокомплит; после добавления доли выравниваются поровну (2 → 50/50, 3 → 34/33/33).
- **Удалить оффер** (×): доли оставшихся выравниваются. Последний оффер удалить нельзя, иначе поток остался бы без цели.
- **Ручные доли**: поле % у каждого оффера, кнопка «Поровну», «Сохранить» активна, только если сумма равна 100%.
- Перед каждым изменением поток перечитывается из Keitaro, так что правки, сделанные в самой админке, не затираются.
- Каждое изменение пишется в таблицу `offer_events` и показывается в «Истории изменений».

## Запуск

Нужен Python 3.11+.

```bash
git clone https://github.com/fed1k/keitaro-wrapper.git && cd keitaro-wrapper
python -m venv .venv
# Windows: .venv\Scripts\activate    |  macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env          # Windows: copy .env.example .env
# впишите KEITARO_API_KEY (админка Keitaro → Профиль → API ключи)

alembic upgrade head          # миграции (по умолчанию SQLite-файл keitaro_wrapper.db)
uvicorn app.main:app --reload --port 8000
```

Откройте http://localhost:8000. Swagger со всеми эндпоинтами: http://localhost:8000/docs.

### Миграции
- Применить: `alembic upgrade head`
- Откатить: `alembic downgrade -1`
- Новая миграция после изменения `app/models.py`: `alembic revision --autogenerate -m "описание"`

БД задаётся через `DATABASE_URL`. По умолчанию SQLite; для Postgres поставьте драйвер (`pip install psycopg[binary]`) и укажите `postgresql+psycopg://user:pass@host/db`.

### Тесты
```bash
pytest -q
```
Тесты гоняют API на фейковом Keitaro в памяти: создание кампании и её структура, валидация гео и оффера, откат при ошибке, добавление, удаление и перевзвешивание офферов, агрегация статистики, математика долей.

## Настройки (`.env`)

| Переменная | По умолчанию | Что это |
|---|---|---|
| `KEITARO_URL` | `https://tlgk.host` | адрес трекера |
| `KEITARO_API_KEY` | — | ключ Admin API |
| `KEITARO_DOMAIN_ID` | `1813` | домен кампаний (kylovoa.com) |
| `KEITARO_GROUP_ID` | `10332` | группа FORTESTS |
| `KEITARO_TRAFFIC_SOURCE_ID` | `836` | источник FORTESTS |
| `CAMPAIGN_PREFIX` | `test_allamurotov_` | префикс названий |
| `GOOGLE_URL` | `https://google.com` | цель первого потока |
| `REPORT_TIMEZONE` | `Europe/Moscow` | таймзона отчётов |
| `DATABASE_URL` | `sqlite:///./keitaro_wrapper.db` | БД |

## API

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/meta` | префикс, дефолты, список стран |
| GET | `/api/offers?q=` | поиск офферов (кэш 60 с) |
| POST | `/api/campaigns` | `{name, geo: ["AU"] \| "AU,MX", offer_id}` — создать кампанию |
| GET | `/api/campaigns?scope=mine\|all&q=` | список кампаний |
| GET | `/api/campaigns/{id}?interval=today` | потоки, офферы, доли, статистика |
| POST | `/api/campaigns/{id}/streams/{sid}/offers` | `{offer_id}` — добавить оффер |
| DELETE | `/api/campaigns/{id}/streams/{sid}/offers/{offer_id}` | удалить оффер |
| PUT | `/api/campaigns/{id}/streams/{sid}/shares` | `{shares: {offer_id: %}}`, сумма 100 |
| GET | `/api/campaigns/{id}/events` | история изменений |

## Структура

```
app/
  main.py        роуты FastAPI + раздача фронта
  services.py    бизнес-логика: создание кампании, редактор, сборка статистики
  keitaro.py     клиент Keitaro Admin API (httpx)
  shares.py      распределение долей (целые, сумма 100)
  models.py      SQLAlchemy: campaigns, offer_events
  schemas.py     Pydantic-схемы и валидация (гео, доли)
  countries.py   ISO-коды стран
alembic/         миграции
static/          фронт (index.html, app.js, style.css)
tests/           pytest
```

## Ограничения тестового окружения
- Тестовому пользователю Keitaro доступен **один оффер** (18813), поэтому добавление второго оффера вживую не проверить. Логика с несколькими офферами покрыта тестами.
- Домен `kylovoa.com` сейчас не резолвится в DNS, поэтому реальные клики по ссылке кампании сделать нельзя. Статистика читается из тех же отчётов Keitaro, формат проверен на кампаниях с кликами.
