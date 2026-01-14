import logging
import sqlite3
import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ForumTopic
from telegram.ext import (
	Application, CommandHandler, MessageHandler, filters,
	CallbackQueryHandler, ContextTypes, CallbackContext
)

# Настройки бота

GROUP_CHAT_ID = -1003588770543
ADMIN_IDS = [884316429]
BOT_USERNAME = "studio79_bot"

# Маппинг параметров услуг
SERVICE_MAPPING = {
	'service_product_cards': 'Карточки товаров',
	'service_photo_editing': 'Фотомонтаж и ретушь',
	'service_reels_editing': 'Монтаж Reels и Shorts',
	'service_videographics': 'Видеографика',
	'service_preview': 'Превью для видео',
	'service_covers': 'Обложки каналов'
}

# Настройка логирования
logging.basicConfig(
	format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
	level=logging.INFO
)
logger = logging.getLogger(__name__)

# Инициализация базы данных
def init_db():
	conn = sqlite3.connect('bot_database.db')
	cursor = conn.cursor()
	
	# Таблица пользователей
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS users (
			user_id INTEGER PRIMARY KEY,
			username TEXT,
			first_name TEXT,
			last_name TEXT,
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
		)
	''')
	
	# Таблица тредов (диалогов)
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS threads (
			thread_id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER,
			forum_topic_id INTEGER,  -- ID форум-топика в группе
			forum_topic_message_id INTEGER,  -- ID первого сообщения в топике
			selected_service TEXT,  -- Выбранная услуга с сайта
			first_message_sent BOOLEAN DEFAULT FALSE,  -- Было ли отправлено первое сообщение с услугой
			status TEXT DEFAULT 'active',
			created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (user_id) REFERENCES users (user_id)
		)
	''')
	
	# Таблица сообщений
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS messages (
			message_id INTEGER PRIMARY KEY AUTOINCREMENT,
			thread_id INTEGER,
			user_id INTEGER,
			group_message_id INTEGER,  -- ID сообщения в группе
			user_message_id INTEGER,   -- ID сообщения у пользователя
			direction TEXT,  -- 'user_to_admin' или 'admin_to_user'
			message_text TEXT,
			message_type TEXT,  -- 'text', 'photo', 'document', etc.
			file_id TEXT,
			sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			FOREIGN KEY (thread_id) REFERENCES threads (thread_id),
			FOREIGN KEY (user_id) REFERENCES users (user_id)
		)
	''')
	
	# Таблица статистики переходов с сайта
	cursor.execute('''
		CREATE TABLE IF NOT EXISTS site_referrals (
			id INTEGER PRIMARY KEY AUTOINCREMENT,
			user_id INTEGER,
			service_param TEXT,
			service_name TEXT,
			clicked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
			created_thread BOOLEAN DEFAULT FALSE,
			thread_id INTEGER,
			FOREIGN KEY (user_id) REFERENCES users (user_id)
		)
	''')
	
	conn.commit()
	conn.close()

# Функции для работы с базой данных
class Database:
	@staticmethod
	def get_connection():
		return sqlite3.connect('bot_database.db')
	
	@staticmethod
	def add_user(user_id: int, username: str, first_name: str, last_name: str = ""):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT OR REPLACE INTO users (user_id, username, first_name, last_name)
			VALUES (?, ?, ?, ?)
		''', (user_id, username, first_name, last_name))
		conn.commit()
		conn.close()
	
	@staticmethod
	def create_thread(user_id: int, forum_topic_id: int, forum_topic_message_id: int, selected_service: str = None) -> int:
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO threads (user_id, forum_topic_id, forum_topic_message_id, selected_service)
			VALUES (?, ?, ?, ?)
		''', (user_id, forum_topic_id, forum_topic_message_id, selected_service))
		thread_id = cursor.lastrowid
		conn.commit()
		conn.close()
		return thread_id
	
	@staticmethod
	def get_user_thread(user_id: int) -> Optional[Dict]:
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			SELECT t.*, u.username, u.first_name 
			FROM threads t
			JOIN users u ON t.user_id = u.user_id
			WHERE t.user_id = ? AND t.status = 'active'
			ORDER BY t.created_at DESC
			LIMIT 1
		''', (user_id,))
		
		row = cursor.fetchone()
		conn.close()
		
		if row:
			columns = ['thread_id', 'user_id', 'forum_topic_id', 'forum_topic_message_id',
					  'selected_service', 'first_message_sent', 'status', 'created_at', 'username', 'first_name']
			return dict(zip(columns, row))
		return None
	
	@staticmethod
	def get_thread_by_forum_topic(forum_topic_id: int) -> Optional[Dict]:
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			SELECT t.*, u.username, u.first_name 
			FROM threads t
			JOIN users u ON t.user_id = u.user_id
			WHERE t.forum_topic_id = ?
		''', (forum_topic_id,))
		
		row = cursor.fetchone()
		conn.close()
		
		if row:
			columns = ['thread_id', 'user_id', 'forum_topic_id', 'forum_topic_message_id',
					  'selected_service', 'first_message_sent', 'status', 'created_at', 'username', 'first_name']
			return dict(zip(columns, row))
		return None
	
	@staticmethod
	def add_message(thread_id: int, user_id: int, direction: str, message_text: str, 
				   message_type: str, group_message_id: int = None, user_message_id: int = None, file_id: str = None):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO messages (thread_id, user_id, direction, message_text, 
								message_type, group_message_id, user_message_id, file_id)
			VALUES (?, ?, ?, ?, ?, ?, ?, ?)
		''', (thread_id, user_id, direction, message_text, message_type, 
			  group_message_id, user_message_id, file_id))
		conn.commit()
		conn.close()
	
	@staticmethod
	def mark_first_message_sent(thread_id: int):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE threads SET first_message_sent = TRUE WHERE thread_id = ?
		''', (thread_id,))
		conn.commit()
		conn.close()
	
	@staticmethod
	def close_thread(thread_id: int):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE threads SET status = 'closed' WHERE thread_id = ?
		''', (thread_id,))
		conn.commit()
		conn.close()
	
	@staticmethod
	def get_all_active_threads():
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			SELECT t.*, u.username, u.first_name 
			FROM threads t
			JOIN users u ON t.user_id = u.user_id
			WHERE t.status = 'active'
			ORDER BY t.created_at DESC
		''')
		
		rows = cursor.fetchall()
		conn.close()
		
		if rows:
			columns = ['thread_id', 'user_id', 'forum_topic_id', 'forum_topic_message_id',
					  'selected_service', 'first_message_sent', 'status', 'created_at', 'username', 'first_name']
			return [dict(zip(columns, row)) for row in rows]
		return []
	
	@staticmethod
	def add_site_referral(user_id: int, service_param: str, service_name: str):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO site_referrals (user_id, service_param, service_name)
			VALUES (?, ?, ?)
		''', (user_id, service_param, service_name))
		conn.commit()
		conn.close()
	
	@staticmethod
	def update_referral_with_thread(referral_id: int, thread_id: int):
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE site_referrals 
			SET created_thread = TRUE, thread_id = ?
			WHERE id = ?
		''', (thread_id, referral_id))
		conn.commit()
		conn.close()

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user = update.effective_user
	logger.info(f"Пользователь {user.id} ({user.username}) запустил бота с аргументами: {context.args}")
	
	Database.add_user(user.id, user.username or "", user.first_name, user.last_name or "")
	
	# Проверяем наличие параметра start (из ссылки с сайта)
	args = context.args
	service_name = None
	service_param = None
	
	if args and len(args) > 0:
		service_param = args[0]
		service_name = SERVICE_MAPPING.get(service_param)
		
		# Сохраняем переход с сайта в статистику
		if service_name:
			Database.add_site_referral(user.id, service_param, service_name)
			logger.info(f"Переход с сайта: пользователь {user.id}, услуга {service_param} -> {service_name}")
	
	# Сохраняем выбранную услугу в контекст пользователя
	if service_name:
		context.user_data['selected_service'] = service_name
		context.user_data['service_param'] = service_param
		
		welcome_text = (
			f"🎨 *Студия 79 | {service_name}*\n\n"
			f"Отлично! Вы выбрали услугу: *{service_name}*\n\n"
			f"📋 *Что дальше?*\n"
			f"1. Опишите подробно вашу задачу\n"
			f"2. Прикрепите материалы (фото/видео) если есть\n"
			f"3. Укажите сроки и пожелания\n"
			f"4. Мы оценим работу и свяжемся с вами\n\n"
			f"💬 *Просто напишите сообщение ниже, чтобы начать общение:*"
		)
		
		keyboard = [
			[InlineKeyboardButton("📋 Описать задачу", callback_data="describe_task")],
			[InlineKeyboardButton("💬 Начать диалог", callback_data="start_chat")]
		]
		reply_markup = InlineKeyboardMarkup(keyboard)
		
		try:
			await update.message.reply_text(
				welcome_text, 
				parse_mode='Markdown',
				reply_markup=reply_markup
			)
		except Exception as e:
			logger.error(f"Ошибка при отправке приветствия: {e}")
			# Попробуем отправить без форматирования
			await update.message.reply_text(
				f"Студия 79 | {service_name}\n\n"
				f"Отлично! Вы выбрали услугу: {service_name}\n\n"
				f"Что дальше?\n"
				f"1. Опишите подробно вашу задачу\n"
				f"2. Прикрепите материалы (фото/видео) если есть\n"
				f"3. Укажите сроки и пожелания\n"
				f"4. Мы оценим работу и свяжемся с вами\n\n"
				f"Просто напишите сообщение ниже, чтобы начать общение:",
				reply_markup=reply_markup
			)
	else:
		# Обычное приветствие
		welcome_text = (
			"👋 *Добро пожаловать в Студии 79!*\n\n"
			"🎨 *Профессиональный фото и видеомонтаж:*\n"
			"• Превью для видео\n"
			"• Обложки каналов\n"
			"• Фотомонтаж и ретушь\n"
			"• Монтаж рилсов и шорт\n"
			"• Видеографика\n"
			"• Карточки товаров\n\n"
			"📋 *Как это работает:*\n"
			"1. Вы выбираете услугу на сайте или здесь\n"
			"2. Описываете задачу\n"
			"3. Мы создаем заявку и связываем вас с исполнителем\n"
			"4. Вы получаете результат и при необходимости правки\n\n"
			"💬 *Доступные команды:*\n"
			"/start - Начать диалог\n"
			"/help - Помощь\n"
			"/services - Посмотреть услуги\n"
			"/status - Статус вашего заказа\n"
			"/website - Перейти на сайт\n\n"
			"✏️ *Напишите сообщение или выберите услугу:*"
		)
		
		keyboard = [
			[InlineKeyboardButton("🌐 Выбрать услугу на сайте", url="https://studio79.ru")],
			[InlineKeyboardButton("🎨 Посмотреть услуги", callback_data="show_services")]
		]
		reply_markup = InlineKeyboardMarkup(keyboard)
		
		try:
			await update.message.reply_text(
				welcome_text, 
				parse_mode='Markdown',
				reply_markup=reply_markup
			)
		except Exception as e:
			logger.error(f"Ошибка при отправке обычного приветствия: {e}")
			await update.message.reply_text(
				"Добро пожаловать в Студии 79!\n\n"
				"Профессиональный фото и видеомонтаж.\n\n"
				"Доступные команды:\n"
				"/start - Начать диалог\n"
				"/help - Помощь\n"
				"/services - Посмотреть услуги\n"
				"/status - Статус вашего заказа\n"
				"/website - Перейти на сайте\n\n"
				"Напишите сообщение или выберите услугу:",
				reply_markup=reply_markup
			)

# Команда /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	help_text = (
		"🤖 *Помощь по использованию бота*\n\n"
		"🎨 *Назначение бота:*\n"
		"Этот бот помогает заказать услуги фото и видеомонтажа в Студии 79\n\n"
		"📋 *Как это работает:*\n"
		"1. Вы выбираете услугу на сайте или через команду /services\n"
		"2. Пишете сообщение с описанием задачи\n"
		"3. Бот создает заявку для наших специалистов\n"
		"4. Администраторы отвечают вам в этом чате\n"
		"5. Вы обсуждаете детали и получаете результат\n\n"
		"💬 *Доступные команды:*\n"
		"/start - Начать диалог (с параметром услуги)\n"
		"/help - Эта справка\n"
		"/services - Посмотреть все услуги\n"
		"/status - Проверить статус заказа\n"
		"/website - Перейти на сайт\n"
		"/close - Закрыть диалог (для админов)\n\n"
		"📎 *Что можно отправить:*\n"
		"✅ Текстовые сообщения\n"
		"✅ Фотографии\n"
		"✅ Документы\n"
		"✅ Видео\n"
		"✅ Аудио\n\n"
		"⏰ *Время ответа:*\n"
		"Мы отвечаем в рабочее время в течение 15-30 минут!"
	)
	
	keyboard = [
		[InlineKeyboardButton("🌐 Перейти на сайт", url="https://studio79.ru")],
		[InlineKeyboardButton("🎨 Выбрать услугу", callback_data="show_services")]
	]
	reply_markup = InlineKeyboardMarkup(keyboard)
	
	await update.message.reply_text(help_text, parse_mode='Markdown', reply_markup=reply_markup)

# Команда /services
async def services_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	services_text = (
		"🎨 *Наши услуги и цены:*\n\n"
		
		"🛒 *1. Карточки товаров* - от 3490₽\n"
		"   Продающие карточки для Wildberries, Ozon, Яндекс.Маркет\n"
		f"   [/start service_product_cards](https://t.me/{BOT_USERNAME}?start=service_product_cards)\n\n"
		
		"✨ *2. Фотомонтаж и ретушь* - от 1490₽\n"
		"   Удаление объектов, ретушь фото, коллажи\n"
		f"   [/start service_photo_editing](https://t.me/{BOT_USERNAME}?start=service_photo_editing)\n\n"
		
		"🎬 *3. Монтаж Reels и Shorts* - от 4990₽\n"
		"   Динамичные видео для Instagram, TikTok, YouTube\n"
		f"   [/start service_reels_editing](https://t.me/{BOT_USERNAME}?start=service_reels_editing)\n\n"
		
		"📹 *4. Видеографика* - от 9900₽\n"
		"   Анимация, титры, интро/аутро для видео\n"
		f"   [/start service_videographics](https://t.me/{BOT_USERNAME}?start=service_videographics)\n\n"
		
		"▶️ *5. Превью для видео* - от 1690₽\n"
		"   Цепляющие превью для YouTube, VK, TikTok\n"
		f"   [/start service_preview](https://t.me/{BOT_USERNAME}?start=service_preview)\n\n"
		
		"📺 *6. Обложки каналов* - от 2490₽\n"
		"   Запоминающиеся обложки для YouTube, Telegram, VK\n"
		f"   [/start service_covers](https://t.me/{BOT_USERNAME}?start=service_covers)\n\n"
		
		"🌐 *Или выберите услугу на сайте:* https://studio79.ru"
	)
	
	keyboard = [
		[
			InlineKeyboardButton("🛒 Карточки товаров", callback_data="service_product_cards"),
			InlineKeyboardButton("✨ Фотомонтаж", callback_data="service_photo_editing")
		],
		[
			InlineKeyboardButton("🎬 Монтаж рилсов", callback_data="service_reels_editing"),
			InlineKeyboardButton("📹 Видеографика", callback_data="service_videographics")
		],
		[
			InlineKeyboardButton("▶️ Превью", callback_data="service_preview"),
			InlineKeyboardButton("📺 Обложки", callback_data="service_covers")
		],
		[InlineKeyboardButton("🌐 Перейти на сайт", url="https://studio79.ru")]
	]
	reply_markup = InlineKeyboardMarkup(keyboard)
	
	await update.message.reply_text(
		services_text,
		parse_mode='Markdown',
		reply_markup=reply_markup,
		disable_web_page_preview=True
	)

# Команда /status
async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	thread = Database.get_user_thread(user_id)
	
	if thread:
		selected_service = thread.get('selected_service', 'не указана')
		status_text = (
			f"📋 *Статус вашего обращения*\n\n"
			f"*Номер обращения:* #{thread['thread_id']}\n"
			f"*Услуга:* {selected_service}\n"
			f"*Создано:* {thread['created_at'][:16]}\n"
			f"*Статус:* {'✅ Активно' if thread['status'] == 'active' else '❌ Закрыто'}\n\n"
			"Администраторы уже уведомлены о вашем сообщении.\n"
			"Ожидайте ответа в ближайшее время!"
		)
	else:
		status_text = (
			"📭 *У вас нет активных обращений*\n\n"
			"Чтобы начать, выберите услугу:\n"
			"• На сайте: https://studio79.ru\n"
			"• Через команду /services\n"
			"• Или просто напишите сообщение с описанием задачи"
		)
	
	keyboard = [[InlineKeyboardButton("🎨 Выбрать услугу", callback_data="show_services")]]
	reply_markup = InlineKeyboardMarkup(keyboard)
	
	await update.message.reply_text(status_text, parse_mode='Markdown', reply_markup=reply_markup)

# Команда /website
async def website_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	keyboard = [
		[InlineKeyboardButton("🌐 Открыть сайт", url="https://studio79.ru")],
		[InlineKeyboardButton("🎨 Посмотреть услуги", callback_data="show_services")],
		[InlineKeyboardButton("💬 Написать сообщение", callback_data="start_chat")]
	]
	reply_markup = InlineKeyboardMarkup(keyboard)
	
	website_text = (
		"🌐 *Наш сайт:* https://studio79.ru\n\n"
		"🎨 *На сайте вы можете:*\n"
		"• Посмотреть все услуги и цены\n"
		"• Увидеть примеры работ в портфолио\n"
		"• Узнать подробнее о процессе работы\n"
		"• Сразу перейти к заказу нужной услуги\n\n"
		"💡 *Совет:*\n"
		"Выберите услугу на сайте и нажмите кнопку 'Заказать в боте' — "
		"вы автоматически перейдете сюда с уже выбранной услугой!"
	)
	
	await update.message.reply_text(
		website_text,
		parse_mode='Markdown',
		reply_markup=reply_markup,
		disable_web_page_preview=True
	)

# Создание нового треда в группе
async def create_forum_topic_for_user(user_id: int, user_name: str, thread_id: int, selected_service: str = None, context: ContextTypes.DEFAULT_TYPE = None):
	try:
		# Формируем название треда: имя пользователя и номер обращения
		topic_name = f"{user_name} | #{thread_id}"
		
		# Добавляем услугу в название, если она есть
		if selected_service:
			# Ограничиваем длину названия (макс. 64 символа для топика)
			service_short = selected_service[:30] if len(selected_service) > 30 else selected_service
			topic_name = f"{user_name} | #{thread_id} | {service_short}"
		
		# Обрезаем название, если оно слишком длинное
		if len(topic_name) > 64:
			topic_name = topic_name[:61] + "..."
		
		# Создаем топик в группе
		try:
			topic = await context.bot.create_forum_topic(
				chat_id=GROUP_CHAT_ID,
				name=topic_name,
				icon_color=0x6C63FF,
				icon_custom_emoji_id=None
			)
		except Exception as e:
			logger.warning(f"Не удалось создать форум-топик: {e}. Используем обычное сообщение.")
			topic = None
		
		# Формируем приветственное сообщение с номером обращения
		welcome_text = f"🎨 *Новый заказ #{thread_id} от клиента*\n\n"
		welcome_text += f"*Пользователь:* {user_name}\n"
		welcome_text += f"*ID:* {user_id}\n"
		
		if selected_service:
			welcome_text += f"*Услуга:* {selected_service}\n"
		
		welcome_text += f"*Время:* {datetime.now().strftime('%H:%M %d.%m.%Y')}\n\n"
		
		if selected_service:
			welcome_text += f"📋 *Ожидание описания задачи по услуге: {selected_service}...*"
		else:
			welcome_text += "📋 *Ожидание описания задачи от клиента...*"
		
		# Отправляем сообщение в группу
		if topic:
			welcome_message = await context.bot.send_message(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=topic.message_thread_id,
				text=welcome_text,
				parse_mode='Markdown'
			)
		else:
			# Если группа не поддерживает треды
			welcome_message = await context.bot.send_message(
				chat_id=GROUP_CHAT_ID,
				text=welcome_text,
				parse_mode='Markdown'
			)
			# Создаем искусственный ID треда
			topic = type('obj', (object,), {'message_thread_id': welcome_message.message_id})()
		
		return topic, welcome_message
		
	except Exception as e:
		logger.error(f"Ошибка при создании треда: {e}")
		return None, None

# Обработка сообщений от пользователей
async def handle_user_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user = update.effective_user
	message = update.message
	user_id = user.id
	
	# Сохраняем пользователя в БД
	Database.add_user(user_id, user.username or "", user.first_name, user.last_name or "")
	
	# Получаем выбранную услугу из context.user_data
	selected_service = context.user_data.get('selected_service')
	
	# Проверяем, есть ли активный тред у пользователя
	thread = Database.get_user_thread(user_id)
	
	# Если треда нет, создаем новый
	if not thread:
		user_name = user.first_name
		if user.username:
			user_name = f"{user.first_name} (@{user.username})"
		elif user.last_name:
			user_name = f"{user.first_name} {user.last_name}"
		
		# Создаем временный тред в БД для получения ID
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			INSERT INTO threads (user_id, forum_topic_id, forum_topic_message_id, selected_service)
			VALUES (?, ?, ?, ?)
		''', (user_id, None, None, selected_service))
		thread_id = cursor.lastrowid
		conn.commit()
		conn.close()
		
		# Создаем тред в группе с thread_id
		topic, welcome_message = await create_forum_topic_for_user(
			user_id, user_name, thread_id, selected_service, context
		)
		
		if not welcome_message:
			# Удаляем временный тред из БД
			conn = Database.get_connection()
			cursor = conn.cursor()
			cursor.execute('DELETE FROM threads WHERE thread_id = ?', (thread_id,))
			conn.commit()
			conn.close()
			
			await message.reply_text(
				"⚠️ Произошла ошибка при создании обращения. "
				"Пожалуйста, попробуйте позже или свяжитесь с администратором."
			)
			return
		
		# Обновляем тред в БД с forum_topic_id и forum_topic_message_id
		forum_topic_id = topic.message_thread_id if hasattr(topic, 'message_thread_id') else welcome_message.message_id
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			UPDATE threads SET forum_topic_id = ?, forum_topic_message_id = ? WHERE thread_id = ?
		''', (forum_topic_id, welcome_message.message_id, thread_id))
		conn.commit()
		conn.close()
		
		# Получаем обновленный тред
		thread = Database.get_user_thread(user_id)
		
		# Формируем уведомление для пользователя
		user_notification = "✅ *Ваше обращение создано!*\n\n"
		user_notification += f"*Номер обращения:* #{thread_id}\n"
		
		if selected_service:
			user_notification += f"*Услуга:* {selected_service}\n"
		
		user_notification += "\n📋 *Что дальше?*\n"
		user_notification += "1. Администратор свяжется с вами в течение 15-30 минут\n"
		user_notification += "2. Обсудите детали и сроки\n"
		user_notification += "3. После согласования приступим к работе\n\n"
		user_notification += "💬 Вы можете продолжать писать сообщения — они добавятся к этому обращению."
		
		await message.reply_text(
			user_notification,
			parse_mode='Markdown',
			reply_to_message_id=message.message_id
		)
	else:
		thread_id = thread['thread_id']
		
		# Если у треда нет услуги, но пользователь выбрал услугу сейчас
		if not thread.get('selected_service') and selected_service:
			# Обновляем услугу в треде
			conn = Database.get_connection()
			cursor = conn.cursor()
			cursor.execute('UPDATE threads SET selected_service = ? WHERE thread_id = ?', (selected_service, thread_id))
			conn.commit()
			conn.close()
			
			# Формируем новое название треда с услугой
			user_name = user.first_name
			if user.username:
				user_name = f"{user.first_name} (@{user.username})"
			elif user.last_name:
				user_name = f"{user.first_name} {user.last_name}"
			
			topic_name = f"{user_name} | #{thread_id} | {selected_service}"
			if len(topic_name) > 64:
				service_short = selected_service[:30] if len(selected_service) > 30 else selected_service
				topic_name = f"{user_name} | #{thread_id} | {service_short}"
				if len(topic_name) > 64:
					topic_name = topic_name[:61] + "..."
			
			# Обновляем название топика
			try:
				await context.bot.edit_forum_topic(
					chat_id=GROUP_CHAT_ID,
					message_thread_id=thread['forum_topic_id'],
					name=topic_name
				)
			except Exception as e:
				logger.error(f"Ошибка при обновлении названия топика: {e}")
			
			# Отправляем сообщение об услуге в тред
			try:
				await context.bot.send_message(
					chat_id=GROUP_CHAT_ID,
					message_thread_id=thread['forum_topic_id'],
					text=f"🎨 *Клиент указал услугу:* {selected_service}",
					parse_mode='Markdown'
				)
			except Exception as e:
				logger.error(f"Ошибка при отправке сообщения об услуге: {e}")
		
		await message.reply_text(
			"✅ Сообщение добавлено к вашему обращению. Администратор увидит его в течение 15 минут.",
			reply_to_message_id=message.message_id
		)
	
	# Проверяем, было ли уже отправлено первое сообщение с услугой
	first_message_sent = thread.get('first_message_sent', False) if thread else False
	
	# Отправляем сообщение пользователя в тред
	try:
		# Если услуга выбрана и это первое сообщение, добавляем информацию об услуге
		message_prefix = ""
		if selected_service and not first_message_sent and thread:
			message_prefix = f"🎨 *Услуга:* {selected_service}\n\n"
			# Отмечаем, что первое сообщение с услугой отправлено
			Database.mark_first_message_sent(thread_id)
		
		# Получаем текущий тред (обновленный)
		thread = Database.get_user_thread(user_id)
		
		if message.text:
			group_reply = await context.bot.send_message(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				text=f"{message_prefix}💬 *Сообщение от клиента:*\n\n{message.text}",
				parse_mode='Markdown'
			)
			message_type = 'text'
			file_id = None
			message_text = message.text
			
		elif message.photo:
			photo = message.photo[-1]
			caption = message.caption or "Фото от клиента"
			group_reply = await context.bot.send_photo(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				photo=photo.file_id,
				caption=f"{message_prefix}📸 *Фото от клиента:*\n\n{caption}",
				parse_mode='Markdown'
			)
			message_type = 'photo'
			file_id = photo.file_id
			message_text = caption or "Фото"
			
		elif message.document:
			group_reply = await context.bot.send_document(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				document=message.document.file_id,
				caption=f"{message_prefix}📎 *Документ от клиента:*\n\n{message.caption or 'Документ'}",
				parse_mode='Markdown'
			)
			message_type = 'document'
			file_id = message.document.file_id
			message_text = message.caption or "Документ"
			
		elif message.video:
			group_reply = await context.bot.send_video(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				video=message.video.file_id,
				caption=f"{message_prefix}🎥 *Видео от клиента:*\n\n{message.caption or 'Видео'}",
				parse_mode='Markdown'
			)
			message_type = 'video'
			file_id = message.video.file_id
			message_text = message.caption or "Видео"
			
		elif message.audio:
			group_reply = await context.bot.send_audio(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				audio=message.audio.file_id,
				caption=f"{message_prefix}🎵 *Аудио от клиента:*\n\n{message.caption or 'Аудио'}",
				parse_mode='Markdown'
			)
			message_type = 'audio'
			file_id = message.audio.file_id
			message_text = message.caption or "Аудио"
			
		else:
			group_reply = await context.bot.send_message(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=thread['forum_topic_id'],
				text=f"{message_prefix}📨 *Сообщение от клиента (тип: {message.content_type})*",
				parse_mode='Markdown'
			)
			message_type = message.content_type
			file_id = None
			message_text = f"Сообщение типа: {message.content_type}"
		
		# Сохраняем сообщение в БД
		Database.add_message(
			thread_id=thread_id,
			user_id=user_id,
			direction='user_to_admin',
			message_text=message_text,
			message_type=message_type,
			group_message_id=group_reply.message_id,
			user_message_id=message.message_id,
			file_id=file_id
		)
		
		# Очищаем выбранную услугу из контекста после первого сообщения
		if 'selected_service' in context.user_data:
			del context.user_data['selected_service']
		
	except Exception as e:
		logger.error(f"Ошибка при пересылке сообщения: {e}")
		await message.reply_text(
			"⚠️ Произошла ошибка при отправке сообщения. Попробуйте еще раз."
		)

# Обработка сообщений от администраторов в группе
async def handle_group_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
	message = update.message
	user_id = update.effective_user.id
	
	# Проверяем, что сообщение из нужной группы
	if message.chat.id != GROUP_CHAT_ID:
		return
	
	# Игнорируем сообщения от самого бота
	if message.from_user and message.from_user.is_bot:
		return
	
	# Проверяем, что от администратора
	if user_id not in ADMIN_IDS:
		return
	
	# Проверяем, находится ли сообщение в треде
	if not message.message_thread_id:
		return
	
	# Ищем тред по ID форум-топика
	thread = Database.get_thread_by_forum_topic(message.message_thread_id)
	
	if not thread:
		return
	
	# Проверяем, не является ли это ответом на служебное сообщение от бота
	if message.text and ("от клиента" in message.text.lower() or "клиента" in message.text.lower()):
		return
	
	# Игнорируем служебные сообщения
	if message.text and (message.text.startswith("✅") or message.text.startswith("❌")):
		return
	
	# Отправляем сообщение клиенту
	try:
		client_user_id = thread['user_id']
		
		# Добавляем информацию об услуге в первый ответ администратора (если услуга есть)
		message_prefix = ""
		selected_service = thread.get('selected_service')
		if selected_service:
			# Получаем все сообщения от администраторов в этом треде
			conn = Database.get_connection()
			cursor = conn.cursor()
			cursor.execute('''
				SELECT COUNT(*) FROM messages 
				WHERE thread_id = ? AND direction = 'admin_to_user'
			''', (thread['thread_id'],))
			admin_message_count = cursor.fetchone()[0]
			conn.close()
			
			# Если это первое сообщение от администратора в этом треде
			if admin_message_count == 0:
				message_prefix = f"🎨 *Услуга:* {selected_service}\n\n"
		
		if message.text:
			await context.bot.send_message(
				chat_id=client_user_id,
				text=f"{message_prefix}👨‍💼 *Ответ от администратора:*\n\n{message.text}",
				parse_mode='Markdown'
			)
			message_type = 'text'
			message_text = message.text
			file_id = None
			
		elif message.photo:
			photo = message.photo[-1]
			caption = message.caption or "Ответ от администратора"
			await context.bot.send_photo(
				chat_id=client_user_id,
				photo=photo.file_id,
				caption=f"{message_prefix}👨‍💼 *Ответ от администратора:*\n\n{caption}",
				parse_mode='Markdown'
			)
			message_type = 'photo'
			message_text = caption or "Фото"
			file_id = photo.file_id
			
		elif message.document:
			await context.bot.send_document(
				chat_id=client_user_id,
				document=message.document.file_id,
				caption=f"{message_prefix}👨‍💼 *Ответ от администратора:*\n\n{message.caption or 'Документ'}",
				parse_mode='Markdown'
			)
			message_type = 'document'
			message_text = message.caption or "Документ"
			file_id = message.document.file_id
			
		elif message.video:
			await context.bot.send_video(
				chat_id=client_user_id,
				video=message.video.file_id,
				caption=f"{message_prefix}👨‍💼 *Ответ от администратора:*\n\n{message.caption or 'Видео'}",
				parse_mode='Markdown'
			)
			message_type = 'video'
			message_text = message.caption or "Видео"
			file_id = message.video.file_id
			
		elif message.audio:
			await context.bot.send_audio(
				chat_id=client_user_id,
				audio=message.audio.file_id,
				caption=f"{message_prefix}👨‍💼 *Ответ от администратора:*\n\n{message.caption or 'Аудио'}",
				parse_mode='Markdown'
			)
			message_type = 'audio'
			message_text = message.caption or "Аудио"
			file_id = message.audio.file_id
			
		else:
			await message.copy(chat_id=client_user_id)
			message_type = message.content_type
			message_text = f"Сообщение типа: {message.content_type}"
			file_id = None
		
		# Сохраняем сообщение в БД
		Database.add_message(
			thread_id=thread['thread_id'],
			user_id=client_user_id,
			direction='admin_to_user',
			message_text=message_text,
			message_type=message_type,
			group_message_id=message.message_id,
			file_id=file_id
		)
		
		# Отправляем подтверждение
		try:
			confirmation = await message.reply_text("✅ Ответ отправлен клиенту", quote=False)
			await asyncio.sleep(5)
			await confirmation.delete()
		except:
			pass
		
	except Exception as e:
		logger.error(f"Ошибка при отправке ответа клиенту: {e}")
		try:
			await message.reply_text(f"❌ Ошибка: {str(e)[:100]}", quote=False)
		except:
			pass

# Обработка нажатий на кнопки
async def button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
	query = update.callback_query
	await query.answer()
	
	data = query.data
	user_id = query.from_user.id
	
	# Обработка админских кнопок
	if data.startswith("view_thread_") or data.startswith("goto_thread_") or data.startswith("close_thread_") or data == "back_to_threads":
		await admin_button_callback(update, context)
		return
		
	elif data == "show_services":
		services_text = (
			"🎨 *Наши услуги и цены:*\n\n"
			
			"🛒 *1. Карточки товаров* - от 3490₽\n"
			"   Продающие карточки для Wildberries, Ozon, Яндекс.Маркет\n"
			f"   [/start service_product_cards](https://t.me/{BOT_USERNAME}?start=service_product_cards)\n\n"
			
			"✨ *2. Фотомонтаж и ретушь* - от 1490₽\n"
			"   Удаление объектов, ретушь фото, коллажи\n"
			f"   [/start service_photo_editing](https://t.me/{BOT_USERNAME}?start=service_photo_editing)\n\n"
			
			"🎬 *3. Монтаж Reels и Shorts* - от 4990₽\n"
			"   Динамичные видео для Instagram, TikTok, YouTube\n"
			f"   [/start service_reels_editing](https://t.me/{BOT_USERNAME}?start=service_reels_editing)\n\n"
			
			"📹 *4. Видеографика* - от 9900₽\n"
			"   Анимация, титры, интро/аутро для видео\n"
			f"   [/start service_videographics](https://t.me/{BOT_USERNAME}?start=service_videographics)\n\n"
			
			"▶️ *5. Превью для видео* - от 1690₽\n"
			"   Цепляющие превью для YouTube, VK, TikTok\n"
			f"   [/start service_preview](https://t.me/{BOT_USERNAME}?start=service_preview)\n\n"
			
			"📺 *6. Обложки каналов* - от 2490₽\n"
			"   Запоминающиеся обложки для YouTube, Telegram, VK\n"
			f"   [/start service_covers](https://t.me/{BOT_USERNAME}?start=service_covers)\n\n"
			
			"🌐 *Или выберите услугу на сайте:* https://studio79.ru"
		)
		
		keyboard = [
			[
				InlineKeyboardButton("🛒 Карточки товаров", callback_data="service_product_cards"),
				InlineKeyboardButton("✨ Фотомонтаж", callback_data="service_photo_editing")
			],
			[
				InlineKeyboardButton("🎬 Монтаж рилсов", callback_data="service_reels_editing"),
				InlineKeyboardButton("📹 Видеографика", callback_data="service_videographics")
			],
			[
				InlineKeyboardButton("▶️ Превью", callback_data="service_preview"),
				InlineKeyboardButton("📺 Обложки", callback_data="service_covers")
			],
			[InlineKeyboardButton("🌐 Перейти на сайт", url="https://studio79.ru")]
		]
		reply_markup = InlineKeyboardMarkup(keyboard)
		
		await query.edit_message_text(
			services_text,
			parse_mode='Markdown',
			reply_markup=reply_markup,
			disable_web_page_preview=True
		)
		return
		
	elif data == "describe_task":
		await query.edit_message_text(
			"📝 *Опишите вашу задачу:*\n\n"
			"Пожалуйста, напишите сообщение с описанием:\n\n"
			"1. *Что нужно сделать?* (конкретная задача)\n"
			"2. *Какие материалы есть?* (фото, видео, текст)\n"
			"3. *Какие сроки?* (когда нужно получить результат)\n"
			"4. *Особые пожелания?* (стиль, цвет, примеры)\n\n"
			"💬 *Просто напишите сообщение ниже:*",
			parse_mode='Markdown'
		)
		return
		
	elif data == "start_chat":
		await query.edit_message_text(
			"💬 *Начните диалог:*\n\n"
			"Напишите любое сообщение, чтобы начать общение с администратором.\n\n"
			"Мы ответим в течение 15-30 минут в рабочее время.",
			parse_mode='Markdown'
		)
		return
	
	elif data in SERVICE_MAPPING:
		service_name = SERVICE_MAPPING[data]
		context.user_data['selected_service'] = service_name
		context.user_data['service_param'] = data
		
		service_text = (
			f"🎨 *Вы выбрали: {service_name}*\n\n"
			f"Отлично! Теперь опишите вашу задачу.\n\n"
			f"📋 *Что нужно указать:*\n"
			f"• Подробное описание задачи\n"
			f"• Материалы (если есть)\n"
			f"• Сроки выполнения\n"
			f"• Примеры или пожелания\n\n"
			f"💬 *Напишите сообщение с описанием:*"
		)
		
		await query.edit_message_text(
			service_text,
			parse_mode='Markdown'
		)
		return
	
	# Если ни одно условие не сработало
	await query.edit_message_text(
		"❌ Неизвестная команда. Пожалуйста, используйте доступные кнопки.",
		parse_mode='Markdown'
	)

# Админские кнопки
async def admin_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
	query = update.callback_query
	await query.answer()
	
	user_id = query.from_user.id
	if user_id not in ADMIN_IDS:
		await query.edit_message_text("❌ У вас нет прав администратора.")
		return
	
	data = query.data
	
	if data.startswith("view_thread_"):
		thread_id = int(data.split("_")[2])
		
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('''
			SELECT t.*, u.username, u.first_name, u.user_id
			FROM threads t
			JOIN users u ON t.user_id = u.user_id
			WHERE t.thread_id = ?
		''', (thread_id,))
		
		row = cursor.fetchone()
		
		if row:
			thread = {
				'thread_id': row[0],
				'user_id': row[1],
				'forum_topic_id': row[2],
				'forum_topic_message_id': row[3],
				'selected_service': row[4],
				'first_message_sent': row[5],
				'status': row[6],
				'created_at': row[7],
				'username': row[8],
				'first_name': row[9],
				'client_user_id': row[10]
			}
			
			cursor.execute('''
				SELECT direction, message_text, message_type, sent_at
				FROM messages
				WHERE thread_id = ?
				ORDER BY sent_at
				LIMIT 10
			''', (thread_id,))
			
			messages = cursor.fetchall()
			
			thread_info = (
				f"📋 *Информация о обращении #{thread_id}*\n\n"
				f"*Клиент:* {thread['first_name']}\n"
				f"*Username:* @{thread['username'] if thread['username'] else 'нет'}\n"
				f"*ID клиента:* `{thread['client_user_id']}`\n"
				f"*Услуга:* {thread['selected_service'] or 'не указана'}\n"
				f"*Статус:* {thread['status']}\n"
				f"*Создано:* {thread['created_at'][:16]}\n\n"
				f"*Последние сообщения:*\n"
			)
			
			for msg in messages:
				direction, text, msg_type, sent_at = msg
				if direction == 'user_to_admin':
					prefix = "👤 Клиент"
				else:
					prefix = "👨‍💼 Админ"
				
				display_text = text[:50] + "..." if len(text) > 50 else text
				thread_info += f"{prefix}: {display_text}\n"
			
			keyboard = [
				[
					InlineKeyboardButton("📩 Перейти к треду", 
									   callback_data=f"goto_thread_{thread_id}"),
					InlineKeyboardButton("❌ Закрыть тред", callback_data=f"close_thread_{thread_id}")
				],
				[InlineKeyboardButton("🔙 Назад", callback_data="back_to_threads")]
			]
			
			reply_markup = InlineKeyboardMarkup(keyboard)
			await query.edit_message_text(thread_info, parse_mode='Markdown', reply_markup=reply_markup)
		
		conn.close()
	
	elif data.startswith("goto_thread_"):
		thread_id = int(data.split("_")[2])
		
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT forum_topic_id FROM threads WHERE thread_id = ?', (thread_id,))
		result = cursor.fetchone()
		conn.close()
		
		if result:
			forum_topic_id = result[0]
			group_id_str = str(GROUP_CHAT_ID)[4:]
			thread_url = f"https://t.me/c/{group_id_str}/{forum_topic_id}"
			
			keyboard = [
				[InlineKeyboardButton("🔗 Открыть тред в Telegram", url=thread_url)],
				[InlineKeyboardButton("🔙 Назад", callback_data=f"view_thread_{thread_id}")]
			]
			reply_markup = InlineKeyboardMarkup(keyboard)
			await query.edit_message_text(
				f"🔗 Ссылка на тред обращения #{thread_id}:\n{thread_url}",
				reply_markup=reply_markup
			)
	
	elif data.startswith("close_thread_"):
		thread_id = int(data.split("_")[2])
		
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT forum_topic_id, user_id FROM threads WHERE thread_id = ?', (thread_id,))
		result = cursor.fetchone()
		conn.close()
		
		if result:
			forum_topic_id = result[0]
			client_user_id = result[1]
			
			try:
				await context.bot.close_forum_topic(
					chat_id=GROUP_CHAT_ID,
					message_thread_id=forum_topic_id
				)
			except:
				pass
			
			Database.close_thread(thread_id)
			
			try:
				await context.bot.send_message(
					chat_id=client_user_id,
					text="✅ Ваше обращение закрыто администратором. "
						 "Если у вас появятся новые вопросы, просто напишите нам!"
				)
			except:
				pass
			
			await query.edit_message_text(f"✅ Тред #{thread_id} закрыт.")
	
	elif data == "back_to_threads":
		threads = Database.get_all_active_threads()
		
		if not threads:
			await query.edit_message_text("📭 Нет активных обращений.")
			return
		
		keyboard = []
		for thread in threads:
			username = f"@{thread['username']}" if thread['username'] else "без username"
			service = thread.get('selected_service', 'без услуги')
			button_text = f"#{thread['thread_id']} - {thread['first_name']} - {service}"
			callback_data = f"view_thread_{thread['thread_id']}"
			keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
		
		reply_markup = InlineKeyboardMarkup(keyboard)
		
		await query.edit_message_text(
			f"📋 *Активные обращения ({len(threads)}):*",
			parse_mode='Markdown',
			reply_markup=reply_markup
		)

# Команда /admin
async def admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	
	if user_id not in ADMIN_IDS:
		await update.message.reply_text("❌ У вас нет прав администратора.")
		return
	
	threads = Database.get_all_active_threads()
	
	if not threads:
		await update.message.reply_text("📭 Нет активных обращений.")
		return
	
	keyboard = []
	for thread in threads:
		username = f"@{thread['username']}" if thread['username'] else "без username"
		service = thread.get('selected_service', 'без услуги')
		button_text = f"#{thread['thread_id']} - {thread['first_name']} - {service}"
		callback_data = f"view_thread_{thread['thread_id']}"
		keyboard.append([InlineKeyboardButton(button_text, callback_data=callback_data)])
	
	reply_markup = InlineKeyboardMarkup(keyboard)
	
	await update.message.reply_text(
		f"📋 *Активные обращения ({len(threads)}):*",
		parse_mode='Markdown',
		reply_markup=reply_markup
	)

# Команда /close
async def close_thread_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	
	if user_id not in ADMIN_IDS:
		await update.message.reply_text("❌ У вас нет прав администратора.")
		return
	
	if not context.args:
		await update.message.reply_text("Использование: /close <номер треда>")
		return
	
	try:
		thread_id = int(context.args[0])
		
		conn = Database.get_connection()
		cursor = conn.cursor()
		cursor.execute('SELECT forum_topic_id, user_id FROM threads WHERE thread_id = ?', (thread_id,))
		result = cursor.fetchone()
		conn.close()
		
		if not result:
			await update.message.reply_text("❌ Тред не найден.")
			return
		
		forum_topic_id = result[0]
		client_user_id = result[1]
		
		try:
			await context.bot.close_forum_topic(
				chat_id=GROUP_CHAT_ID,
				message_thread_id=forum_topic_id
			)
		except:
			pass
		
		Database.close_thread(thread_id)
		
		try:
			await context.bot.send_message(
				chat_id=client_user_id,
				text="✅ Ваше обращение закрыто администратором. "
					 "Если у вас появятся новые вопросы, просто напишите нам!"
			)
		except:
			pass
		
		await update.message.reply_text(f"✅ Тред #{thread_id} закрыт.")
		
	except ValueError:
		await update.message.reply_text("❌ Неверный номер треда. Используйте: /close <номер>")
	except Exception as e:
		await update.message.reply_text(f"❌ Ошибка: {str(e)}")

# Команда /stats - ИСПРАВЛЕННАЯ ВЕРСИЯ
async def stats_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user_id = update.effective_user.id
	
	if user_id not in ADMIN_IDS:
		await update.message.reply_text("❌ У вас нет прав администратора.")
		return
	
	conn = Database.get_connection()
	cursor = conn.cursor()
	
	cursor.execute('SELECT COUNT(*) FROM users')
	total_users = cursor.fetchone()[0]
	
	cursor.execute('SELECT COUNT(*) FROM threads WHERE status = "active"')
	active_threads = cursor.fetchone()[0]
	
	cursor.execute('SELECT COUNT(*) FROM threads WHERE status = "closed"')
	closed_threads = cursor.fetchone()[0]
	
	cursor.execute('SELECT COUNT(*) FROM messages WHERE direction = "user_to_admin"')
	user_messages = cursor.fetchone()[0]
	
	cursor.execute('SELECT COUNT(*) FROM messages WHERE direction = "admin_to_user"')
	admin_messages = cursor.fetchone()[0]
	
	cursor.execute('SELECT COUNT(*) FROM site_referrals')
	site_referrals = cursor.fetchone()[0]
	
	cursor.execute('SELECT service_name, COUNT(*) as count FROM site_referrals GROUP BY service_name ORDER BY count DESC')
	service_stats = cursor.fetchall()
	
	# Статистика по услугам в тредах
	cursor.execute('SELECT selected_service, COUNT(*) as count FROM threads WHERE selected_service IS NOT NULL GROUP BY selected_service ORDER BY count DESC')
	thread_service_stats = cursor.fetchall()
	
	conn.close()
	
	stats_text = (
		"📊 *Статистика бота*\n\n"
		f"*Всего пользователей:* `{total_users}`\n"
		f"*Активных обращений:* `{active_threads}`\n"
		f"*Закрытых обращений:* `{closed_threads}`\n"
		f"*Сообщений от клиентов:* `{user_messages}`\n"
		f"*Ответов администраторов:* `{admin_messages}`\n"
		f"*Всего сообщений:* `{user_messages + admin_messages}`\n"
		f"*Переходов с сайта:* `{site_referrals}`\n\n"
	)
	
	if service_stats:
		stats_text += "*Статистика по услугам (с сайта):*\n"
		for service, count in service_stats:
			# Экранируем специальные символы Markdown
			service_escaped = service.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
			stats_text += f"• `{service_escaped}`: `{count}`\n"
		stats_text += "\n"
	
	if thread_service_stats:
		stats_text += "*Услуги в активных тредах:*\n"
		for service, count in thread_service_stats:
			if service:  # Проверяем, что услуга не None
				# Экранируем специальные символы Markdown
				service_escaped = service.replace('_', '\\_').replace('*', '\\*').replace('`', '\\`')
				stats_text += f"• `{service_escaped}`: `{count}`\n"
		stats_text += "\n"
	
	stats_text += (
		f"*ID группы:* `{GROUP_CHAT_ID}`\n"
		f"*Имя бота:* @{BOT_USERNAME}\n"
		f"*Администраторы:* `{', '.join(map(str, ADMIN_IDS))}`"
	)
	
	try:
		await update.message.reply_text(stats_text, parse_mode='Markdown')
	except Exception as e:
		# Если все равно возникает ошибка, отправляем без Markdown
		logger.error(f"Ошибка при отправке статистики: {e}")
		stats_text_plain = (
			"📊 Статистика бота\n\n"
			f"Всего пользователей: {total_users}\n"
			f"Активных обращений: {active_threads}\n"
			f"Закрытых обращений: {closed_threads}\n"
			f"Сообщений от клиентов: {user_messages}\n"
			f"Ответов администраторов: {admin_messages}\n"
			f"Всего сообщений: {user_messages + admin_messages}\n"
			f"Переходов с сайта: {site_referrals}\n\n"
		)
		
		if service_stats:
			stats_text_plain += "Статистика по услугам (с сайта):\n"
			for service, count in service_stats:
				stats_text_plain += f"- {service}: {count}\n"
			stats_text_plain += "\n"
		
		if thread_service_stats:
			stats_text_plain += "Услуги в активных тредах:\n"
			for service, count in thread_service_stats:
				if service:
					stats_text_plain += f"- {service}: {count}\n"
			stats_text_plain += "\n"
		
		stats_text_plain += (
			f"ID группы: {GROUP_CHAT_ID}\n"
			f"Имя бота: @{BOT_USERNAME}\n"
			f"Администраторы: {', '.join(map(str, ADMIN_IDS))}"
		)
		
		await update.message.reply_text(stats_text_plain)

# Команда /check для тестирования
async def check_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
	user = update.effective_user
	await update.message.reply_text(
		f"✅ Бот работает!\n"
		f"👤 Пользователь: {user.id}\n"
		f"🤖 Имя бота: @{BOT_USERNAME}\n"
		f"🎨 Сервисы: {len(SERVICE_MAPPING)}\n"
		f"📊 База данных: bot_database.db"
	)

# Основная функция
def main():
	# Инициализируем базу данных
	init_db()
	
	# Создаем приложение
	application = Application.builder().token(BOT_TOKEN).build()
	
	# Обработчики команд с правильным порядком (команда start должна быть первой)
	application.add_handler(CommandHandler("start", start, filters=filters.ChatType.PRIVATE))
	application.add_handler(CommandHandler("help", help_command))
	application.add_handler(CommandHandler("status", status_command))
	application.add_handler(CommandHandler("services", services_command))
	application.add_handler(CommandHandler("website", website_command))
	application.add_handler(CommandHandler("admin", admin_command))
	application.add_handler(CommandHandler("close", close_thread_command))
	application.add_handler(CommandHandler("stats", stats_command))
	application.add_handler(CommandHandler("check", check_command))
	
	# Обработчик кнопок
	application.add_handler(CallbackQueryHandler(button_callback))
	
	# Обработчик сообщений от пользователей
	application.add_handler(MessageHandler(
		filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
		handle_user_message
	))
	
	# Обработчик медиа-сообщений от пользователей
	application.add_handler(MessageHandler(
		(filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO) & filters.ChatType.PRIVATE,
		handle_user_message
	))
	
	# Обработчик сообщений в группе
	application.add_handler(MessageHandler(
		filters.Chat(chat_id=GROUP_CHAT_ID) & 
		(filters.TEXT | filters.PHOTO | filters.Document.ALL | filters.VIDEO | filters.AUDIO) &
		~filters.COMMAND,
		handle_group_message
	))
	
	# Запускаем бота
	print("=" * 50)
	print("🎨 Бот Студии 79 запущен!")
	print(f"🤖 Имя бота: @{BOT_USERNAME}")
	print(f"👥 ID группы: {GROUP_CHAT_ID}")
	print(f"👑 Администраторы: {ADMIN_IDS}")
	print("🌐 Сайт: https://studio79.ru")
	print("=" * 50)
	print("📊 База данных инициализирована")
	print("✅ Бот готов к работе")
	print("=" * 50)
	
	application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
	main()
