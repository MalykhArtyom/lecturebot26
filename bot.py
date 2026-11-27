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
from database import init_db, get_or_create_user, can_process_lecture, save_lecture, increment_lecture_count
from database import get_stats

dp = Dispatcher()

# Убедимся, что папка audio существует
os.makedirs("audio", exist_ok=True)


@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    await message.answer(
        "Привет! Я бот для конспектирования лекций.\n"
        "Отправь мне MP3 файл с лекцией, и я сделаю конспект."
    )


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