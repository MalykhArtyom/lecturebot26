import asyncio
import os
import time
import uuid
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from aiohttp import ClientSession
from aiohttp_socks import ProxyConnector
from config import BOT_TOKEN, PROXY_URL
from transcription import transcribe_audio_async
from summarization import create_summary_with_timestamps
from database import init_db, get_or_create_user, can_process_lecture, save_lecture, increment_lecture_count, get_user, \
    spend_purchased_lecture
from database import get_stats
from database import get_user_lectures

dp = Dispatcher()

# Убедимся, что папка audio существует
os.makedirs("audio", exist_ok=True)

from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from database import get_user


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Приветствие и знакомство с ботом."""

    # Получаем пользователя (создастся автоматически, если новый)
    user = get_or_create_user(
        message.from_user.id,
        message.from_user.username
    )

    # Считаем, сколько бесплатных лекций осталось
    free_left = max(0, 5 - user['lectures_count'])

    # Формируем текст в зависимости от статуса пользователя
    if user['lectures_count'] == 0:
        status_line = f"🎁 Вам доступно {free_left} бесплатных лекций!"
    elif free_left > 0:
        status_line = f"🎁 Осталось бесплатных лекций: {free_left}"
    else:
        status_line = f"💎 На балансе купленных лекций: {user['purchased_lectures']}"

    text = (
        "🎓 **Привет! Я бот-конспектор для студентов**\n\n"
        "Отправь мне MP3 с лекцией — я распознаю речь и сделаю "
        "структурированный конспект с разделами, терминами и выводами.\n\n"
        f"{status_line}\n\n"
        "📋 **Команды:**\n"
        "• /buy — купить пакет лекций\n"
        "• /mystats — проверить баланс\n"
        "• /help — как пользоваться\n"
        "• /history — мои последние конспекты\n\n"
        "🎧 Просто отправь аудиофайл, и начнём!"
    )

    # Кнопки быстрого доступа
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="💎 Купить лекции", callback_data="buy_10"),
            InlineKeyboardButton(text="📊 Мой баланс", callback_data="mystats_btn")
        ]
    ])

    await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")


@dp.message(Command("help"))
async def cmd_help(message: types.Message):
    await message.answer(
        "Как пользоваться:\n"
        "1. Отправь мне MP3 файл с лекцией (как документ или аудио)\n"
        "2. Подожди, пока я скачаю и обработаю его\n"
        "3. Получи структурированный конспект"
    )


@dp.message(F.audio)
async def handle_audio(message: types.Message):
    # Регистрируем пользователя (если ещё не зарегистрирован)
    user = get_or_create_user(
        message.from_user.id,
        message.from_user.username
    )

    # Проверяем лимит
    can_process, reason = can_process_lecture(message.from_user.id)
    if not can_process:
        await message.answer(reason)
        return

    wait_msg = await message.answer("⏳ Скачиваю аудиофайл...")

    user_id = message.from_user.id
    timestamp = int(time.time())

    original_name = message.audio.file_name or "audio.mp3"
    file_extension = original_name.split('.')[-1]
    unique_filename = f"audio/{user_id}_{timestamp}.{file_extension}"

    try:
        # Скачиваем файл с проверкой
        expected_size = message.audio.file_size
        await bot.download(message.audio.file_id, destination=unique_filename)

        actual_size = os.path.getsize(unique_filename)
        if actual_size < expected_size * 0.95:
            os.remove(unique_filename)
            await bot.download(message.audio.file_id, destination=unique_filename)

        await wait_msg.edit_text("✅ Файл сохранен!\n🔄 Транскрибирую аудио...")

        # Транскрибируем
        transcription_result = await transcribe_audio_async(unique_filename)
        if not transcription_result.get('success'):
            raise Exception("Транскрибация не удалась")

        chunks = transcription_result.get('chunks', [])

        # Собираем сырой текст для сохранения в БД
        raw_transcript = "\n".join([
            chunk.get('alternatives', [{}])[0].get('text', '')
            for chunk in chunks
        ])

        await wait_msg.edit_text("📝 Транскрибация готова!\n🧠 Создаю конспект...")

        # Создаем конспект
        summary = await create_summary_with_timestamps(chunks)

        # Сохраняем в БД
        save_lecture(
            telegram_id=user_id,
            filename=original_name,
            duration=message.audio.duration,
            transcript=raw_transcript,
            summary=summary
        )
        # Получаем актуальные данные пользователя перед сохранением
        current_user = get_user(user_id)

        if current_user['lectures_count'] >= 5:
            spend_purchased_lecture(user_id)
        else:
            increment_lecture_count(user_id)

        # Отправляем конспект
        if len(summary) > 4000:
            for i in range(0, len(summary), 4000):
                await message.answer(summary[i:i + 4000], parse_mode="Markdown")
        else:
            await message.answer(summary, parse_mode="Markdown")

        # Удаляем временный файл
        os.remove(unique_filename)

    except Exception as e:
        await wait_msg.edit_text(f"❌ Ошибка: {e}")


# Также добавим поддержку голосовых сообщений (Voice), если пользователь запишет их прямо в боте
@dp.message(F.voice)
async def handle_voice(message: types.Message):
    await message.answer(
        "🎤 Я получил голосовое сообщение! \n"
        "Пока я умею работать лучше всего с MP3 файлами, отправленными как документ или аудио. "
        "Попробуй отправить файл таким способом!"
    )

@dp.message(Command("stats"))
async def cmd_stats(message: types.Message):
    """Показывает статистику бота (для владельца)."""
    stats = get_stats()
    await message.answer(
        f"📊 **Статистика бота:**\n\n"
        f"👥 Всего пользователей: {stats['total_users']}\n"
        f"💎 Premium: {stats['premium_users']}\n"
        f"📚 Обработано лекций: {stats['total_lectures']}",
        parse_mode="Markdown"
    )


from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


@dp.message(Command("buy"))
async def cmd_buy(message: types.Message):
    """Показывает тарифы (нужно для скриншотов ЮKassa и будущих продаж)."""
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 10 лекций — 50₽", callback_data="buy_10")],
        [InlineKeyboardButton(text="🔥 20 лекций — 90₽", callback_data="buy_20")],
        [InlineKeyboardButton(text="🚀 50 лекций — 200₽", callback_data="buy_50")]
    ])

    await message.answer(
        "💎 **Магазин пакетов лекций**\n\n"
        "Выберите подходящий пакет. Купленные лекции не сгорают и действуют бессрочно!\n\n"
        "📦 **10 лекций** — 50₽ (5₽/лекция)\n"
        "📦 **20 лекций** — 90₽ (4.5₽/лекция)\n"
        "📦 **50 лекций** — 200₽ (4₽/лекция)",
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# Заглушка для кнопок (чтобы бот не ругался при нажатии)
@dp.callback_query(lambda c: c.data.startswith('buy_'))
async def process_buy_callback(callback_query: types.CallbackQuery):
    await callback_query.answer("⏳ Оплата скоро будет доступна!", show_alert=True)


@dp.callback_query(lambda c: c.data == "mystats_btn")
async def process_mystats_callback(callback_query: types.CallbackQuery):
    """Кнопка 'Мой баланс' из /start."""
    user = get_user(callback_query.from_user.id)
    if not user:
        await callback_query.answer("Сначала отправьте мне аудиофайл!", show_alert=True)
        return

    free_left = max(0, 5 - user['lectures_count'])

    text = (
        f"👤 **Ваш баланс:**\n\n"
        f"🎁 Бесплатных осталось: {free_left}\n"
        f"💎 Куплено: {user['purchased_lectures']} лекций\n"
        f"📚 Всего обработано: {user['lectures_count']}"
    )

    await callback_query.message.answer(text, parse_mode="Markdown")
    await callback_query.answer()



@dp.message(Command("history"))
async def cmd_history(message: types.Message):
    """Показывает последние 5 обработанных лекций."""
    lectures = get_user_lectures(message.from_user.id, limit=5)

    if not lectures:
        await message.answer(
            "📭 Вы ещё не обработали ни одной лекции.\n"
            "Отправьте мне MP3 файл, чтобы начать!"
        )
        return

    lines = ["📚 **Ваши последние конспекты:**\n"]
    for i, lecture in enumerate(lectures, 1):
        date = lecture['created_at'][:10]  # Берём только дату (YYYY-MM-DD)
        duration_min = lecture['duration'] // 60 if lecture['duration'] else 0
        lines.append(
            f"{i}. {lecture['filename']}\n"
            f"   📅 {date} | ⏱ {duration_min} мин | 🆔 #{lecture['id']}"
        )

    lines.append("\n💡 Чтобы получить конспект, отправьте: /get <номер>")
    await message.answer("\n".join(lines), parse_mode="Markdown")


@dp.message(Command("get"))
async def cmd_get(message: types.Message):
    """Получить конспект по номеру из /history."""
    try:
        lecture_num = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Используй: /get <номер>\nСписок номеров — в /history")
        return

    lectures = get_user_lectures(message.from_user.id, limit=10)

    if lecture_num < 1 or lecture_num > len(lectures):
        await message.answer(f"❌ Лекции с номером {lecture_num} не найдено.")
        return

    lecture = lectures[lecture_num - 1]
    summary = lecture['summary']

    if len(summary) > 4000:
        for i in range(0, len(summary), 4000):
            await message.answer(summary[i:i + 4000], parse_mode="Markdown")
    else:
        await message.answer(summary, parse_mode="Markdown")

async def main():
    init_db()
    if PROXY_URL and PROXY_URL.startswith("socks5"):
        connector = ProxyConnector.from_url(PROXY_URL)
        session = AiohttpSession(session=ClientSession(connector=connector))
    else:
        session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else AiohttpSession()

    global bot  # Делаем bot глобальной, чтобы handle_audio мог его использовать для download
    bot = Bot(token=BOT_TOKEN, session=session)

    print("✅ Бот успешно запущен и подключен к Telegram!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())