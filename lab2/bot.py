import os
import json
import logging
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from telegram import Update, ReplyKeyboardMarkup, ReplyKeyboardRemove
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ConversationHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# Загружаем настройки из .env
load_dotenv()

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATA_FILE = Path(__file__).with_name("feedback.json")

RATING, COMMENT = range(2)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# Чтение отзывов из JSON
def load_feedback():
    if not DATA_FILE.exists():
        return []

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as file:
            data = json.load(file)
            return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError):
        logger.exception("Ошибка чтения отзывов")
        return []


# Сохранение отзывов
def save_feedback(feedback):
    with open(DATA_FILE, "w", encoding="utf-8") as file:
        json.dump(feedback, file, ensure_ascii=False, indent=2)

# Экспорт отзывов в CSV
async def export_reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    feedback = load_feedback()

    if not feedback:
        await update.message.reply_text("Отзывов пока нет.")
        return

    import csv
    import io

    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["user_id", "rating", "comment", "date"],
        extrasaction="ignore",
    )
    writer.writeheader()

    for item in feedback:
        if isinstance(item, dict):
            writer.writerow(item)

    file = io.BytesIO(output.getvalue().encode("utf-8-sig"))
    file.name = "feedback.csv"

    await update.message.reply_document(
        document=file,
        filename="feedback.csv",
        caption="📁 Экспорт отзывов в CSV",
    )


# Поиск отзывов по оценке
async def reviews(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text("⛔ Доступ запрещён.")
        return

    if len(context.args) != 1 or context.args[0] not in ("1", "2", "3", "4", "5"):
        await update.message.reply_text(
            "Укажите оценку от 1 до 5. Например: /reviews 5"
        )
        return

    rating = int(context.args[0])
    matches = [
        item for item in load_feedback()
        if isinstance(item, dict) and item.get("rating") == rating
    ]

    if not matches:
        await update.message.reply_text("Отзывы с такой оценкой не найдены.")
        return

    text = "\n\n".join(
        f"⭐ {rating}/5 — {str(item.get('comment', ''))[:300]}"
        for item in matches[-5:]
    )
    await update.message.reply_text(text)
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Добро пожаловать в Feedback Assistant!\n\n"
        "Здесь вы можете оставить отзыв о качестве обслуживания.\n\n"
        "📝 /feedback — оставить отзыв\n"
        "📊 /stats — статистика (администратор)\n"
        "❓ /help — помощь"
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await start(update, context)


async def feedback_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["1", "2", "3", "4", "5"]]

    await update.message.reply_text(
        "⭐ Оцените качество обслуживания от 1 до 5:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard, resize_keyboard=True, one_time_keyboard=True
        ),
    )
    return RATING


async def receive_rating(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rating = update.message.text.strip()

    if rating not in ("1", "2", "3", "4", "5"):
        await update.message.reply_text("Введите число от 1 до 5.")
        return RATING

    context.user_data["rating"] = int(rating)

    await update.message.reply_text(
        "✍️ Напишите комментарий к вашей оценке:",
        reply_markup=ReplyKeyboardRemove(),
    )
    return COMMENT


async def receive_comment(update: Update, context: ContextTypes.DEFAULT_TYPE):
    comment = update.message.text.strip()

    if not comment:
        await update.message.reply_text("Комментарий не должен быть пустым.")
        return COMMENT

    rating = context.user_data["rating"]

    feedback = load_feedback()
    feedback.append({
        "user_id": update.effective_user.id,
        "rating": rating,
        "comment": comment,
        "date": datetime.now().astimezone().isoformat(timespec="seconds"),
    })

    try:
        save_feedback(feedback)
    except OSError:
        logger.exception("Ошибка сохранения отзыва")
        await update.message.reply_text(
            "Не удалось сохранить отзыв. Попробуйте позже."
        )
        return ConversationHandler.END

    await update.message.reply_text(
        "✅ Спасибо! Ваш отзыв успешно сохранён."
    )

    if ADMIN_ID:
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=(
                    "📩 Новый отзыв!\n\n"
                    f"⭐ Оценка: {rating}/5\n"
                    f"💬 Комментарий: {comment}"
                ),
            )
        except Exception:
            logger.exception("Не удалось уведомить администратора")

    context.user_data.pop("rating", None)
    return ConversationHandler.END


async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        await update.message.reply_text(
            "⛔ У вас нет доступа к статистике."
        )
        return

    feedback = load_feedback()

    if not feedback:
        await update.message.reply_text("📊 Отзывов пока нет.")
        return

    ratings = [
        item["rating"]
        for item in feedback
        if isinstance(item, dict)
        and isinstance(item.get("rating"), int)
        and 1 <= item["rating"] <= 5
    ]

    if not ratings:
        await update.message.reply_text("📊 Корректных оценок пока нет.")
        return

    average = sum(ratings) / len(ratings)

    await update.message.reply_text(
        f"📊 Статистика отзывов\n\n"
        f"Всего отзывов: {len(feedback)}\n"
        f"Средняя оценка: {average:.2f}/5"
    )


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data.pop("rating", None)
    await update.message.reply_text(
        "Сбор отзыва отменён.",
        reply_markup=ReplyKeyboardRemove(),
    )
    return ConversationHandler.END


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    logger.error("Ошибка Telegram-бота: %s", context.error)


def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN отсутствует в файле .env")

    if not ADMIN_ID:
        raise RuntimeError("ADMIN_ID отсутствует в файле .env")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conversation = ConversationHandler(
        entry_points=[CommandHandler("feedback", feedback_start)],
        states={
            RATING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_rating)
            ],
            COMMENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_comment)
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel)],
    )

    app.add_handler(conversation)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("reviews", reviews))
    app.add_handler(CommandHandler("export", export_reviews))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("stats", stats))
    app.add_error_handler(error_handler)

    print("Feedback Assistant запущен!")
    app.run_polling()


if __name__ == "__main__":
    main()

