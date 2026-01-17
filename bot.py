import asyncio
from aiogram import Bot, Dispatcher, types
from aiogram.filters import CommandStart

# Токен вашего бота
BOT_TOKEN = "7971728560:AAFTv0qYcv8YyaM-rVUcvr7DoThEkvS5LTo"
# Ваш ID или username для пересылки сообщений
ADMIN_ID = 884316429  # Можно использовать и username: "goncharovs7"

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Обработчик команды /start
@dp.message(CommandStart())
async def start_command(message: types.Message):
    await message.answer(
        "Здравствуйте, напишите свой вопрос, администратор с вами свяжется в ближайшее время"
    )

# Обработчик всех остальных сообщений
@dp.message()
async def forward_to_admin(message: types.Message):
    # Формируем информацию о пользователе
    user_info = (
        f"Новое сообщение от пользователя:\n"
        f"ID: {message.from_user.id}\n"
        f"Имя: {message.from_user.first_name}\n"
        f"Фамилия: {message.from_user.last_name}\n"
        f"Username: @{message.from_user.username}"
    )
    
    try:
        # Пересылаем оригинальное сообщение администратору
        await message.forward(chat_id=ADMIN_ID)
        
        # Отправляем информацию о пользователе администратору
        await bot.send_message(chat_id=ADMIN_ID, text=user_info)
        
        # Подтверждаем пользователю, что его вопрос отправлен
        await message.answer("Ваш вопрос передан администратору. Ожидайте ответа.")
        
    except Exception as e:
        print(f"Ошибка при пересылке: {e}")
        await message.answer("Произошла ошибка при отправке вопроса.")

# Запуск бота
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
