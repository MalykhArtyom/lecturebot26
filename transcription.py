import asyncio
import httpx
import time
import os
import json
import boto3
from botocore.config import Config
from config import (
    YANDEX_API_KEY, YANDEX_FOLDER_ID,
    S3_ACCESS_KEY, S3_SECRET_KEY, S3_BUCKET_NAME
)


def upload_to_s3(file_path: str) -> str:
    """
    Загружает файл в Yandex Object Storage и возвращает публичную ссылку.
    """
    # Создаем клиент S3 для Yandex Cloud
    s3_client = boto3.client(
        's3',
        endpoint_url='https://storage.yandexcloud.net',
        aws_access_key_id=S3_ACCESS_KEY,
        aws_secret_access_key=S3_SECRET_KEY,
        config=Config(signature_version='s3v4')
    )

    # Уникальное имя файла в бакете
    s3_key = f"audio/{os.path.basename(file_path)}"

    print(f"📤 Загружаю файл в бакет {S3_BUCKET_NAME}...")

    # Загружаем файл
    s3_client.upload_file(
        Filename=file_path,
        Bucket=S3_BUCKET_NAME,
        Key=s3_key,
        ExtraArgs={'ContentType': 'audio/mpeg'}
    )

    # Формируем публичную ссылку
    public_url = f"https://{S3_BUCKET_NAME}.storage.yandexcloud.net/{s3_key}"
    print(f"✅ Файл загружен. Ссылка: {public_url}")

    return public_url


async def transcribe_audio_async(file_path: str) -> dict:
    """
    Асинхронная транскрибация. Возвращает чанки с таймкодами.
    """
    if not os.path.exists(file_path):
        raise Exception(f"Файл не найден: {file_path}")

    file_size = os.path.getsize(file_path)
    print(f"📁 Файл: {file_path}")
    print(f"📏 Размер: {file_size / 1024 / 1024:.2f} МБ")

    # 1. Загружаем файл в Object Storage
    file_url = upload_to_s3(file_path)

    # 2. Отправляем ссылку в SpeechKit
    url = "https://transcribe.api.cloud.yandex.net/speech/stt/v2/longRunningRecognize"

    payload = {
        "config": {
            "specification": {
                "languageCode": "ru-RU",
                "audioEncoding": "MP3",
                "sampleRateHertz": 44100,
                "profanityFilter": False,
                "literatureText": False
            }
        },
        "audio": {
            "uri": file_url
        }
    }

    print("🔄 Отправляю ссылку в SpeechKit...")

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                url,
                headers={
                    "Authorization": f"Api-Key {YANDEX_API_KEY}",
                    "x-folder-id": YANDEX_FOLDER_ID,
                    "Content-Type": "application/json"
                },
                json=payload
            )

        print(f"📡 Ответ сервера: {response.status_code}")

        if response.status_code != 200:
            raise Exception(f"Ошибка SpeechKit: {response.status_code} - {response.text}")

        result = response.json()
        operation_id = result.get('id')

        if not operation_id:
            raise Exception(f"Не получен ID операции: {result}")

        print(f"✅ Операция создана. ID: {operation_id}")
        print("⏳ Ожидаю завершения распознавания...")

        # Возвращаем чанки с таймкодами
        return await poll_operation_async(operation_id)

    except Exception as e:
        raise Exception(f"Ошибка транскрибации: {e}")


async def poll_operation_async(operation_id: str) -> dict:
    """
    Проверяет статус операции и возвращает чанки с таймкодами.
    """
    url = f"https://operation.api.cloud.yandex.net/operations/{operation_id}"

    max_attempts = 120
    attempt = 0

    async with httpx.AsyncClient(timeout=30.0) as client:
        while attempt < max_attempts:
            attempt += 1

            response = await client.get(
                url,
                headers={
                    "Authorization": f"Api-Key {YANDEX_API_KEY}",
                    "x-folder-id": YANDEX_FOLDER_ID
                }
            )

            if response.status_code != 200:
                raise Exception(f"Ошибка проверки статуса: {response.status_code}")

            result = response.json()
            done = result.get('done', False)

            if done:
                if 'error' in result:
                    raise Exception(f"Ошибка распознавания: {result['error']}")

                response_result = result.get('response', {})
                chunks = response_result.get('chunks', [])

                # Возвращаем чанки целиком (с таймкодами), а не просто текст
                return {
                    'chunks': chunks,
                    'success': True
                }

            if attempt % 6 == 0:
                print(f"  ⏳ Проверка #{attempt}...")

            await asyncio.sleep(5)

    raise Exception("Превышено время ожидания (10 минут)")

    raise Exception("Превышено время ожидания (10 минут)")