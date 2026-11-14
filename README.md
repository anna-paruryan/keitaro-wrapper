# Keitaro wrapper

Веб-приложение поверх трекера [Keitaro](https://keitaro.io), работает через его Admin API. Тестовое задание «Обёртка над Keitaro».

* **Создание кампании.** Название, гео и оффер (поиск с автодополнением). В Keitaro появляется кампания с двумя потоками: посетители из указанных стран уходят на Google, все остальные идут на выбранный оффер.
* **Редактор кампании.** Показывает потоки и офферы с долями. Оффер можно добавить, убрать, вернуть и закрепить долю (Pin). Правки копятся в черновике и уходят в Keitaro по кнопке **Push to KT**. Доли всегда дают ровно 100%.
  Названия кампаний получают префикс `test_paruryan_`, и редактор правит только кампании с этим префиксом.

**Стек:** FastAPI, SQLAlchemy 2, Alembic, SQLite (или PostgreSQL), React + TypeScript + Vite.

## Запуск

Нужны Python 3.10+, Node.js 20.19+ (или 22.12+) и [pnpm](https://pnpm.io).

### 1. Бэкенд и миграции

```bash
cd backend
 
python -m venv .venv
source .venv/bin/activate              # Windows: .venv\Scripts\activate
pip install -r requirements.txt
 
cp .env.example .env                   # Windows: copy .env.example .env
# открой .env и впиши KEITARO_API_KEY
 
alembic upgrade head                   # миграции: создаёт таблицы в БД
uvicorn app.main:app --reload          # http://127.0.0.1:8000
```

Описание всех методов API (Swagger): <http://127.0.0.1:8000/docs>.

Ключ Admin API берётся в админке Keitaro: Профиль → API ключи → Создать новый ключ.

### 2. Фронтенд

В другом терминале:

```bash
cd client
pnpm install
pnpm dev                               # http://localhost:5173
```

Открой <http://localhost:5173>. Запросы на `/api` Vite пересылает на бэкенд, поэтому бэкенд должен быть запущен.

## Настройки (`backend/.env`)

Образец со всеми переменными и комментариями лежит в `backend/.env.example`. Главные:

| Переменная | Описание |
|---|---|
| `KEITARO_URL` | адрес трекера, например `https://tlgk.host` |
| `KEITARO_API_KEY` | ключ Admin API |
| `CAMPAIGN_PREFIX` | префикс названий, у нас `test_paruryan_` (добавляется автоматически) |
| `DATABASE_URL` | по умолчанию `sqlite:///./data/app.db` |

Файл `.env` с ключом в репозиторий не попадает (он в `.gitignore`).

## Миграции

Схемой базы управляет Alembic. Команды выполняются в `backend/`:

```bash
alembic upgrade head                              # применить все миграции
alembic downgrade -1                              # откатить последнюю
alembic revision --autogenerate -m "описание"     # новая миграция после правки app/models.py
alembic current                                   # текущая версия схемы
```

Таблицы: `campaigns` (история созданных кампаний), `streams` и `stream_offers` (черновики редактора), `offer_changes` (журнал Push). SQLite-файл создаётся сам. Для PostgreSQL:

```bash
pip install "psycopg[binary]"
# в backend/.env:
# DATABASE_URL=postgresql+psycopg://user:password@localhost:5432/keitaro_tools
alembic upgrade head
```

## Тесты

```bash
cd backend
pip install -r requirements-dev.txt
pytest
```

89 тестов, доступ к Keitaro не нужен: он заменён эмулятором. Покрыты создание кампании, весь редактор, расчёт долей и применение миграций с нуля.

## Как пользоваться

1. **Create campaign:** введи название, гео (`MX,AU,RO`), выбери оффер **из выпадающего списка** и нажми Create.
2. **Editor:** выбери кампанию в списке My campaigns или введи её ID и нажми **Fetch Streams**.
3. Меняй офферы в карточке потока. Жёлтая карточка (`Unpublished`) значит, что в Keitaro правки ещё не отправлены.
4. **Push to KT** отправляет поток в Keitaro, **Cancel** отбрасывает неопубликованные правки.
   Подробно о логике редактора, пересчёте долей, защитах и о том, что проверено вручную: [docs/editor-logic.md](docs/editor-logic.md).

## Ограничения

* Ключ, с которым разрабатывалось приложение, не видит домен `in.posdk.xyz`, источник и группу `FORTESTS` (в API их нет). Форма показывает то, что отдаёт API; если объекты появятся, они выберутся автоматически по настройкам `KEITARO_*`.
* У API нет авторизации: он рассчитан на локальный запуск. Выкладывать бэкенд в открытый интернет без логина нельзя, иначе любой сможет действовать от имени ключа.
* Название кампании нельзя использовать повторно, даже после удаления кампании (так устроен архив Keitaro).
## Структура репозитория

```
backend/
  app/            код приложения (api, services, editor, keitaro, shares, models)
  migrations/     Alembic
  scripts/        check_keitaro.py: проверка доступа к трекеру (только чтение)
  tests/
client/
  src/            React: pages, components, api, index.css
docs/             детали логики редактора
```

Проект сделан с помощью AI-агента (Claude), что допускается условием задания.