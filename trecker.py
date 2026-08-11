
"""
Telegram-бот "Трекер целей" (aiogram 3.x)
==========================================
Логика:
  08:00 — бот спрашивает планы/цели на день, пользователь присылает список
  12:00 — напоминание о невыполненных целях + мотивация
  16:00 — напоминание о невыполненных целях + совет по достижению
  20:00 — запрос отчёта: инлайн-кнопки для отметки "достигнуто/не достигнуто"
          -> после подтверждения бот присылает итог дня и советы по недостигнутым целям
 
Хранилище: SQLite (файл tracker.db, создаётся автоматически).
Планировщик: APScheduler (AsyncIOScheduler, cron-триггеры).
 
Установка зависимостей:
    pip install aiogram==3.* APScheduler
 
Запуск:
    export BOT_TOKEN=xxxxx:yyyyy   # или впишите токен в TOKEN ниже
    python tracker_bot.py
"""
 
import asyncio
import logging
import os
import random
import sqlite3
from datetime import date, datetime
 
from aiogram import Bot, Dispatcher, F, Router
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger


 
# ────────────────────────────── КОНФИГ ──────────────────────────────
 
# ВАЖНО: не храните токен прямо в коде — если он утёк (например, попал
# в чат, скриншот, публичный репозиторий), сразу же отзовите его через
# @BotFather -> /mybots -> ваш бот -> Bot Settings -> Revoke token.
TOKEN = "8882958690:AAFtueXs5cwKAecLmVJi354yrc4404TBK4A"
if not TOKEN:
    raise RuntimeError(
        "Не задан BOT_TOKEN. Установите переменную окружения: "
        "export BOT_TOKEN=xxxxx:yyyyy"
    )
 
# Если провайдер блокирует Telegram — задайте SOCKS5/HTTP-прокси через env.
# Пример: export BOT_PROXY=socks5://127.0.0.1:10808
PROXY_URL = proxy="socks5://127.0.0.1:10808"
 
DB_PATH = "tracker.db"
 
# Время четырёх ежедневных сообщений (час, минута) — поменяйте под себя
TIME_PLAN = (8, 0)        # утреннее планирование
TIME_MIDDAY = (12, 0)     # напоминание №1 + мотивация
TIME_AFTERNOON = (16, 0)  # напоминание №2 + совет
TIME_REPORT = (20, 0)     # вечерний отчёт
 
logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tracker_bot")
 
# Единственное место создания bot/dp/router/scheduler — на уровне модуля.
# Именно поэтому раньше "зачёркивало": вы пересоздавали bot/dp внутри
# main(), а хендлеры ниже продолжали ссылаться на несуществующие глобальные
# имена, и вторая async def main() затирала первую (с прокси).
_session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
bot = Bot(token=TOKEN, session=_session)
dp = Dispatcher(storage=MemoryStorage())
router = Router()
dp.include_router(router)
 
scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
 
# ────────────────────────────── БАЗА ДАННЫХ ──────────────────────────────
 
 
def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
 
 
def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS goals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                goal_date TEXT NOT NULL,
                text TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending'  -- pending | done | failed
            )"""
        )
        conn.commit()
 
 
def add_user(user_id: int, username: str | None) -> None:
    with db_connect() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)",
            (user_id, username or ""),
        )
        conn.commit()
 
 
def get_all_user_ids() -> list[int]:
    with db_connect() as conn:
        rows = conn.execute("SELECT user_id FROM users").fetchall()
        return [r["user_id"] for r in rows]
 
 
def save_goals(user_id: int, goals: list[str]) -> None:
    today = date.today().isoformat()
    with db_connect() as conn:
        # если пользователь перепланировал день — старые цели этого дня удаляем
        conn.execute(
            "DELETE FROM goals WHERE user_id=? AND goal_date=?", (user_id, today)
        )
        conn.executemany(
            "INSERT INTO goals (user_id, goal_date, text, status) VALUES (?,?,?, 'pending')",
            [(user_id, today, g) for g in goals],
        )
        conn.commit()
 
 
def get_today_goals(user_id: int) -> list[sqlite3.Row]:
    today = date.today().isoformat()
    with db_connect() as conn:
        return conn.execute(
            "SELECT * FROM goals WHERE user_id=? AND goal_date=? ORDER BY id",
            (user_id, today),
        ).fetchall()
 
 
def set_goal_status(goal_id: int, status: str) -> None:
    with db_connect() as conn:
        conn.execute("UPDATE goals SET status=? WHERE id=?", (status, goal_id))
        conn.commit()

def delete_goal(goal_id: int) -> None:
    with db_connect() as conn:
        conn.execute("DELETE FROM goals WHERE id=?", (goal_id,))
        conn.commit()        
 
 
# ────────────────────────────── КОНТЕНТ ──────────────────────────────
 
MOTIVATION_QUOTES = [
    "Маленькие шаги каждый день приводят к большим результатам. Ты уже в пути!",
    "Не обязательно быть идеальным — обязательно быть последовательным.",
    "Половина дня прошла — самое время свериться с целями и сделать рывок.",
    "Дисциплина сегодня — это свобода завтра. Продолжай двигаться.",
    "Ты сам выбрал эти цели утром — значит, они важны. Не бросай на полпути.",
]
 
ADVICE_TIPS = [
    "Разбей оставшуюся цель на 1-2 маленьких подшага — так проще начать.",
    "Убери телефон и уведомления на 25 минут — используй технику Помодоро.",
    "Спроси себя: что мешает прямо сейчас? Устрани это одно препятствие.",
    "Если цель буксует — сократи её масштаб, но не откладывай на завтра.",
    "Сделай хотя бы 10% от цели прямо сейчас — импульс важнее совершенства.",
]
 
FAIL_ADVICE = [
    "Проанализируй, что помешало, и заложи на это время завтра.",
    "Попробуй разбить эту цель на более мелкие и конкретные шаги.",
    "Возможно, цель была слишком амбициозной для одного дня — раздели её.",
    "Запланируй эту цель на завтра первым пунктом, пока есть энергия с утра.",
]
 
 
def goals_list_text(goals: list[sqlite3.Row]) -> str:
    if not goals:
        return "На сегодня цели ещё не запланированы. Используй /plan."
    icon = {"pending": "🔲", "done": "✅", "failed": "❌"}
    return "\n".join(f"{icon[g['status']]} {g['text']}" for g in goals)
 
 
# ────────────────────────────── FSM ──────────────────────────────
 
 
class PlanGoals(StatesGroup):
    waiting_for_goals = State()
 
 
# ────────────────────────────── ХЕНДЛЕРЫ ──────────────────────────────
 
 
@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    add_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "Привет! Я бот-трекер целей 🎯\n\n"
        f"Каждый день в {TIME_PLAN[0]:02d}:{TIME_PLAN[1]:02d} я спрошу твои планы на день.\n"
        f"В {TIME_MIDDAY[0]:02d}:{TIME_MIDDAY[1]:02d} и {TIME_AFTERNOON[0]:02d}:{TIME_AFTERNOON[1]:02d} "
        "буду напоминать о них и мотивировать.\n"
        f"В {TIME_REPORT[0]:02d}:{TIME_REPORT[1]:02d} — подведём итоги дня.\n\n"
        "Команды:\n"
        "/plan — запланировать цели на сегодня прямо сейчас\n"
        "/today — посмотреть текущие цели и статусы\n"
        "/report — отчитаться о выполнении досрочно"
    )
 
 
@router.message(Command("plan"))
async def cmd_plan(message: Message, state: FSMContext) -> None:
    await state.set_state(PlanGoals.waiting_for_goals)
    await message.answer(
        "Напиши свои цели на сегодня — каждую с новой строки.\n"
        "Например:\n<i>Сделать отчёт\nПробежать 5 км\nПрочитать 20 страниц</i>",
        parse_mode="HTML",
    )
 
 
@router.message(PlanGoals.waiting_for_goals, F.text)
async def process_goals(message: Message, state: FSMContext) -> None:
    goals = [line.strip() for line in message.text.splitlines() if line.strip()]
    if not goals:
        await message.answer("Не вижу целей, попробуй ещё раз — каждую с новой строки.")
        return
    save_goals(message.from_user.id, goals)
    await state.clear()
    await message.answer(
        "Цели на сегодня зафиксированы ✅\n\n"
        + goals_list_text(get_today_goals(message.from_user.id))
        + "\n\nБуду напоминать о них в течение дня. Удачи!"
    )
 
 
@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    goals = get_today_goals(message.from_user.id)
    await message.answer("Твои цели на сегодня:\n\n" + goals_list_text(goals))


# ── удаление целей ──


def build_remove_keyboard(goals: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    icon = {"pending": "🔲", "done": "✅", "failed": "❌"}
    for g in goals:
        builder.button(
            text=f"🗑 {icon[g['status']]} {g['text']}",
            callback_data=f"remove:{g['id']}",
        )
    builder.button(text="Закрыть", callback_data="remove:close")
    builder.adjust(1)
    return builder.as_markup()


@router.message(Command("remove"))
async def cmd_remove(message: Message) -> None:
    goals = get_today_goals(message.from_user.id)
    if not goals:
        await message.answer("На сегодня целей нет — нечего удалять.")
        return
    await message.answer(
        "Нажми на цель, которую нужно убрать из списка:",
        reply_markup=build_remove_keyboard(goals),
    )


@router.callback_query(F.data.startswith("remove:"))
async def cb_remove_goal(callback: CallbackQuery) -> None:
    payload = callback.data.split(":")[1]

    if payload == "close":
        await callback.message.edit_text("Ок, ничего не меняю.")
        await callback.answer()
        return

    goal_id = int(payload)
    with db_connect() as conn:
        row = conn.execute(
            "SELECT text FROM goals WHERE id=?", (goal_id,)
        ).fetchone()
    if row is None:
        await callback.answer("Цель уже удалена")
        return

    delete_goal(goal_id)
    goals = get_today_goals(callback.from_user.id)

    if goals:
        await callback.message.edit_text(
            f"Убрал: «{row['text']}» ✅\n\nОставшиеся цели — нажми, чтобы убрать ещё:",
            reply_markup=build_remove_keyboard(goals),
        )
    else:
        await callback.message.edit_text(
            f"Убрал: «{row['text']}» ✅\n\nЦелей на сегодня больше нет."
        )
    await callback.answer()    
 
 
@router.message(Command("report"))
async def cmd_report(message: Message) -> None:
    await send_evening_report(message.from_user.id)
 
 
# ── обработка инлайн-кнопок отчёта ──
 
 
def build_report_keyboard(goals: list[sqlite3.Row]) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    icon = {"pending": "🔲", "done": "✅", "failed": "❌"}
    for g in goals:
        builder.button(
            text=f"{icon[g['status']]} {g['text']}", callback_data=f"toggle:{g['id']}"
        )
    builder.button(text="Готово ✔️", callback_data="report:finish")
    builder.adjust(1)
    return builder.as_markup()
 
 
@router.callback_query(F.data.startswith("toggle:"))
async def cb_toggle_goal(callback: CallbackQuery) -> None:
    goal_id = int(callback.data.split(":")[1])
    with db_connect() as conn:
        row = conn.execute("SELECT status FROM goals WHERE id=?", (goal_id,)).fetchone()
    if row is None:
        await callback.answer("Цель не найдена")
        return
    order = {"pending": "done", "done": "failed", "failed": "pending"}
    set_goal_status(goal_id, order[row["status"]])
    goals = get_today_goals(callback.from_user.id)
    await callback.message.edit_reply_markup(reply_markup=build_report_keyboard(goals))
    await callback.answer()
 
 
@router.callback_query(F.data == "report:finish")
async def cb_finish_report(callback: CallbackQuery) -> None:
    await callback.message.edit_text("Итоги дня зафиксированы, спасибо! 👇")
    await send_summary(callback.from_user.id)
    await callback.answer()
 
 
# ────────────────────────────── РАССЫЛКИ (4 РАЗА В ДЕНЬ) ──────────────────────────────
 
 
async def send_morning_plan_request() -> None:
    for user_id in get_all_user_ids():
        try:
            await bot.send_message(
                user_id,
                "Доброе утро! ☀️ Какие цели у тебя на сегодня?\n"
                "Напиши каждую с новой строки (или используй /plan).",
            )
        except Exception as e:
            log.warning("Не удалось отправить %s: %s", user_id, e)
 
 
async def send_checkin(advice_pool: list[str]) -> None:
    for user_id in get_all_user_ids():
        goals = get_today_goals(user_id)
        pending = [g for g in goals if g["status"] == "pending"]
        if not goals:
            continue
        text = (
            f"💡 {random.choice(MOTIVATION_QUOTES)}\n\n"
            f"Совет: {random.choice(advice_pool)}\n\n"
            "Текущие цели:\n" + goals_list_text(goals)
        )
        if not pending:
            text += "\n\nПохоже, ты уже со всем разобрался — красавчик! 🔥"
        try:
            await bot.send_message(user_id, text)
        except Exception as e:
            log.warning("Не удалось отправить %s: %s", user_id, e)
 
 
async def send_evening_report(user_id: int) -> None:
    goals = get_today_goals(user_id)
    if not goals:
        await bot.send_message(user_id, "Сегодня цели не были запланированы 🤷")
        return
    await bot.send_message(
        user_id,
        "Пора подвести итоги дня! Отметь статус каждой цели (нажимай, чтобы переключить):",
        reply_markup=build_report_keyboard(goals),
    )
 
 
async def send_report_requests() -> None:
    for user_id in get_all_user_ids():
        await send_evening_report(user_id)
 
 
async def send_summary(user_id: int) -> None:
    goals = get_today_goals(user_id)
    done = [g for g in goals if g["status"] == "done"]
    failed = [g for g in goals if g["status"] == "failed"]
    pending = [g for g in goals if g["status"] == "pending"]
 
    lines = [f"📊 Итоги дня — {date.today().strftime('%d.%m.%Y')}\n"]
    lines.append(f"Достигнуто: {len(done)}/{len(goals)}")
    for g in done:
        lines.append(f"  ✅ {g['text']}")
 
    if failed:
        lines.append("\nНе достигнуто:")
        for g in failed:
            lines.append(f"  ❌ {g['text']} — {random.choice(FAIL_ADVICE)}")
 
    if pending:
        lines.append("\nОсталось без отметки:")
        for g in pending:
            lines.append(f"  🔲 {g['text']}")
 
    if len(done) == len(goals) and goals:
        lines.append("\nВсе цели дня достигнуты! Отличная работа 🏆")
    elif done:
        lines.append("\nНеплохой день — продолжай в том же духе завтра 💪")
    else:
        lines.append("\nЗавтра новый день и новый шанс. Начни с самой простой цели 🙂")
 
    await bot.send_message(user_id, "\n".join(lines))
 
 
# # ────────────────────────────── ПЛАНИРОВЩИК ──────────────────────────────

 
def setup_scheduler() -> None:
    scheduler.add_job(
        send_morning_plan_request,
        CronTrigger(hour=TIME_PLAN[0], minute=TIME_PLAN[1]),
    )
    scheduler.add_job(
        send_checkin,
        CronTrigger(hour=TIME_MIDDAY[0], minute=TIME_MIDDAY[1]),
        args=[MOTIVATION_QUOTES],
    )
    scheduler.add_job(
        send_checkin,
        CronTrigger(hour=TIME_AFTERNOON[0], minute=TIME_AFTERNOON[1]),
        args=[ADVICE_TIPS],
    )
    scheduler.add_job(
        send_report_requests,
        CronTrigger(hour=TIME_REPORT[0], minute=TIME_REPORT[1]),
    )
    scheduler.start()
 
# ────────────────────────────── ENTRYPOINT ──────────────────────────────
 
 
async def main() -> None:
    init_db()
    setup_scheduler()
    await dp.start_polling(bot)
 
 
if __name__ == "__main__":
    print('Bot started')
    asyncio.run(main())
 