import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_URL = os.getenv("PROXY_URL")
YANDEX_API_KEY = os.getenv("YANDEX_API_KEY")
YANDEX_FOLDER_ID = os.getenv("YANDEX_FOLDER_ID")

# Object Storage
S3_ACCESS_KEY = os.getenv("S3_ACCESS_KEY")
S3_SECRET_KEY = os.getenv("S3_SECRET_KEY")
S3_BUCKET_NAME = os.getenv("S3_BUCKET_NAME")

# YandexGPT
YANDEX_GPT_MODEL_ID = os.getenv("YANDEX_GPT_MODEL_ID", "yandexgpt-lite/latest")

if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден!")
if not YANDEX_API_KEY:
    raise ValueError("YANDEX_API_KEY не найден!")
if not YANDEX_FOLDER_ID:
    raise ValueError("YANDEX_FOLDER_ID не найден!")
if not S3_ACCESS_KEY or not S3_SECRET_KEY:
    raise ValueError("S3 ключи не найдены!")