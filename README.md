# Keitaro Wrapper

Веб-приложение поверх трекера Keitaro: создаёт кампании и редактирует доли трафика между офферами через Admin API.
Тестовое задание «Обёртка над Keitaro».
Видео:https://drive.google.com/file/d/1FA8VCEJNH0HattojM8Re6bJv1zJX8oTu/view?usp=sharing
**Стек:** FastAPI · SQLAlchemy 2 · Alembic · SQLite / PostgreSQL · React · TypeScript · Vite

## Что умеет

### Создание кампании

Название, гео и оффер (поиск с автодополнением). В Keitaro появляется кампания с двумя потоками:

- посетители из указанных стран уходят на Google;
- все остальные идут на выбранный оффер.

### Редактор кампании

Показывает потоки и офферы с долями трафика.

- Оффер можно **добавить**, **убрать**, **вернуть** и **закрепить** долю (Pin).
- Правки копятся в черновике и уходят в Keitaro кнопкой **Push to KT**. **Cancel** отбрасывает их.
- Доли всегда дают ровно 100%.

Названия кампаний получают префикс `test_paruryan_`, и редактор правит только кампании с этим префиксом.

Подробно о логике редактора, пересчёте долей и защитах: [docs/editor-logic.md](docs/editor-logic.md).

## Быстрый старт

Нужны Python 3.10+, Node.js 20.19+ (или 22.12+) и pnpm.

### 1. Бэкенд

```bash
cd backend
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # Windows: copy .env.example .env
```

Открой `backend/.env` и впиши `KEITARO_API_KEY`.
Ключ берётся в админке Keitaro: **Профиль → API ключи → Создать новый ключ**.

```bash
alembic upgrade head               # миграции: создаёт таблицы в БД
uvicorn app.main:app --reload      # http://127.0.0.1:8000
```

Описание всех методов API (Swagger): http://127.0.0.1:8000/docs

### 2. Фронтенд

В другом терминале:

```bash
cd client
pnpm install
pnpm dev                           # http://localhost:5173
```

Запросы на `/api` Vite пересылает на бэкенд, поэтому бэкенд должен быть запущен.

## Настройки

Файл `backend/.env`. Образец со всеми переменными лежит в `backend/.env.example`. Сам `.env` с ключом в репозиторий не попадает.

| Переменная | Описание | Пример |
|---|---|---|
| `KEITARO_URL` | адрес трекера | `https://tlgk.host` |
| `KEITARO_API_KEY` | ключ Admin API | впиши свой ключ |
| `CAMPAIGN_PREFIX` | префикс названий кампаний | `test_paruryan_` |
| `DATABASE_URL` | база данных | `sqlite:///./data/app.db` |

## Миграции

Схемой базы управляет Alembic. Команды выполняются в папке `backend/`:

```bash
alembic upgrade head                               # применить все миграции
alembic downgrade -1                               # откатить последнюю
alembic revision --autogenerate -m "описание"      # новая миграция после правки app/models.py
alembic current                                    # текущая версия схемы
```

Таблицы: `campaigns` (история созданных кампаний), `streams` и `stream_offers` (черновики редактора), `offer_changes` (журнал Push).

<details>
<summary>Как перейти на PostgreSQL</summary>

```bash
pip install "psycopg[binary]"
```

В `backend/.env`:

```env
DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/keitaro_tools
```

```bash
alembic upgrade head
```

</details>

## Тесты

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

89 тестов. Доступ к Keitaro не нужен: он заменён эмулятором. Покрыты создание кампании, весь редактор, расчёт долей и применение миграций с нуля.

## Как пользоваться

1. **Create campaign:** введи название, гео (например `MX,AU,RO`), выбери оффер из списка и нажми **Create**.
2. **Editor:** выбери кампанию в списке *My campaigns* или введи её ID и нажми **Fetch Streams**.
3. Меняй офферы в карточке потока. Жёлтая карточка (*Unpublished*) значит, что правки ещё не отправлены в Keitaro.
4. **Push to KT** отправляет поток в Keitaro, **Cancel** отбрасывает неопубликованные правки.

## Сверх задания

- Адаптивная вёрстка: интерфейс работает и на телефоне, и на десктопе (mobile-first).
- Все цвета и стили собраны в одном месте: `client/src/index.css`.
- Черновики хранятся в базе, поэтому после обновления страницы состояние не теряется.
- Понятные сообщения об ошибках вместо технических.
- Журнал Push в API.

## Ограничения

- Ключ, с которым разрабатывалось приложение, не видит домен `in.posdk.xyz`, источник и группу `FORTESTS` (в API их нет). Форма показывает то, что отдаёт API. Если объекты появятся, они выберутся автоматически по настройкам `KEITARO_*`.
- У API нет авторизации: он рассчитан на локальный запуск. Выкладывать бэкенд в открытый интернет без логина нельзя, иначе любой сможет действовать от имени ключа.
- Название кампании нельзя использовать повторно, даже после удаления кампании (так устроен архив Keitaro).

## Структура репозитория

```text
backend/
  app/          код приложения (api, services, editor, keitaro, shares, models)
  migrations/   Alembic
  scripts/      check_keitaro.py: проверка доступа к трекеру (только чтение)
  tests/
client/
  src/          React: pages, components, api, index.css
docs/           детали логики редактора
```

---

Проект сделан с помощью AI-агента (Claude), что допускается условием задания.