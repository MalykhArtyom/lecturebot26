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
    wait_msg = await message.answer("⏳ Скачиваю аудиофайл...")

    user_id = message.from_user.id
    timestamp = int(time.time())

    original_name = message.audio.file_name or "audio.mp3"
    file_extension = original_name.split('.')[-1]
    unique_filename = f"audio/{user_id}_{timestamp}.{file_extension}"

    try:
        # 1. Скачиваем файл
        await bot.download(
            message.audio.file_id,
            destination=unique_filename
        )

        await wait_msg.edit_text("✅ Файл сохранен!\n🔄 Транскрибирую аудио в текст...")

        # 2. Вызываем транскрибацию
        transcript_text = await transcribe_audio_async(unique_filename)

        # 3. Отправляем результат пользователю
        if len(transcript_text) > 4000:  # Telegram ограничивает длину сообщения
            # Если текст очень длинный, разбиваем на части
            for i in range(0, len(transcript_text), 4000):
                await message.answer(transcript_text[i:i + 4000])
        else:
            await message.answer(
                f"📝 **Транскрибация:**\n\n{transcript_text}",
                parse_mode="Markdown"
            )

        # 4. Удаляем временный файл (опционально)
        # os.remove(unique_filename)

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


async def main():
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