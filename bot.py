#!/usr/bin/env python3
import asyncio
import os
import sqlite3
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command, StateFilter
from aiogram.types import Message, CallbackQuery, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from knowledge_base import init_faq_table, search_faq, add_faq, get_all_faq, delete_faq, fill_default_faq

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = [int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()]

CHANNELS = {
    "mama_dychi": "https://t.me/mama_dychi",
    "detky_nazametky": "https://t.me/detky_nazametky"
}

DB_NAME = "database.db"

# ========== БАЗОВАЯ ТАБЛИЦА ПОЛЬЗОВАТЕЛЕЙ И ВОПРОСОВ ==========
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            full_name TEXT,
            registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS questions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question_text TEXT NOT NULL,
            answer_text TEXT DEFAULT '',
            asked_by INTEGER,
            answered_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            answered_at TIMESTAMP,
            added_to_faq BOOLEAN DEFAULT 0
        )
    """)
    conn.commit()
    conn.close()

def get_user(user_id, username, full_name):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users WHERE user_id = ?", (user_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (user_id, username, full_name) VALUES (?, ?, ?)",
                    (user_id, username, full_name))
        conn.commit()
    conn.close()

def save_question(user_id, text):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO questions (question_text, asked_by) VALUES (?, ?)", (text, user_id))
    conn.commit()
    q_id = cur.lastrowid
    conn.close()
    return q_id

def get_unanswered_questions():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, question_text, asked_by FROM questions WHERE answer_text = ''")
    rows = cur.fetchall()
    conn.close()
    return rows

def answer_question(q_id, answer_text, admin_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE questions SET answer_text = ?, answered_by = ?, answered_at = ? WHERE id = ?",
                (answer_text, admin_id, datetime.now(), q_id))
    conn.commit()
    cur.execute("SELECT asked_by FROM questions WHERE id = ?", (q_id,))
    user_id = cur.fetchone()[0]
    conn.close()
    return user_id

def mark_added_to_faq(q_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("UPDATE questions SET added_to_faq = 1 WHERE id = ?", (q_id,))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    users = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM questions")
    total_q = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM questions WHERE answer_text != ''")
    answered_q = cur.fetchone()[0]
    conn.close()
    return users, total_q, answered_q

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_user_info(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT username, full_name FROM users WHERE user_id = ?", (user_id,))
    result = cur.fetchone()
    conn.close()
    if result:
        username, full_name = result
        mention = f"@{username}" if username else f"[{full_name}](tg://user?id={user_id})"
        return {"full_name": full_name or "Не указано", "username": username, "mention": mention}
    return {"full_name": "Пользователь", "username": None, "mention": f"[Пользователь](tg://user?id={user_id})"}

# ========== КЛАВИАТУРЫ ==========
def get_main_keyboard(user_id):
    buttons = [
        [KeyboardButton(text="❓ Задать вопрос куратору")],
        [KeyboardButton(text="📚 Частые вопросы мам")],
        [KeyboardButton(text="🛍️ Товары и рецензии")],
        [KeyboardButton(text="🧘 Поддержка и забота")],
        [KeyboardButton(text="📢 Наши каналы")],
        [KeyboardButton(text="💬 Поговорить с куратором")],
        [KeyboardButton(text="ℹ️ О проекте")]
    ]
    if is_admin(user_id):
        buttons.append([KeyboardButton(text="👑 Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

admin_kb = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="📋 Неотвеченные вопросы")],
        [KeyboardButton(text="📈 Статистика")],
        [KeyboardButton(text="📚 Управление FAQ")],
        [KeyboardButton(text="➕ Создать опрос")],
        [KeyboardButton(text="🔙 В главное меню")]
    ],
    resize_keyboard=True
)

def get_question_inline(q_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✍️ Ответить", callback_data=f"answer_{q_id}")],
        [InlineKeyboardButton(text="🗑 Пропустить", callback_data=f"skip_{q_id}")]
    ])

def get_answer_inline(q_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📚 Добавить в FAQ", callback_data=f"add_faq_{q_id}")],
        [InlineKeyboardButton(text="✅ Закрыть", callback_data=f"close_{q_id}")]
    ])

def get_faq_inline_keyboard():
    """Создаёт инлайн-клавиатуру из всех вопросов в FAQ (по 2 кнопки в ряд)"""
    faqs = get_all_faq()
    if not faqs:
        return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="📭 FAQ пуст", callback_data="faq_empty")]])
    buttons = []
    for fid, q, a in faqs:
        # Ограничим длину текста кнопки
        short_q = q[:40] + "..." if len(q) > 40 else q
        buttons.append([InlineKeyboardButton(text=short_q, callback_data=f"faq_{fid}")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)

# ========== FSM ==========
class AskQuestion(StatesGroup):
    waiting_for_question = State()

class AnswerFlow(StatesGroup):
    waiting_for_answer = State()

class PollCreation(StatesGroup):
    waiting_question = State()
    waiting_options = State()

class ManualFAQ(StatesGroup):
    waiting_question = State()
    waiting_answer = State()

class LiveChat(StatesGroup):
    waiting = State()

# ========== БОТ ==========
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# --- СТАРТ ---
@dp.message(Command("start"))
async def cmd_start(message: Message):
    get_user(message.from_user.id, message.from_user.username, message.from_user.full_name)
    await message.answer(
        f"👋 Привет, {message.from_user.first_name}!\n\n"
        "🌸 **«Мама, дыши и улыбайся»** и **«Детки на заметку»** — твоё безопасное пространство.\n\n"
        "✨ Что я умею:\n"
        "• ❓ Задать вопрос куратору (опытные мамы ответят)\n"
        "• 📚 Готовые ответы на частые вопросы (более 30 тем)\n"
        "• 🛍️ Рекомендации лучших товаров для детей (в разработке)\n"
        "• 🧘 Упражнения и советы для восстановления (в разработке)\n"
        "• 💬 Анонимная поддержка — выговориться без страха\n\n"
        "👇 Выбирай нужный раздел!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard(message.from_user.id))

# --- ЗАДАТЬ ВОПРОС С АВТООТВЕТОМ ИЗ FAQ ---
@dp.message(F.text == "❓ Задать вопрос куратору")
async def ask_question(message: Message, state: FSMContext):
    await state.set_state(AskQuestion.waiting_for_question)
    await message.answer("📝 Напишите ваш вопрос. Я сначала поищу ответ в базе знаний. Если не найду — передам куратору.\n\nОтменить: /cancel")

@dp.message(AskQuestion.waiting_for_question)
async def process_question(message: Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard(message.from_user.id))
        return
    
    user_question = message.text
    answer = search_faq(user_question)
    if answer:
        await message.answer(f"📖 **Нашёл ответ в базе знаний:**\n\n{answer}\n\n👍 Помогло? Если нет — просто задай вопрос ещё раз, я передам куратору.")
        await state.clear()
        return
    
    q_id = save_question(message.from_user.id, user_question)
    await state.clear()
    await message.answer("✅ Вопрос не найден в базе. Я передал его куратору. Ответ придёт в этот чат.\n🌱 Спасибо за доверие!")
    
    user_info = get_user_info(message.from_user.id)
    for admin_id in ADMIN_IDS:
        await bot.send_message(
            admin_id,
            f"🔔 **Новый вопрос от мамы** (не найден в FAQ)\n\n"
            f"👤 **От:** {user_info['mention']}\n"
            f"📛 **Имя:** {user_info['full_name']}\n"
            f"🆔 **ID:** `{message.from_user.id}`\n\n"
            f"💬 **Вопрос:**\n_{user_question}_",
            parse_mode="Markdown",
            reply_markup=get_question_inline(q_id)
        )

# --- ОТВЕТЫ АДМИНА И ДОБАВЛЕНИЕ В FAQ ---
@dp.callback_query(F.data.startswith("answer_"))
async def admin_answer_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    q_id = int(callback.data.split("_")[1])
    await state.update_data(answer_qid=q_id)
    await state.set_state(AnswerFlow.waiting_for_answer)
    await callback.message.answer("✏️ Напишите ответ на этот вопрос:")
    await callback.answer()

@dp.message(AnswerFlow.waiting_for_answer)
async def admin_answer_process(message: Message, state: FSMContext):
    data = await state.get_data()
    q_id = data["answer_qid"]
    answer_text = message.text
    user_id = answer_question(q_id, answer_text, message.from_user.id)
    
    await bot.send_message(user_id, f"📬 **Ответ куратора:**\n\n{answer_text}")
    await message.answer("✅ Ответ отправлен пользователю.")
    
    await message.answer(
        "📚 Хотите добавить этот вопрос и ответ в базу знаний, чтобы в будущем бот отвечал автоматически?",
        reply_markup=get_answer_inline(q_id)
    )
    await state.clear()

@dp.callback_query(F.data.startswith("add_faq_"))
async def add_to_faq_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    q_id = int(callback.data.split("_")[2])
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT question_text, answer_text FROM questions WHERE id = ?", (q_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        question, answer = row
        success = add_faq(question, answer)
        if success:
            mark_added_to_faq(q_id)
            await callback.message.answer("✅ Вопрос и ответ добавлены в базу знаний! Теперь бот будет отвечать на подобные вопросы автоматически.")
        else:
            await callback.message.answer("⚠️ Такая пара уже есть в базе знаний.")
    else:
        await callback.message.answer("❌ Ошибка: вопрос не найден.")
    await callback.answer()

@dp.callback_query(F.data.startswith("close_"))
async def close_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_"))
async def admin_skip(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    await callback.message.answer("⏩ Вопрос пропущен.")
    await callback.answer()

# --- УПРАВЛЕНИЕ FAQ ДЛЯ АДМИНА ---
@dp.message(F.text == "📚 Управление FAQ")
async def manage_faq(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вручную", callback_data="manual_add_faq")],
        [InlineKeyboardButton(text="📋 Список FAQ", callback_data="list_faq")],
        [InlineKeyboardButton(text="🗑 Удалить запись", callback_data="delete_faq")]
    ])
    await message.answer("📚 **Управление базой знаний**\n\nВыберите действие:", reply_markup=kb)

@dp.callback_query(F.data == "manual_add_faq")
async def manual_add_faq_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    await state.set_state(ManualFAQ.waiting_question)
    await callback.message.answer("✏️ Введите вопрос (как его будут задавать пользователи):")
    await callback.answer()

@dp.message(ManualFAQ.waiting_question)
async def manual_add_faq_question(message: Message, state: FSMContext):
    await state.update_data(faq_question=message.text)
    await state.set_state(ManualFAQ.waiting_answer)
    await message.answer("✏️ Введите ответ на этот вопрос:")

@dp.message(ManualFAQ.waiting_answer)
async def manual_add_faq_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    question = data["faq_question"]
    answer = message.text
    success = add_faq(question, answer)
    if success:
        await message.answer("✅ Новая пара вопрос-ответ добавлена в базу знаний!")
    else:
        await message.answer("⚠️ Такой вопрос уже существует.")
    await state.clear()

@dp.callback_query(F.data == "list_faq")
async def list_faq_callback(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    faqs = get_all_faq()
    if not faqs:
        await callback.message.answer("📭 База знаний пуста.")
    else:
        text = "📚 **Список FAQ:**\n\n"
        for fid, q, a in faqs[:20]:
            text += f"{fid}. {q[:60]}...\n"
        text += "\nДля удаления используйте кнопку «Удалить запись»."
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "delete_faq")
async def delete_faq_start(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    faqs = get_all_faq()
    if not faqs:
        await callback.message.answer("Нет записей для удаления.")
        await callback.answer()
        return
    kb_buttons = []
    for fid, q, _ in faqs[:20]:
        kb_buttons.append([InlineKeyboardButton(text=f"{fid}. {q[:40]}...", callback_data=f"del_faq_{fid}")])
    kb = InlineKeyboardMarkup(inline_keyboard=kb_buttons)
    await callback.message.answer("🗑 Выберите ID записи для удаления:", reply_markup=kb)
    await callback.answer()

@dp.callback_query(F.data.startswith("del_faq_"))
async def confirm_delete_faq(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав")
        return
    faq_id = int(callback.data.split("_")[2])
    delete_faq(faq_id)
    await callback.message.answer(f"✅ Запись #{faq_id} удалена.")
    await callback.answer()

# --- ЧАСТЫЕ ВОПРОСЫ (инлайн-меню) ---
@dp.message(F.text == "📚 Частые вопросы мам")
async def show_faq_menu(message: Message):
    await message.answer(
        "📖 **Выберите интересующий вопрос из списка ниже:**\n\n"
        "👇 Нажмите на кнопку с вопросом, чтобы увидеть ответ.\n"
        "Если не нашли нужный, воспользуйтесь поиском по ключевому слову или задайте вопрос куратору.",
        reply_markup=get_faq_inline_keyboard()
    )

@dp.callback_query(F.data.startswith("faq_"))
async def handle_faq_callback(callback: CallbackQuery):
    data = callback.data
    if data == "faq_empty":
        await callback.answer("База знаний пока пуста.", show_alert=True)
        return
    # формат: faq_{id}
    faq_id = int(data.split("_")[1])
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT question, answer FROM faq WHERE id = ?", (faq_id,))
    row = cur.fetchone()
    conn.close()
    if row:
        question, answer = row
        await callback.message.answer(f"**❓ {question}**\n\n{answer}", parse_mode="Markdown")
    else:
        await callback.message.answer("❌ Ответ не найден.")
    await callback.answer()

# --- ТОВАРЫ И РЕЦЕНЗИИ (заглушка) ---
@dp.message(F.text == "🛍️ Товары и рецензии")
async def products(message: Message):
    await message.answer(
        "🛒 **Раздел «Товары и рецензии» скоро появится!**\n\n"
        "🚧 Пока мы собираем лучшие рекомендации и отзывы мам.\n"
        "🌟 Следите за обновлениями в нашем канале.\n\n"
        "А пока вы можете задать вопрос куратору о любом товаре — опытные мамы подскажут!"
    )

# --- ПОДДЕРЖКА И ЗАБОТА (заглушка) ---
@dp.message(F.text == "🧘 Поддержка и забота")
async def support(message: Message):
    await message.answer(
        "🧘 **Раздел «Поддержка и забота» в разработке!**\n\n"
        "🌱 Здесь скоро появятся:\n"
        "• Дыхательные практики и упражнения\n"
        "• Советы психолога\n"
        "• Истории мам, которые прошли через трудности\n\n"
        "✨ А пока вы можете воспользоваться кнопкой «💬 Поговорить с куратором» — мы всегда рядом."
    )

# --- НАШИ КАНАЛЫ ---
@dp.message(F.text == "📢 Наши каналы")
async def our_channels(message: Message):
    text = (
        "📢 **Наши проекты для мам:**\n\n"
        f"🌸 [Мама, дыши и улыбайся]({CHANNELS['mama_dychi']}) — поддержка, дыхательные практики, посты о материнстве\n\n"
        f"📘 [Детки на заметку]({CHANNELS['detky_nazametky']}) — развитие, здоровье, лайфхаки для мам\n\n"
        "🔔 **Подпишись, чтобы не пропустить:**\n"
        "• Бесплатные вебинары\n"
        "• Розыгрыши товаров для детей\n"
        "• Анонсы встреч мам\n\n"
        "🤱 Здесь тебя понимают и ждут!"
    )
    await message.answer(text, parse_mode="Markdown")

# --- ЖИВОЙ ЧАТ С КУРАТОРОМ ---
@dp.message(F.text == "💬 Поговорить с куратором")
async def live_chat_start(message: Message, state: FSMContext):
    await state.set_state(LiveChat.waiting)
    await message.answer("💬 Напишите своё сообщение. Куратор ответит в ближайшее время.\nОтменить: /cancel")

@dp.message(LiveChat.waiting)
async def process_live_chat(message: Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard(message.from_user.id))
        return
    await state.clear()
    await message.answer("✅ Сообщение передано куратору. Ответ придёт сюда.")
    user_info = get_user_info(message.from_user.id)
    for admin_id in ADMIN_IDS:
        await bot.send_message(
            admin_id,
            f"💌 **Сообщение от мамы**\n\n"
            f"👤 **От:** {user_info['mention']}\n"
            f"📛 **Имя:** {user_info['full_name']}\n"
            f"🆔 **ID:** `{message.from_user.id}`\n\n"
            f"💬 **Текст:**\n_{message.text}_",
            parse_mode="Markdown"
        )

# --- О ПРОЕКТЕ ---
@dp.message(F.text == "ℹ️ О проекте")
async def about_project(message: Message):
    text = (
        "✨ **О проекте**\n\n"
        "«Мама, дыши и улыбайся» — канал, где мамы делятся опытом, поддерживают друг друга и напоминают: ты справляешься!\n"
        "«Детки на заметку» — полезности о здоровье, развитии и воспитании детей.\n\n"
        "🤖 **Этот бот** — твой помощник:\n"
        "• Задай вопрос куратору\n"
        "• Найди готовый ответ в базе из 30+ тем\n"
        "• Получи рекомендации товаров (скоро)\n"
        "• Освоишь дыхательные практики (скоро)\n"
        "• Просто выговорись\n\n"
        "📌 **Контакты:**\n"
        "По вопросам сотрудничества: @ваш_логин (укажите свой)\n\n"
        "🌸 Ты — лучшая мама для своего ребёнка!"
    )
    await message.answer(text)

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👑 Добро пожаловать в админ-панель", reply_markup=admin_kb)

@dp.message(F.text == "📋 Неотвеченные вопросы")
async def admin_unanswered(message: Message):
    if not is_admin(message.from_user.id):
        return
    questions = get_unanswered_questions()
    if not questions:
        await message.answer("🎉 Нет неотвеченных вопросов!")
        return
    for q_id, q_text, asked_by in questions:
        user_info = get_user_info(asked_by)
        await message.answer(
            f"📝 **Вопрос #{q_id}**\nОт: {user_info['mention']}\n\n{q_text}",
            parse_mode="Markdown",
            reply_markup=get_question_inline(q_id)
        )

@dp.message(F.text == "📈 Статистика")
async def admin_stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users, total_q, answered_q = get_stats()
    await message.answer(f"📊 **Статистика**\n👥 Пользователей: {users}\n❓ Всего вопросов: {total_q}\n✅ Отвечено: {answered_q}")

@dp.message(F.text == "➕ Создать опрос")
async def admin_create_poll(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(PollCreation.waiting_question)
    await message.answer("Введите вопрос для опроса:")

@dp.message(PollCreation.waiting_question)
async def poll_question(message: Message, state: FSMContext):
    await state.update_data(poll_q=message.text)
    await state.set_state(PollCreation.waiting_options)
    await message.answer("Введите варианты через запятую (пример: Да, Нет, Не знаю)")

@dp.message(PollCreation.waiting_options)
async def poll_options(message: Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    if len(options) < 2:
        await message.answer("❌ Нужно минимум 2 варианта. Попробуйте снова.")
        return
    data = await state.get_data()
    await state.clear()
    await bot.send_poll(chat_id=message.chat.id, question=data["poll_q"], options=options, is_anonymous=False)
    await message.answer("✅ Опрос отправлен!")

@dp.message(F.text == "🔙 В главное меню")
async def back_to_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Возврат в главное меню", reply_markup=get_main_keyboard(message.from_user.id))

# --- ПОИСК ПО КЛЮЧЕВЫМ СЛОВАМ (если пользователь просто пишет текст) ---
@dp.message(F.text, ~StateFilter(AskQuestion.waiting_for_question, AnswerFlow.waiting_for_answer, PollCreation.waiting_question, PollCreation.waiting_options, ManualFAQ.waiting_question, ManualFAQ.waiting_answer, LiveChat.waiting))
async def free_text_search(message: Message):
    if message.text in ["❓ Задать вопрос куратору", "📚 Частые вопросы мам", "🛍️ Товары и рецензии", "🧘 Поддержка и забота", "📢 Наши каналы", "💬 Поговорить с куратором", "ℹ️ О проекте", "👑 Админ-панель", "📋 Неотвеченные вопросы", "📈 Статистика", "📚 Управление FAQ", "➕ Создать опрос", "🔙 В главное меню"]:
        return
    answer = search_faq(message.text)
    if answer:
        await message.answer(f"📖 **Нашёл ответ:**\n\n{answer}")
    else:
        await message.answer("😕 Не нашёл ответа в базе. Попробуйте задать вопрос куратору через кнопку «❓ Задать вопрос куратору».")

# --- ЗАПУСК ---
async def main():
    init_db()
    init_faq_table()
    fill_default_faq()  # заполняем 30 вопросами
    print("✅ Бот запущен. База знаний готова.")
    print(f"👑 Администраторы: {ADMIN_IDS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())