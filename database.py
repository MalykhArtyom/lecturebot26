import sqlite3
from datetime import datetime, timedelta
from typing import Optional

# Путь к файлу БД
DB_PATH = "lecture_bot.db"


def get_connection() -> sqlite3.Connection:
    """Возвращает подключение к БД."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row  # Чтобы получать результаты как словари
    return conn


def init_db():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            telegram_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            lectures_count INTEGER DEFAULT 0,
            purchased_lectures INTEGER DEFAULT 0
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS lectures (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT,
            duration INTEGER,
            transcript TEXT,
            summary TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(telegram_id)
        )
    """)

    conn.commit()
    conn.close()
    print("✅ База данных инициализирована")


# ========== РАБОТА С ПОЛЬЗОВАТЕЛЯМИ ==========

def get_or_create_user(telegram_id: int, username: Optional[str] = None) -> dict:
    """
    Получает пользователя или создаёт нового.
    Возвращает словарь с данными пользователя.
    """
    conn = get_connection()
    cursor = conn.cursor()

    # Пытаемся найти пользователя
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()

    if user:
        # Обновляем username, если он изменился
        if username and user['username'] != username:
            cursor.execute(
                "UPDATE users SET username = ? WHERE telegram_id = ?",
                (username, telegram_id)
            )
            conn.commit()
    else:
        # Создаём нового пользователя
        cursor.execute(
            """INSERT INTO users (telegram_id, username) 
               VALUES (?, ?)""",
            (telegram_id, username)
        )
        conn.commit()
        cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
        user = cursor.fetchone()

    conn.close()
    return dict(user)


def can_process_lecture(telegram_id: int) -> tuple[bool, str]:
    user = get_user(telegram_id)
    if not user:
        return False, "Пользователь не найден"

    if user['lectures_count'] < 5:
        return True, ""

    if user['purchased_lectures'] > 0:
        return True, ""

    return False, (
        "📊 Бесплатный лимит исчерпан!\n"
        "💎 Купите пакет лекций, чтобы продолжить."
    )


def get_user(telegram_id: int) -> Optional[dict]:
    """Получает пользователя по telegram_id."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,))
    user = cursor.fetchone()
    conn.close()
    return dict(user) if user else None


def increment_lecture_count(telegram_id: int):
    """Увеличивает счётчик обработанных лекций."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET lectures_count = lectures_count + 1 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()


def upgrade_to_premium(telegram_id: int, days: int = 30):
    """Выдаёт премиум-подписку на указанное количество дней."""
    expires = datetime.now() + timedelta(days=days)
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE users 
           SET subscription = 'premium', subscription_expires = ? 
           WHERE telegram_id = ?""",
        (expires.isoformat(), telegram_id)
    )
    conn.commit()
    conn.close()


def downgrade_to_free(telegram_id: int):
    """Переводит пользователя в free-статус."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """UPDATE users 
           SET subscription = 'free', subscription_expires = NULL 
           WHERE telegram_id = ?""",
        (telegram_id,)
    )
    conn.commit()
    conn.close()


# ========== РАБОТА С ЛЕКЦИЯМИ ==========

def save_lecture(
        telegram_id: int,
        filename: str,
        duration: int,
        transcript: str,
        summary: str
) -> int:
    """
    Сохраняет лекцию в БД. Возвращает ID сохранённой лекции.
    """
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """INSERT INTO lectures (user_id, filename, duration, transcript, summary)
           VALUES (?, ?, ?, ?, ?)""",
        (telegram_id, filename, duration, transcript, summary)
    )
    lecture_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return lecture_id


def get_user_lectures(telegram_id: int, limit: int = 10) -> list:
    """Получает последние N лекций пользователя."""
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        """SELECT * FROM lectures 
           WHERE user_id = ? 
           ORDER BY created_at DESC 
           LIMIT ?""",
        (telegram_id, limit)
    )
    lectures = [dict(row) for row in cursor.fetchall()]
    conn.close()
    return lectures


# ========== СТАТИСТИКА ==========

def get_stats() -> dict:
    """Возвращает общую статистику бота."""
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) as count FROM users")
    total_users = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM users WHERE subscription = 'premium'")
    premium_users = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM lectures")
    total_lectures = cursor.fetchone()['count']

    conn.close()

    return {
        'total_users': total_users,
        'premium_users': premium_users,
        'total_lectures': total_lectures
    }

def spend_purchased_lecture(telegram_id: int):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET purchased_lectures = purchased_lectures - 1 WHERE telegram_id = ?",
        (telegram_id,)
    )
    conn.commit()
    conn.close()