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

# ========== ТОКЕН БОТА (ВСТАВЬТЕ СВОЙ) ==========
BOT_TOKEN = "8660466323:AAHKGwCNkz5tD2ZA4l_0f-pPiMdaj3_H_so"  # Пример: "5826884420:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw"

# ========== ID АДМИНИСТРАТОРОВ ==========
ADMIN_IDS = [5826884420,1669539257]  # Ваш Telegram ID

CHANNELS = {
    "mama_dychi": "https://t.me/mama_dychi",
    "detky_nazametky": "https://t.me/detky_nazametky"
}

DB_NAME = "database.db"

# ========== БАЗОВАЯ ТАБЛИЦА ==========
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

# ========== БАЗА ЗНАНИЙ (FAQ) ==========
def init_faq_table():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS faq (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL UNIQUE,
            answer TEXT NOT NULL,
            keywords TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("CREATE INDEX IF NOT EXISTS idx_question ON faq (question)")
    conn.commit()
    conn.close()

def add_faq(question: str, answer: str) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    import re
    keywords = ' '.join([w for w in re.findall(r'\b\w+\b', question.lower()) if len(w) > 3])
    try:
        cur.execute(
            "INSERT INTO faq (question, answer, keywords) VALUES (?, ?, ?)",
            (question, answer, keywords)
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def search_faq(query: str):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    import re
    query_lower = query.lower().strip()
    cur.execute("SELECT answer FROM faq WHERE LOWER(question) = ?", (query_lower,))
    row = cur.fetchone()
    if row:
        conn.close()
        return row[0]
    words = [w for w in re.findall(r'\b\w+\b', query_lower) if len(w) > 3]
    if not words:
        conn.close()
        return None
    like_conditions = ' OR '.join(['keywords LIKE ?'] * len(words))
    like_params = [f'%{w}%' for w in words]
    cur.execute(f"SELECT answer FROM faq WHERE {like_conditions} LIMIT 1", like_params)
    row = cur.fetchone()
    conn.close()
    return row[0] if row else None

def get_all_faq():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT id, question, answer FROM faq ORDER BY id")
    rows = cur.fetchall()
    conn.close()
    return rows

def delete_faq(faq_id: int) -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("DELETE FROM faq WHERE id = ?", (faq_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted

def is_faq_empty() -> bool:
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM faq")
    count = cur.fetchone()[0]
    conn.close()
    return count == 0

# 30 частых вопросов
DEFAULT_FAQ = [
    ("Как наладить сон ребёнка?", "😴 **Как наладить сон ребёнка?**\n\n• Установите ритуал (купание, сказка)\n• Тёмная комната + белый шум\n• Не перегревайте (20-22°C)\n• Сытый малыш спит лучше"),
    ("Проблемы с грудным вскармливанием", "🍼 **Проблемы ГВ:**\n\n• Прикладывайте по требованию\n• Следите за захватом\n• Пейте тёплое перед кормлением"),
    ("С чего начать прикорм?", "🥄 **Начало прикорма:**\n\n• С 6 месяцев\n• Начинайте с овощей\n• Новый продукт раз в 3 дня"),
    ("Что делать при коликах?", "😖 **Колики:**\n\n• Выкладывайте на живот\n• Тёплая пелёнка\n• Массаж по часовой стрелке"),
    ("Температура у ребёнка", "🌡️ **Температура:**\n\n• До 38°C не сбивайте\n• Обильное питьё\n• Выше 38.5°C — жаропонижающее"),
    ("Развитие в 3 месяца", "👶 **Развитие в 3 месяца:**\n\n• Улыбается\n• Держит голову\n• Гулит"),
    ("Развитие в 6 месяцев", "🧸 **Развитие в 6 месяцев:**\n\n• Сидит\n• Переворачивается\n• Тянет всё в рот"),
    ("Развитие в 1 год", "🎉 **Развитие в 1 год:**\n\n• Ходит\n• Говорит 2-10 слов\n• Показывает части тела"),
    ("Аллергия у грудничка", "🤧 **Аллергия:**\n\n• Сыпь на щеках\n• Ведите пищевой дневник\n• К врачу-аллергологу"),
    ("Запор у малыша", "💩 **Запор:**\n\n• Больше жидкости\n• Массаж живота\n• Чернослив (с 6 мес)"),
    ("Сколько гулять?", "☀️ **Прогулки:**\n\n• 1.5-4 часа в день\n• Одевайте по погоде +1 слой"),
    ("Пустышка: за и против", "🍼 **Пустышка:**\n\n• До 6 месяцев — можно\n• После года — отучаем"),
    ("Что делать при истерике?", "😭 **Истерика:**\n\n• Сохраняйте спокойствие\n• Переключите внимание\n• Обнимите после"),
    ("Когда лезут зубы?", "🦷 **Зубы:**\n\n• Первые зубы: 6-8 месяцев\n• Прорезыватели в помощь"),
    ("Нужен ли развивающий коврик?", "🧩 **Коврик:**\n\n• Да, с 2-3 месяцев\n• Развивает сенсорику"),
    ("Экранное время для детей", "📱 **Экранное время:**\n\n• До 2 лет не рекомендуется\n• Альтернатива: книги, игры"),
    ("Как не кричать на ребёнка?", "👩‍👧 **Как не кричать:**\n\n• Сделайте глубокий вдох\n• Выйдите из комнаты\n• Хвалите за хорошее поведение"),
    ("Как вовлечь папу?", "👨‍👦 **Вовлечь папу:**\n\n• Оставьте их вдвоём\n• Доверьте купание/прогулку\n• Хвалите за помощь"),
    ("Мама, выдохни! (отдых)", "🧘 **Мама, выдохни:**\n\n• Сон, когда спит ребёнок\n• 15 минут на себя\n• Просите помощь"),
    ("Список в роддом", "🏥 **Список в роддом:**\n\n• Документы\n• Вещи для малыша\n• Вещи для мамы"),
    ("Прививки детям", "💉 **Прививки:**\n\n• По календарю\n• Ребёнок должен быть здоров"),
    ("Как выбрать смесь?", "🍼 **Смесь:**\n\n• Только по рекомендации педиатра\n• Для новорожденных 0-6"),
    ("Путешествуем с малышом", "✈️ **Путешествия:**\n\n• В самолёт с 7 дней\n• Аптечка + запасная одежда"),
    ("Полезные курсы для мам", "📚 **Курсы:**\n\n• Наш канал @mama_dychi\n• Школа материнства"),
    ("Детская аптечка", "🚑 **Аптечка:**\n\n• Жаропонижающее\n• Антигистаминное\n• От колик\n• Зелёнка, бинт"),
    ("Как подготовиться к визиту к врачу?", "👩‍⚕️ **К врачу:**\n\n• Список вопросов\n• Запишите симптомы\n• Игрушка для отвлечения"),
    ("Слинг: плюсы", "🪢 **Слинг:**\n\n• Руки свободны\n• Успокаивает малыша\n• С консультантом безопаснее"),
    ("Ребёнок плохо спит ночью", "🌙 **Ночной сон:**\n\n• Проверьте зубы/живот\n• Ритуал перед сном"),
    ("Массаж для малыша", "💆‍♀️ **Массаж:**\n\n• С 1 месяца\n• До еды или через час"),
    ("Как научить ребёнка засыпать самостоятельно?", "😴 **Самостоятельное засыпание:**\n\n• Метод «Посиди рядом»\n• Ритуал каждый день\n• Терпение 1-2 недели")
]

def fill_default_faq():
    if is_faq_empty():
        for q, a in DEFAULT_FAQ:
            add_faq(q, a)
        print("✅ База знаний заполнена 30 частыми вопросами.")
    else:
        print("ℹ️ База знаний уже содержит данные.")

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

def get_faq_inline_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="😴 Сон малыша", callback_data="faq_сон")],
        [InlineKeyboardButton(text="🍼 Грудное вскармливание", callback_data="faq_грудное вскармливание")],
        [InlineKeyboardButton(text="🥄 Прикорм", callback_data="faq_прикорм")],
        [InlineKeyboardButton(text="😖 Колики", callback_data="faq_колики")],
        [InlineKeyboardButton(text="🌡️ Температура", callback_data="faq_температура")],
        [InlineKeyboardButton(text="👶 Развитие по месяцам", callback_data="faq_развитие")],
        [InlineKeyboardButton(text="🤧 Аллергия", callback_data="faq_аллергия")],
        [InlineKeyboardButton(text="💩 Запор", callback_data="faq_запор")],
        [InlineKeyboardButton(text="🦷 Зубы", callback_data="faq_зубы")],
        [InlineKeyboardButton(text="📖 Все ответы", callback_data="faq_all")]
    ])

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
        "• 📚 Готовые ответы на частые вопросы\n"
        "• 🛍️ Рекомендации лучших товаров для детей\n"
        "• 🧘 Упражнения и советы для восстановления\n"
        "• 💬 Анонимная поддержка — выговориться без страха\n\n"
        "👇 Выбирай нужный раздел!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.message(Command("cancel"))
async def cancel_cmd(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("❌ Действие отменено.", reply_markup=get_main_keyboard(message.from_user.id))

# --- ЧАСТЫЕ ВОПРОСЫ ---
@dp.message(F.text == "📚 Частые вопросы мам")
async def show_faq_menu(message: Message):
    await message.answer(
        "📖 **Частые вопросы мам**\n\n👇 Выберите тему:",
        reply_markup=get_faq_inline_menu()
    )

@dp.callback_query(F.data.startswith("faq_"))
async def handle_faq_callback(callback: CallbackQuery):
    topic = callback.data.split("_", 1)[1]
    
    if topic == "all":
        faqs = get_all_faq()
        if not faqs:
            await callback.message.answer("📭 База знаний пока пуста.")
        else:
            text = "📚 **Все вопросы:**\n\n"
            for fid, q, _ in faqs[:30]:
                text += f"• {q}\n"
            text += "\n🔍 Напишите ключевое слово для поиска!"
            await callback.message.answer(text)
        await callback.answer()
        return
    
    answer = search_faq(topic)
    if answer:
        await callback.message.answer(answer)
    else:
        await callback.message.answer("🔍 Не нашли? Задайте вопрос куратору через меню.")
    await callback.answer()

# --- ЗАДАТЬ ВОПРОС ---
@dp.message(F.text == "❓ Задать вопрос куратору")
async def ask_question(message: Message, state: FSMContext):
    await state.set_state(AskQuestion.waiting_for_question)
    await message.answer("📝 Напишите вопрос. Я поищу ответ в базе. Если не найду — передам куратору.\nОтменить: /cancel")

@dp.message(AskQuestion.waiting_for_question)
async def process_question(message: Message, state: FSMContext):
    if message.text and message.text.strip().lower() == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.", reply_markup=get_main_keyboard(message.from_user.id))
        return
    
    user_question = message.text
    answer = search_faq(user_question)
    if answer:
        await message.answer(f"📖 **Нашёл ответ:**\n\n{answer}\n\n👍 Помогло?")
        await state.clear()
        return
    
    q_id = save_question(message.from_user.id, user_question)
    await state.clear()
    await message.answer("✅ Вопрос передан куратору. Ответ придёт сюда.")
    
    user_info = get_user_info(message.from_user.id)
    for admin_id in ADMIN_IDS:
        await bot.send_message(
            admin_id,
            f"🔔 **Новый вопрос!**\n\n"
            f"👤 **От:** {user_info['mention']}\n"
            f"📛 **Имя:** {user_info['full_name']}\n\n"
            f"💬 **Вопрос:**\n_{user_question}_",
            parse_mode="Markdown",
            reply_markup=get_question_inline(q_id)
        )

# --- ОТВЕТЫ АДМИНА ---
@dp.callback_query(F.data.startswith("answer_"))
async def admin_answer_start(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("Нет прав", show_alert=True)
        return
    q_id = int(callback.data.split("_")[1])
    await state.update_data(answer_qid=q_id)
    await state.set_state(AnswerFlow.waiting_for_answer)
    await callback.message.answer("✏️ Напишите ответ:")
    await callback.answer()

@dp.message(AnswerFlow.waiting_for_answer)
async def admin_answer_process(message: Message, state: FSMContext):
    data = await state.get_data()
    q_id = data["answer_qid"]
    answer_text = message.text
    user_id = answer_question(q_id, answer_text, message.from_user.id)
    
    await bot.send_message(user_id, f"📬 **Ответ куратора:**\n\n{answer_text}")
    await message.answer("✅ Ответ отправлен.")
    
    await message.answer(
        "📚 Добавить в базу знаний?",
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
            await callback.message.answer("✅ Добавлено в базу знаний!")
        else:
            await callback.message.answer("⚠️ Уже есть в базе.")
    await callback.answer()

@dp.callback_query(F.data.startswith("close_"))
async def close_callback(callback: CallbackQuery):
    await callback.message.delete()
    await callback.answer()

@dp.callback_query(F.data.startswith("skip_"))
async def admin_skip(callback: CallbackQuery):
    await callback.message.answer("⏩ Пропущено.")
    await callback.answer()

# --- УПРАВЛЕНИЕ FAQ ---
@dp.message(F.text == "📚 Управление FAQ")
async def manage_faq(message: Message):
    if not is_admin(message.from_user.id):
        return
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить вручную", callback_data="manual_add_faq")],
        [InlineKeyboardButton(text="📋 Список FAQ", callback_data="list_faq")],
        [InlineKeyboardButton(text="🗑 Удалить", callback_data="delete_faq")]
    ])
    await message.answer("📚 Управление базой знаний:", reply_markup=kb)

@dp.callback_query(F.data == "manual_add_faq")
async def manual_add_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ManualFAQ.waiting_question)
    await callback.message.answer("Введите вопрос:")
    await callback.answer()

@dp.message(ManualFAQ.waiting_question)
async def manual_question(message: Message, state: FSMContext):
    await state.update_data(faq_question=message.text)
    await state.set_state(ManualFAQ.waiting_answer)
    await message.answer("Введите ответ:")

@dp.message(ManualFAQ.waiting_answer)
async def manual_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    success = add_faq(data["faq_question"], message.text)
    await message.answer("✅ Добавлено!" if success else "⚠️ Уже есть")
    await state.clear()

@dp.callback_query(F.data == "list_faq")
async def list_faq(callback: CallbackQuery):
    faqs = get_all_faq()
    if not faqs:
        await callback.message.answer("📭 База пуста.")
    else:
        text = "📚 **FAQ:**\n\n"
        for fid, q, _ in faqs[:20]:
            text += f"{fid}. {q[:50]}...\n"
        await callback.message.answer(text)
    await callback.answer()

@dp.callback_query(F.data == "delete_faq")
async def delete_start(callback: CallbackQuery):
    faqs = get_all_faq()
    if not faqs:
        await callback.message.answer("Нет записей.")
        await callback.answer()
        return
    buttons = [[InlineKeyboardButton(text=f"{fid}. {q[:40]}...", callback_data=f"del_faq_{fid}")] for fid, q, _ in faqs[:20]]
    await callback.message.answer("🗑 Выберите ID для удаления:", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons))
    await callback.answer()

@dp.callback_query(F.data.startswith("del_faq_"))
async def delete_faq_callback(callback: CallbackQuery):
    faq_id = int(callback.data.split("_")[2])
    delete_faq(faq_id)
    await callback.message.answer(f"✅ Запись #{faq_id} удалена.")
    await callback.answer()

# --- ОСТАЛЬНЫЕ КНОПКИ ---
@dp.message(F.text == "🛍️ Товары и рецензии")
async def products(message: Message):
    await message.answer("🛍️ **Товары и рецензии**\n\n🚧 Раздел в разработке. Скоро здесь появятся рекомендации лучших товаров для детей и отзывы мам!")

@dp.message(F.text == "🧘 Поддержка и забота")
async def support(message: Message):
    await message.answer("🧘 **Поддержка и забота**\n\n🚧 Раздел в разработке. Скоро здесь появятся дыхательные практики, упражнения и советы психолога!")

@dp.message(F.text == "📢 Наши каналы")
async def channels(message: Message):
    await message.answer(f"📢 **Наши каналы:**\n\n🌸 [Мама, дыши и улыбайся]({CHANNELS['mama_dychi']})\n📘 [Детки на заметку]({CHANNELS['detky_nazametky']})", parse_mode="Markdown")

@dp.message(F.text == "💬 Поговорить с куратором")
async def live_chat_start(message: Message, state: FSMContext):
    await state.set_state(LiveChat.waiting)
    await message.answer("💬 Напишите сообщение. Куратор ответит.\nОтменить: /cancel")

@dp.message(LiveChat.waiting)
async def live_chat(message: Message, state: FSMContext):
    if message.text == "/cancel":
        await state.clear()
        await message.answer("❌ Отменено.")
        return
    await state.clear()
    await message.answer("✅ Сообщение передано.")
    user_info = get_user_info(message.from_user.id)
    for admin_id in ADMIN_IDS:
        await bot.send_message(admin_id, f"💌 Сообщение от {user_info['mention']}:\n{message.text}")

@dp.message(F.text == "ℹ️ О проекте")
async def about(message: Message):
    await message.answer("✨ **О проекте**\n\n«Мама, дыши и улыбайся» и «Детки на заметку» — каналы поддержки мам.\n\n🤖 Бот помогает:\n• Задать вопрос\n• Найти ответ\n• Получить поддержку\n\n🌸 Ты — лучшая мама!")

# --- АДМИН-ПАНЕЛЬ ---
@dp.message(F.text == "👑 Админ-панель")
async def admin_panel(message: Message):
    if not is_admin(message.from_user.id):
        return
    await message.answer("👑 Админ-панель", reply_markup=admin_kb)

@dp.message(F.text == "📋 Неотвеченные вопросы")
async def unanswered(message: Message):
    if not is_admin(message.from_user.id):
        return
    questions = get_unanswered_questions()
    if not questions:
        await message.answer("🎉 Нет вопросов!")
        return
    for q_id, q_text, asked_by in questions:
        user_info = get_user_info(asked_by)
        await message.answer(f"📝 Вопрос #{q_id}\nОт: {user_info['mention']}\n\n{q_text}", parse_mode="Markdown", reply_markup=get_question_inline(q_id))

@dp.message(F.text == "📈 Статистика")
async def stats(message: Message):
    if not is_admin(message.from_user.id):
        return
    users, total_q, answered_q = get_stats()
    await message.answer(f"📊 Статистика\n👥 Пользователей: {users}\n❓ Вопросов: {total_q}\n✅ Отвечено: {answered_q}")

@dp.message(F.text == "➕ Создать опрос")
async def create_poll(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    await state.set_state(PollCreation.waiting_question)
    await message.answer("Введите вопрос для опроса:")

@dp.message(PollCreation.waiting_question)
async def poll_q(message: Message, state: FSMContext):
    await state.update_data(poll_q=message.text)
    await state.set_state(PollCreation.waiting_options)
    await message.answer("Введите варианты через запятую (пример: Да, Нет, Не знаю)")

@dp.message(PollCreation.waiting_options)
async def poll_opts(message: Message, state: FSMContext):
    options = [opt.strip() for opt in message.text.split(",") if opt.strip()]
    if len(options) < 2:
        await message.answer("❌ Минимум 2 варианта.")
        return
    data = await state.get_data()
    await state.clear()
    await bot.send_poll(chat_id=message.chat.id, question=data["poll_q"], options=options, is_anonymous=False)
    await message.answer("✅ Опрос отправлен!")

@dp.message(F.text == "🔙 В главное меню")
async def back_main(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Возврат", reply_markup=get_main_keyboard(message.from_user.id))

# --- ЗАПУСК ---
async def main():
    init_db()
    init_faq_table()
    fill_default_faq()
    print("✅ Бот запущен!")
    print(f"👑 Администраторы: {ADMIN_IDS}")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
