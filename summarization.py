import asyncio
import httpx
import json
from config import YANDEX_API_KEY, YANDEX_FOLDER_ID, YANDEX_GPT_MODEL_ID


async def create_summary_with_timestamps(chunks: list) -> str:
    """
    Создает структурированный конспект с таймкодами из распознанных сегментов.

    Args:
        chunks: Список сегментов от SpeechKit, каждый содержит:
            - alternatives[0].text: распознанный текст
            - startTime: время начала (в наносекундах)
            - endTime: время конца (в наносекундах)

    Returns:
        Форматированный конспект с таймкодами
    """
    # Преобразуем чанки в удобный формат
    segments = []
    for chunk in chunks:
        alternatives = chunk.get('alternatives', [])
        if not alternatives:
            continue

        text = alternatives[0].get('text', '').strip()
        if not text:
            continue

        # Получаем время в наносекундах и конвертируем в миллисекунды
        start_ns = chunk.get('startTime', '0')
        end_ns = chunk.get('endTime', '0')

        # Yandex возвращает время в формате "1234567890s" (секунды с точностью)
        start_ms = parse_timestamp(start_ns)
        end_ms = parse_timestamp(end_ns)

        segments.append({
            'text': text,
            'start': start_ms,
            'end': end_ms
        })

    if not segments:
        return "❌ Не удалось распознать текст"

    # Формируем текст для отправки в YandexGPT
    transcript_text = "\n".join([
        f"[{format_time(seg['start'])}] {seg['text']}"
        for seg in segments
    ])

    # Создаем промпт для YandexGPT
    prompt = f"""Ты — эксперт по созданию учебных конспектов. Тебе дана расшифровка лекции с таймкодами.

ЗАДАЧА: Создай подробный структурированный конспект лекции.

ТРЕБОВАНИЯ К ФОРМАТУ:
1. Раздели конспект на логические разделы по темам
2. Для каждого раздела укажи таймкод начала (формат MM:SS)
3. Выдели ключевые термины и их определения
4. Сформулируй основные тезисы каждого раздела
5. В конце добавь раздел "Ключевые выводы" с 3-5 главными мыслями лекции
6. Используй markdown-форматирование для удобства чтения

СТРУКТУРА КОНСПЕКТА:
📚 ЛЕКЦИЯ: [краткое название темы]
⏱ Длительность: [общее время]

📖 [MM:SS] - [MM:SS] | [Название раздела 1]
[Краткое содержание раздела с основными тезисами]

📖 [MM:SS] - [MM:SS] | [Название раздела 2]
[Краткое содержание раздела]

...

🔑 КЛЮЧЕВЫЕ ТЕРМИНЫ:
• **Термин 1** — определение
• **Термин 2** — определение

📝 ГЛАВНЫЕ ВЫВОДЫ:
1. [Вывод 1]
2. [Вывод 2]
3. [Вывод 3]

ТЕКСТ ЛЕКЦИИ:
{transcript_text}

СОЗДАЙ КОНСПЕКТ:"""

    # Отправляем в YandexGPT
    summary = await call_yandexgpt(prompt)

    return summary


def parse_timestamp(timestamp_str: str) -> int:
    """
    Парсит временную метку от Yandex SpeechKit.
    Формат: "123.456s" (секунды с дробной частью)
    Возвращает миллисекунды.
    """
    try:
        # Убираем 's' в конце и конвертируем в float
        seconds = float(timestamp_str.rstrip('s'))
        return int(seconds * 1000)  # Конвертируем в миллисекунды
    except:
        return 0


def format_time(milliseconds: int) -> str:
    """
    Форматирует миллисекунды в MM:SS
    """
    total_seconds = milliseconds // 1000
    minutes = total_seconds // 60
    seconds = total_seconds % 60
    return f"{minutes:02d}:{seconds:02d}"


async def call_yandexgpt(prompt: str) -> str:
    """
    Отправляет промпт в YandexGPT и возвращает ответ.
    """
    url = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"

    headers = {
        "Authorization": f"Api-Key {YANDEX_API_KEY}",
        "x-folder-id": YANDEX_FOLDER_ID,
        "Content-Type": "application/json"
    }

    payload = {
        "modelUri": f"gpt://{YANDEX_FOLDER_ID}/{YANDEX_GPT_MODEL_ID}",
        "completionOptions": {
            "stream": False,
            "temperature": 0.3,  # Низкая температура для точности
            "maxTokens": "2000"  # Максимальная длина ответа
        },
        "messages": [
            {
                "role": "user",
                "text": prompt
            }
        ]
    }

    print("🧠 Отправляю текст в YandexGPT для создания конспекта...")

    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                url,
                headers=headers,
                json=payload
            )

        print(f"📡 Ответ YandexGPT: {response.status_code}")

        if response.status_code != 200:
            raise Exception(f"Ошибка YandexGPT: {response.status_code} - {response.text}")

        result = response.json()

        # Извлекаем текст из ответа
        alternatives = result.get('result', {}).get('alternatives', [])
        if alternatives:
            return alternatives[0].get('message', {}).get('text', '')
        else:
            raise Exception(f"Не получен ответ от YandexGPT: {result}")

    except Exception as e:
        raise Exception(f"Ошибка вызова YandexGPT: {e}")