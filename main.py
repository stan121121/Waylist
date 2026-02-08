import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

# ════════════════════════════════════════════════════════════════════════════
# ⚙️  НАСТРОЙКА ЛОГИРОВАНИЯ ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),  # Для Railway логов
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# 🔐 КОНФИГУРАЦИЯ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (ДЛЯ RAILWAY)
# ════════════════════════════════════════════════════════════════════════════

# Получение токена из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в переменных окружения!")
    logger.info("📝 На Railway добавьте переменную окружения BOT_TOKEN")
    logger.info("📝 Локально: создайте .env файл с BOT_TOKEN=ваш_токен")
    exit(1)

logger.info("✅ Бот инициализирован, токен получен")

# ════════════════════════════════════════════════════════════════════════════
# 🤖 ИНИЦИАЛИЗАЦИЯ БОТА И ДИСПЕТЧЕРА
# ════════════════════════════════════════════════════════════════════════════

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

# Используем MemoryStorage для Railway
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ════════════════════════════════════════════════════════════════════════════
# 💾 НАСТРОЙКА БАЗЫ ДАННЫХ С ПОДДЕРЖКОЙ VOLUME
# ════════════════════════════════════════════════════════════════════════════

def get_db_path() -> str:
    """Определяет путь к базе данных с учетом Volume в Railway"""
    # Проверяем наличие папки /data (куда монтируется Volume в Railway)
    if os.path.exists('/data'):
        db_dir = '/data'
        logger.info("✅ Обнаружен Volume /data для хранения базы данных")
    else:
        db_dir = '.'  # Локальная папка для разработки
        logger.info("📁 Используется локальная папка для базы данных")
    
    # Создаем папку если не существует
    os.makedirs(db_dir, exist_ok=True)
    
    # Путь к файлу базы данных
    db_path = os.path.join(db_dir, 'waybills.db')
    logger.info(f"📊 Путь к базе данных: {db_path}")
    return db_path

def get_db_connection():
    """Создание подключения к SQLite базе данных"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Инициализация базы данных при старте"""
    try:
        db_path = get_db_path()
        logger.info(f"🔄 Инициализация базы данных по пути: {db_path}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Таблица автомобилей (ДОБАВЛЕНО ПОЛЕ ДЛЯ ПРОСТОЯ)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL,
                idle_rate REAL DEFAULT 2.0,  -- НОВОЕ ПОЛЕ: перерасход в час простоя (л/ч)
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
        
        # Таблица путевых листов
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS waybills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                vehicle_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                date TEXT NOT NULL,
                start_time TEXT,
                end_time TEXT,
                total_hours REAL,
                odo_start REAL,
                odo_end REAL,
                distance REAL,
                fuel_start REAL,
                fuel_end REAL,
                fuel_refuel REAL DEFAULT 0,  -- НОВОЕ ПОЛЕ: заправленное топливо
                fuel_norm REAL,
                fuel_actual REAL,
                overuse REAL DEFAULT 0,
                overuse_hours REAL DEFAULT 0,  -- НОВОЕ ПОЛЕ: часы простоя для расчета перерасхода
                overuse_calculated INTEGER DEFAULT 0,  -- НОВОЕ ПОЛЕ: флаг расчета перерасхода по простому
                economy REAL DEFAULT 0,
                fuel_rate REAL,
                fuel_end_manual INTEGER DEFAULT 0,  -- НОВОЕ: флаг ручного ввода
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
            )
        ''')
        
        # Индексы для улучшения производительности
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_user_date ON waybills(user_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_date ON waybills(vehicle_id, date)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ════════════════════════════════════════════════════════════════════════════
# 📊 КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float, idle_rate: float = 2.0) -> Optional[int]:
        """Добавление нового автомобиля (ДОБАВЛЕН ПРОСТОЙ)"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicles (number, fuel_rate, idle_rate) VALUES (?, ?, ?)",
                (number.upper(), fuel_rate, idle_rate)
            )
            conn.commit()
            vehicle_id = cursor.lastrowid
            conn.close()
            logger.info(f"✅ Добавлен автомобиль {number}, простой: {idle_rate} л/ч")
            return vehicle_id
        except sqlite3.IntegrityError:
            logger.warning(f"⚠️ Автомобиль {number} уже существует")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка добавления автомобиля: {e}")
            return None
    
    @staticmethod
    def get_vehicles() -> list:
        """Получение списка автомобилей"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate, idle_rate FROM vehicles ORDER BY number")
            vehicles = cursor.fetchall()
            conn.close()
            return vehicles
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка автомобилей: {e}")
            return []
    
    @staticmethod
    def get_vehicle(vehicle_id: int):
        """Получение информации об автомобиле"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate, idle_rate FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            conn.close()
            return vehicle
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля: {e}")
            return None
    
    @staticmethod
    def get_last_waybill(vehicle_id: int, user_id: int):
        """Получение последнего путевого листа"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT odo_end, fuel_end, date 
                FROM waybills 
                WHERE vehicle_id = ? AND user_id = ?
                ORDER BY date DESC, id DESC 
                LIMIT 1
            ''', (vehicle_id, user_id))
            waybill = cursor.fetchone()
            conn.close()
            return waybill
        except Exception as e:
            logger.error(f"❌ Ошибка получения последнего путевого листа: {e}")
            return None
    
    @staticmethod
    def save_waybill(data: Dict[str, Any]) -> Optional[int]:
        """Сохранение путевого листа"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO waybills 
                (vehicle_id, user_id, date, start_time, end_time, total_hours, 
                 odo_start, odo_end, distance, fuel_start, fuel_end, fuel_refuel,
                 fuel_norm, fuel_actual, overuse, overuse_hours, overuse_calculated, 
                 economy, fuel_rate, fuel_end_manual)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['vehicle_id'],
                data['user_id'],
                data.get('date', datetime.now().strftime('%Y-%m-%d')),
                data.get('start_time'),
                data.get('end_time'),
                data.get('hours'),
                data.get('odo_start'),
                data.get('odo_end'),
                data.get('distance'),
                data.get('fuel_start'),
                data.get('fuel_end'),
                data.get('fuel_refuel', 0),
                data.get('fuel_norm'),
                data.get('fuel_actual'),
                data.get('overuse', 0),
                data.get('overuse_hours', 0),
                data.get('overuse_calculated', 0),
                data.get('economy', 0),
                data.get('fuel_rate'),
                data.get('fuel_end_manual', 0)
            ))
            conn.commit()
            waybill_id = cursor.lastrowid
            conn.close()
            logger.info(f"✅ Сохранен путевой лист #{waybill_id}")
            return waybill_id
        except Exception as e:
            logger.error(f"❌ Ошибка сохранения путевого листа: {e}")
            return None
    
    @staticmethod
    def get_statistics(vehicle_id: int, user_id: int, days: int = 7):
        """Получение статистики"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as trips,
                    SUM(distance) as total_distance,
                    SUM(fuel_actual) as total_fuel,
                    SUM(fuel_refuel) as total_refuel,
                    SUM(overuse_hours) as total_idle_hours,
                    AVG(fuel_actual/distance*100) as avg_consumption
                FROM waybills 
                WHERE vehicle_id = ? AND user_id = ? 
                AND date >= date('now', '-' || ? || ' days')
            ''', (vehicle_id, user_id, days))
            stats = cursor.fetchone()
            conn.close()
            return stats
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return None
    
    @staticmethod
    def get_database_info() -> Dict[str, Any]:
        """Получение информации о базе данных"""
        try:
            db_path = get_db_path()
            exists = os.path.exists(db_path)
            size = os.path.getsize(db_path) if exists else 0
            
            conn = get_db_connection()
            cursor = conn.cursor()
            
            cursor.execute("SELECT COUNT(*) FROM vehicles")
            vehicles_count = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM waybills")
            waybills_count = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'path': db_path,
                'exists': exists,
                'size': size,
                'vehicles_count': vehicles_count,
                'waybills_count': waybills_count
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о БД: {e}")
            return {}

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM
# ════════════════════════════════════════════════════════════════════════════

class AddVehicleStates(StatesGroup):
    number = State()
    fuel_rate = State()
    idle_rate = State()  # НОВОЕ: состояние для ввода простоя

class WaybillStates(StatesGroup):
    vehicle_selected = State()
    start_time = State()
    initial_data_choice = State()
    odo_start = State()
    fuel_start = State()
    end_time = State()
    odo_end = State()
    overuse_choice = State()  # НОВОЕ: выбор способа учета перерасхода
    overuse_hours = State()   # НОВОЕ: ввод часов простоя
    overuse_manual = State()  # НОВОЕ: ручной ввод перерасхода
    economy = State()
    fuel_end_choice = State()   # НОВОЕ: выбор способа ввода остатка топлива
    fuel_refuel = State()       # НОВОЕ: заправленное топливо
    fuel_end_manual = State()   # НОВОЕ: ручной ввод остатка топлива

# ════════════════════════════════════════════════════════════════════════════
# ⌨️  КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════════════════════════

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новый путевой лист")],
            [KeyboardButton(text="🚗 Добавить автомобиль")],
            [KeyboardButton(text="📊 Мои автомобили")],
            [KeyboardButton(text="📈 Статистика")],
            [KeyboardButton(text="ℹ️ Инфо о боте")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_skip_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для пропуска"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0")],
            [KeyboardButton(text="⏭ Пропустить")]
        ],
        resize_keyboard=True
    )

def get_vehicles_keyboard(vehicles: list) -> ReplyKeyboardMarkup:
    """Клавиатура выбора автомобиля"""
    buttons = []
    for vehicle in vehicles:
        buttons.append([KeyboardButton(text=f"🚙 {vehicle['number']} ({vehicle['fuel_rate']} л/км, {vehicle['idle_rate']} л/ч)")])
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_initial_data_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для выбора начальных данных"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Использовать данные предыдущего дня")],
            [KeyboardButton(text="✏️ Ввести вручную")]
        ],
        resize_keyboard=True
    )

def get_overuse_choice_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для выбора способа учета перерасхода"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🕒 Рассчитать по часам")],
            [KeyboardButton(text="✏️ Ввести перерасход вручную")],
            [KeyboardButton(text="✅ Нет перерасхода")]
        ],
        resize_keyboard=True
    )

def get_fuel_end_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для выбора способа ввода остатка топлива"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Рассчитать автоматически")],
            [KeyboardButton(text="✏️ Ввести остаток вручную")],
            [KeyboardButton(text="⛽ Добавить заправку")]
        ],
        resize_keyboard=True
    )

# ════════════════════════════════════════════════════════════════════════════
# 🛠️  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════════════════

def calculate_hours(start_time: str, end_time: str) -> float:
    """Расчет количества часов между двумя временами"""
    try:
        fmt = "%H:%M"
        start = datetime.strptime(start_time, fmt)
        end = datetime.strptime(end_time, fmt)
        
        if end < start:
            end += timedelta(days=1)
        
        hours = (end - start).total_seconds() / 3600
        return round(hours, 2)
    except Exception as e:
        logger.error(f"❌ Ошибка расчета часов: {e}")
        return 0.0

def validate_time(time_str: str) -> bool:
    """Валидация формата времени"""
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

def validate_number(value: str) -> bool:
    """Валидация числового значения"""
    try:
        float(value)
        return True
    except ValueError:
        return False

# ════════════════════════════════════════════════════════════════════════════
# 🏠 ОБРАБОТЧИКИ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    logger.info(f"🚀 Пользователь {message.from_user.id} запустил бота")
    
    await message.answer(
        "<b>🚛 Система учета путевых листов v3.0</b>\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
        "<b>НОВОЕ в версии 3.0:</b>\n"
        "• Поддержка Volume для Railway\n"
        "• Сохранение данных между деплоями\n"
        "• Учет простоя автомобиля\n"
        "• Расчет перерасхода по часам простоя\n"
        "• Ручной ввод остатка топлива\n"
        "• Учет заправленного топлива\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """
<b>📋 Доступные команды:</b>

/start - Главное меню
/help - Эта справка
/cancel - Отмена текущего действия
/stats - Статистика бота
/info - Информация о боте и базе данных

<b>📝 Как работать с ботом:</b>

1. <b>Добавьте автомобиль</b> - укажите:
   • Гос. номер
   • Норму расхода (л/км)
   • Перерасход при простое (л/ч)

2. <b>Создайте путевой лист</b> - заполните данные за день

3. <b>Расчет перерасхода:</b>
   • Введите часы простоя
   • Бот рассчитает: часы × перерасход в час
   • Пример: 5 ч × 0.9 л/ч = 4.5 л перерасхода

4. <b>Новые возможности:</b>
   • Расчет перерасхода по часам простоя
   • Ввод перерасхода вручную
   • Ввод остатка топлива вручную
   • Учет заправленного топлива

5. <b>Смотрите статистику</b> за последние 7 дней

<b>⚠️ Внимание:</b>
• Время указывайте в формате ЧЧ:ММ
• Показания одометра - в километрах
• Топливо - в литрах
• Простой - в часах
"""
    await message.answer(help_text)

@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("🤷 Нет активных действий для отмены", reply_markup=get_main_keyboard())
        return
    
    await state.clear()
    logger.info(f"❌ Пользователь {message.from_user.id} отменил действие")
    await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())

@router.message(Command("stats"))
@router.message(F.text == "📈 Статистика")
async def cmd_stats(message: Message):
    """Статистика бота"""
    try:
        db_info = Database.get_database_info()
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT COUNT(*) FROM vehicles")
        vehicles_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT COUNT(*) FROM waybills")
        waybills_count = cursor.fetchone()[0]
        
        cursor.execute("SELECT SUM(distance) FROM waybills")
        total_distance = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(fuel_actual) FROM waybills")
        total_fuel = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(overuse_hours) FROM waybills")
        total_idle_hours = cursor.fetchone()[0] or 0
        
        conn.close()
        
        stats_text = f"""
<b>📊 СТАТИСТИКА БОТА</b>

🚗 Автомобилей в базе: {vehicles_count}
📝 Путевых листов: {waybills_count}
🛣️ Общий пробег: {total_distance:.0f} км
⛽ Общий расход топлива: {total_fuel:.1f} л
⏱️ Часы простоя: {total_idle_hours:.1f} ч

<b>📁 Информация о базе данных:</b>
📍 Путь: {db_info.get('path', 'неизвестно')}
📏 Размер: {db_info.get('size', 0) / 1024:.1f} КБ
✅ Volume: {"подключен" if os.path.exists('/data') else "не подключен"}

<b>ℹ️ Информация:</b>
Бот готов к работе на Railway
Данные сохраняются между деплоями
Использует переменные окружения
        """
        
        await message.answer(stats_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@router.message(Command("info"))
@router.message(F.text == "ℹ️ Инфо о боте")
async def cmd_info(message: Message):
    """Информация о боте и базе данных"""
    try:
        bot_info = await bot.get_me()
        db_info = Database.get_database_info()
        
        info_text = f"""
<b>🤖 ИНФОРМАЦИЯ О БОТЕ</b>

📛 Имя: @{bot_info.username}
🆔 ID: {bot_info.id}
📅 Версия: 3.0
🚀 Платформа: Railway

<b>📊 БАЗА ДАННЫХ:</b>
📍 Путь: {db_info.get('path', 'неизвестно')}
📏 Размер: {db_info.get('size', 0) / 1024:.1f} КБ
✅ Существует: {'да' if db_info.get('exists') else 'нет'}
🚗 Автомобилей: {db_info.get('vehicles_count', 0)}
📝 Путевых листов: {db_info.get('waybills_count', 0)}

<b>⚙️ НАСТРОЙКИ:</b>
✅ BOT_TOKEN: {"установлен" if BOT_TOKEN else "не установлен"}
✅ Volume /data: {"подключен" if os.path.exists('/data') else "не подключен"}
📁 Локальная папка: {"используется" if not os.path.exists('/data') else "не используется"}

<b>📈 ПРОИЗВОДИТЕЛЬНОСТЬ:</b>
💾 MemoryStorage: используется
🔄 Асинхронный: да
🔒 Безопасность: SQLite с проверками

<b>ℹ️ ОБНОВЛЕНИЯ:</b>
• Поддержка Volume для Railway
• Сохранение данных между деплоями
• Расчет перерасхода по простому
• Ручной ввод остатка топлива
        """
        
        await message.answer(info_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации: {e}")
        await message.answer("❌ Ошибка получения информации")

# ════════════════════════════════════════════════════════════════════════════
# 🚗 ДОБАВЛЕНИЕ АВТОМОБИЛЯ (ОБНОВЛЕНО)
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🚗 Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    """Начало добавления автомобиля"""
    await message.answer(
        "🚗 Введите государственный номер автомобиля:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AddVehicleStates.number)
    logger.info(f"🚗 Пользователь {message.from_user.id} начал добавление автомобиля")

@router.message(AddVehicleStates.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    """Обработка номера автомобиля"""
    number = message.text.strip().upper()
    if len(number) < 3:
        await message.answer("❌ Номер слишком короткий. Попробуйте еще раз:")
        return
    
    await state.update_data(number=number)
    await message.answer("⛽ Введите норму расхода топлива (л/км):\nНапример: <code>0.12</code>")
    await state.set_state(AddVehicleStates.fuel_rate)

@router.message(AddVehicleStates.fuel_rate)
async def add_vehicle_fuel_rate(message: Message, state: FSMContext):
    """Обработка нормы расхода"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число (например: <code>0.12</code>):")
        return
    
    fuel_rate = float(message.text.strip())
    if fuel_rate <= 0 or fuel_rate > 5:
        await message.answer("❌ Некорректная норма расхода. Введите значение от 0.01 до 5:")
        return
    
    await state.update_data(fuel_rate=fuel_rate)
    await message.answer("⏱️ Введите перерасход топлива в час простоя (л/ч):\nНапример: <code>0.9</code>\n(стандартное значение 2.0 л/ч)")
    await state.set_state(AddVehicleStates.idle_rate)

@router.message(AddVehicleStates.idle_rate)
async def add_vehicle_idle_rate(message: Message, state: FSMContext):
    """Обработка перерасхода при простое"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число (например: <code>0.9</code>):")
        return
    
    idle_rate = float(message.text.strip())
    if idle_rate <= 0 or idle_rate > 10:
        await message.answer("❌ Некорректное значение. Введите значение от 0.1 до 10:")
        return
    
    data = await state.get_data()
    vehicle_id = Database.add_vehicle(data['number'], data['fuel_rate'], idle_rate)
    
    if vehicle_id:
        await message.answer(
            f"✅ Автомобиль <b>{data['number']}</b> добавлен!\n"
            f"⛽ Норма расхода: {data['fuel_rate']} л/км\n"
            f"⏱️ Перерасход при простое: {idle_rate} л/ч\n\n"
            f"<b>Формула расчета перерасхода:</b>\n"
            f"Перерасход = Часы простоя × {idle_rate} л/ч\n"
            f"Пример: 5 ч × {idle_rate} л/ч = {5 * idle_rate:.1f} л",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Автомобиль {data['number']} уже существует!",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 📊 СПИСОК АВТОМОБИЛЕЙ (ОБНОВЛЕНО)
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📊 Мои автомобили")
async def list_vehicles(message: Message):
    """Вывод списка автомобилей"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ У вас нет зарегистрированных автомобилей.\n"
            "Добавьте первый автомобиль!",
            reply_markup=get_main_keyboard()
        )
        return
    
    text = "<b>🚗 СПИСОК АВТОМОБИЛЕЙ</b>\n" + "━" * 30 + "\n\n"
    for vehicle in vehicles:
        text += f"🚙 <b>{vehicle['number']}</b>\n"
        text += f"⛽ Расход: {vehicle['fuel_rate']} л/км\n"
        text += f"⏱️ Перерасход при простое: {vehicle['idle_rate']} л/ч\n"
        text += f"📊 Пример расчета: 5 ч простоя = {5 * vehicle['idle_rate']:.1f} л\n\n"
    
    text += "━" * 30 + "\n"
    text += "📝 <i>Для расчета перерасхода введите часы простоя</i>"
    
    await message.answer(text)

# ════════════════════════════════════════════════════════════════════════════
# 📝 НОВЫЙ ПУТЕВОЙ ЛИСТ (ОБНОВЛЕНО)
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📝 Новый путевой лист")
async def new_waybill(message: Message, state: FSMContext):
    """Начало создания путевого листа"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ Сначала добавьте автомобиль!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Сохраняем список автомобилей для выбора
    await state.update_data(vehicles=vehicles, action='waybill')
    
    await message.answer(
        "🚗 Выберите автомобиль для путевого листа:",
        reply_markup=get_vehicles_keyboard(vehicles)
    )
    logger.info(f"📝 Пользователь {message.from_user.id} начал новый путевой лист")

# ════════════════════════════════════════════════════════════════════════════
# 🚙 ВЫБОР АВТОМОБИЛЯ (ОБНОВЛЕНО)
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text.startswith("🚙 "))
async def vehicle_selected(message: Message, state: FSMContext):
    """Обработка выбора автомобиля"""
    data = await state.get_data()
    action = data.get('action')
    vehicles = data.get('vehicles', [])
    
    # Извлекаем номер из текста кнопки
    try:
        vehicle_text = message.text[2:]  # Убираем эмодзи
        vehicle_number = vehicle_text.split(" (")[0]
    except:
        await message.answer("❌ Ошибка выбора. Попробуйте снова.", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    # Находим автомобиль в списке
    vehicle = None
    for v in vehicles:
        if v['number'] == vehicle_number:
            vehicle = v
            break
    
    if not vehicle:
        await message.answer("❌ Автомобиль не найден", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    user_id = message.from_user.id
    
    if action == 'stats':
        # Показ статистики
        stats = Database.get_statistics(vehicle['id'], user_id, 7)
        
        if not stats or stats['trips'] == 0:
            await message.answer(
                f"<b>📊 Статистика: {vehicle['number']}</b>\n\n"
                f"Нет данных за последние 7 дней",
                reply_markup=get_main_keyboard()
            )
        else:
            avg_consumption = stats['avg_consumption'] if stats['avg_consumption'] else 0
            await message.answer(
                f"<b>📊 Статистика: {vehicle['number']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>📅 За последние 7 дней:</b>\n"
                f"🚗 Поездок: {stats['trips']}\n"
                f"📏 Пробег: {stats['total_distance']:.0f} км\n"
                f"⛽ Топливо: {stats['total_fuel']:.2f} л\n"
                f"⛽ Заправлено: {stats['total_refuel']:.2f} л\n"
                f"⏱️ Часы простоя: {stats['total_idle_hours']:.1f} ч\n"
                f"📊 Средний расход: {avg_consumption:.2f} л/100км",
                reply_markup=get_main_keyboard()
            )
        await state.clear()
    else:
        # Создание путевого листа
        await state.update_data(
            vehicle_id=vehicle['id'],
            vehicle_number=vehicle['number'],
            fuel_rate=vehicle['fuel_rate'],
            idle_rate=vehicle['idle_rate'],  # Добавляем простой
            user_id=user_id
        )
        
        # Проверяем последний путевой лист
        last_waybill = Database.get_last_waybill(vehicle['id'], user_id)
        
        if last_waybill:
            await state.update_data(
                previous_odo=last_waybill['odo_end'],
                previous_fuel=last_waybill['fuel_end'],
                previous_date=last_waybill['date']
            )
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
                f"📅 Последний путевой лист: {last_waybill['date']}\n"
                f"🛣 Показания одометра на конец дня: {last_waybill['odo_end']:.0f} км\n"
                f"⛽ Остаток топлива на конец дня: {last_waybill['fuel_end']:.2f} л\n\n"
                f"<b>Использовать эти данные как начальные для нового дня?</b>",
                reply_markup=get_initial_data_keyboard()
            )
            await state.set_state(WaybillStates.initial_data_choice)
        else:
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
                f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.set_state(WaybillStates.start_time)

# ════════════════════════════════════════════════════════════════════════════
# 🔄 ВЫБОР НАЧАЛЬНЫХ ДАННЫХ (БЕЗ ИЗМЕНЕНИЙ)
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.initial_data_choice)
async def handle_initial_data_choice(message: Message, state: FSMContext):
    """Обработка выбора начальных данных"""
    data = await state.get_data()
    
    if message.text == "✅ Использовать данные предыдущего дня":
        # Используем данные из предыдущего дня
        await state.update_data(
            odo_start=data['previous_odo'],
            fuel_start=data['previous_fuel']
        )
        
        await message.answer(
            f"✅ Использованы данные от {data['previous_date']}:\n"
            f"🛣 Показания одометра на начало дня: {data['previous_odo']:.0f} км\n"
            f"⛽ Остаток топлива при выезде: {data['previous_fuel']:.2f} л\n\n"
            f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.start_time)
    else:
        # Ввод данных вручную
        await message.answer(
            "✏️ Введите показания одометра на начало дня (км):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.odo_start)

# ════════════════════════════════════════════════════════════════════════════
# 📝 ПРОЦЕСС ЗАПОЛНЕНИЯ ПУТЕВОГО ЛИСТА (ОБНОВЛЕННЫЙ)
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.start_time)
async def start_time_input(message: Message, state: FSMContext):
    """Ввод времени начала"""
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: <code>08:30</code>)")
        return
    
    await state.update_data(start_time=message.text)
    data = await state.get_data()
    
    # Проверяем, есть ли уже начальные данные (одометр и топливо)
    if 'odo_start' in data and 'fuel_start' in data:
        # Данные уже введены (из предыдущего дня или вручную), переходим к вводу времени возвращения
        await message.answer("🕓 Введите время возвращения с линии (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)
    else:
        # Нужно ввести начальные данные
        if 'odo_start' not in data:
            await message.answer("🛣 Введите показания одометра на начало дня (км):")
            await state.set_state(WaybillStates.odo_start)
        elif 'fuel_start' not in data:
            await message.answer("⛽ Введите остаток топлива при выезде (л):")
            await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.odo_start)
async def odo_start_input(message: Message, state: FSMContext):
    """Ввод показаний одометра на начало"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    await state.update_data(odo_start=float(message.text))
    data = await state.get_data()
    
    # Проверяем, есть ли время начала
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска на линию (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        # Время уже введено, запрашиваем топливо
        await message.answer("⛽ Введите остаток топлива при выезде (л):")
        await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.fuel_start)
async def fuel_start_input(message: Message, state: FSMContext):
    """Ввод остатка топлива на начало"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    await state.update_data(fuel_start=float(message.text))
    data = await state.get_data()
    
    # Проверяем, есть ли время начала
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска на линию (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        # Все начальные данные есть, переходим к времени возвращения
        await message.answer("🕓 Введите время возвращения с линии (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)

@router.message(WaybillStates.end_time)
async def end_time_input(message: Message, state: FSMContext):
    """Ввод времени окончания"""
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: <code>17:30</code>)")
        return
    
    data = await state.get_data()
    hours = calculate_hours(data["start_time"], message.text)
    await state.update_data(end_time=message.text, hours=hours)
    
    await message.answer(
        f"⏱ Всего в наряде: <b>{hours} ч</b>\n\n"
        "🚗 Введите показания одометра на конец дня (км):"
    )
    await state.set_state(WaybillStates.odo_end)

@router.message(WaybillStates.odo_end)
async def odo_end_input(message: Message, state: FSMContext):
    """Ввод показаний одометра на конец"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    data = await state.get_data()
    odo_end = float(message.text)
    odo_start = data.get('odo_start', 0)
    distance = odo_end - odo_start
    
    if distance < 0:
        await message.answer("❌ Показания одометра не могут быть меньше начальных!")
        return
    
    await state.update_data(odo_end=odo_end, distance=distance)
    
    # Теперь предлагаем выбрать способ учета перерасхода
    await message.answer(
        f"📏 Пробег за день: <b>{distance:.0f} км</b>\n\n"
        "⚠️ <b>Как учесть перерасход топлива?</b>\n\n"
        f"<i>Автомобиль: {data.get('vehicle_number', 'неизвестно')}</i>\n"
        f"<i>Перерасход при простое: {data.get('idle_rate', 2.0)} л/ч</i>\n\n"
        f"<b>Формула расчета:</b>\n"
        f"Перерасход = Часы простоя × {data.get('idle_rate', 2.0)} л/ч",
        reply_markup=get_overuse_choice_keyboard()
    )
    await state.set_state(WaybillStates.overuse_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⏱️ НОВЫЙ ФУНКЦИОНАЛ: УЧЕТ ПРОСТОЯ И ПЕРЕРАСХОДА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.overuse_choice)
async def overuse_choice_input(message: Message, state: FSMContext):
    """Обработка выбора способа учета перерасхода"""
    data = await state.get_data()
    idle_rate = data.get('idle_rate', 2.0)
    
    if message.text == "🕒 Рассчитать по простому":
        await message.answer(
            f"⏱️ Введите количество часов простоя автомобиля:\n"
            f"(например: <code>1.5</code> для 1 часа 30 минут)\n\n"
            f"<b>Формула расчета:</b>\n"
            f"Перерасход = Часы простоя × {idle_rate} л/ч",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.overuse_hours)
        
    elif message.text == "✏️ Ввести перерасход вручную":
        await message.answer(
            "📉 Введите перерасход топлива (л):\n"
            "(например: <code>3.0</code> для 3 литров)",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.overuse_manual)
        
    elif message.text == "✅ Нет перерасхода":
        await state.update_data(overuse=0, overuse_hours=0, overuse_calculated=0)
        await message.answer(
            "💰 Введите экономию топлива (л), если есть, или 0:",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.economy)
    else:
        await message.answer("❌ Пожалуйста, выберите один из предложенных вариантов:", 
                           reply_markup=get_overuse_choice_keyboard())

@router.message(WaybillStates.overuse_hours)
async def overuse_hours_input(message: Message, state: FSMContext):
    """Ввод часов простоя для расчета перерасхода"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    idle_hours = float(message.text)
    if idle_hours < 0:
        await message.answer("❌ Часы простоя не могут быть отрицательными!")
        return
    
    data = await state.get_data()
    idle_rate = data.get('idle_rate', 2.0)  # По умолчанию 2.0 л/ч
    
    # Рассчитываем перерасход: часы простоя × перерасход в час
    overuse = idle_hours * idle_rate
    
    await state.update_data(
        overuse=overuse,
        overuse_hours=idle_hours,
        overuse_calculated=1  # Флаг расчета по простому
    )
    
    await message.answer(
        f"📊 <b>РАСЧЕТ ПЕРЕРАСХОДА ПО ПРОСТОЮ:</b>\n"
        f"⏱️ Часы простоя: {idle_hours:.1f} ч\n"
        f"⛽ Перерасход в час: {idle_rate} л/ч\n"
        f"📉 Итого перерасход: <b>{overuse:.2f} л</b>\n\n"
        f"<b>Формула:</b> {idle_hours:.1f} ч × {idle_rate} л/ч = {overuse:.2f} л\n\n"
        f"💰 Введите экономию топлива (л), если есть, или 0:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.overuse_manual)
async def overuse_manual_input(message: Message, state: FSMContext):
    """Ручной ввод перерасхода"""
    if message.text == "⏭ Пропустить":
        overuse = 0
    elif not validate_number(message.text):
        await message.answer("❌ Введите корректное число или нажмите 'Пропустить'!")
        return
    else:
        overuse = float(message.text)
    
    await state.update_data(
        overuse=overuse,
        overuse_hours=0,
        overuse_calculated=0  # Не расчет по простому
    )
    
    await message.answer(
        "💰 Введите экономию топлива (л), если есть, или 0:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def economy_input(message: Message, state: FSMContext):
    """Ввод экономии"""
    if message.text == "⏭ Пропустить":
        economy = 0
    elif not validate_number(message.text):
        await message.answer("❌ Введите корректное число или нажмите 'Пропустить'!")
        return
    else:
        economy = float(message.text)
    
    await state.update_data(economy=economy)
    
    # Теперь предлагаем выбрать способ ввода остатка топлива
    data = await state.get_data()
    fuel_start = data.get('fuel_start', 0)
    distance = data.get('distance', 0)
    fuel_rate = data.get('fuel_rate', 0)
    
    # Предварительный расчет
    fuel_norm = distance * fuel_rate
    overuse = data.get('overuse', 0)
    fuel_actual = fuel_norm - economy + overuse
    fuel_end_calculated = fuel_start - fuel_actual
    
    await state.update_data(
        fuel_norm=fuel_norm,
        fuel_actual=fuel_actual,
        fuel_end_calculated=fuel_end_calculated
    )
    
    await message.answer(
        f"📊 <b>ПРЕДВАРИТЕЛЬНЫЙ РАСЧЕТ:</b>\n"
        f"⛽ Топливо начало: {fuel_start:.2f} л\n"
        f"📏 Пробег: {distance:.0f} км\n"
        f"📊 Расход по норме: {fuel_norm:.2f} л\n"
        f"📈 Фактический расход: {fuel_actual:.2f} л\n"
        f"📉 Остаток (расчетный): {fuel_end_calculated:.2f} л\n\n"
        f"<b>Выберите способ ввода остатка топлива:</b>",
        reply_markup=get_fuel_end_keyboard()
    )
    await state.set_state(WaybillStates.fuel_end_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⛽ ФУНКЦИОНАЛ: ВВОД ОСТАТКА ТОПЛИВА И ЗАПРАВКИ
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.fuel_end_choice)
async def fuel_end_choice_input(message: Message, state: FSMContext):
    """Обработка выбора способа ввода остатка топлива"""
    data = await state.get_data()
    fuel_end_calculated = data.get('fuel_end_calculated', 0)
    
    if message.text == "📊 Рассчитать автоматически":
        # Используем расчетный остаток
        await state.update_data(
            fuel_end=fuel_end_calculated,
            fuel_refuel=0,
            fuel_end_manual=0
        )
        await calculate_and_save_waybill(message, state)
        
    elif message.text == "✏️ Ввести остаток вручную":
        # Запрашиваем ручной ввод остатка
        await message.answer(
            f"✏️ Введите остаток топлива на конец дня (л):\n"
            f"<i>Расчетный остаток: {fuel_end_calculated:.2f} л</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_end_manual)
        
    elif message.text == "⛽ Добавить заправку":
        # Запрашиваем количество заправленного топлива
        await message.answer(
            f"⛽ Введите количество заправленного топлива (л):\n"
            f"<i>После заправки расчетный остаток будет: {fuel_end_calculated:.2f} л + заправка</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_refuel)
    else:
        await message.answer("❌ Пожалуйста, выберите один из предложенных вариантов:", 
                           reply_markup=get_fuel_end_keyboard())

@router.message(WaybillStates.fuel_end_manual)
async def fuel_end_manual_input(message: Message, state: FSMContext):
    """Ручной ввод остатка топлива"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    fuel_end_manual = float(message.text)
    data = await state.get_data()
    fuel_start = data.get('fuel_start', 0)
    fuel_actual = data.get('fuel_actual', 0)
    fuel_end_calculated = data.get('fuel_end_calculated', 0)
    
    # Рассчитываем сколько было заправлено (если остаток больше расчетного)
    fuel_refuel = 0
    if fuel_end_manual > fuel_end_calculated:
        fuel_refuel = fuel_end_manual - fuel_end_calculated
    
    await state.update_data(
        fuel_end=fuel_end_manual,
        fuel_refuel=fuel_refuel,
        fuel_end_manual=1  # Флаг ручного ввода
    )
    
    await calculate_and_save_waybill(message, state)

@router.message(WaybillStates.fuel_refuel)
async def fuel_refuel_input(message: Message, state: FSMContext):
    """Ввод заправленного топлива"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    fuel_refuel = float(message.text)
    if fuel_refuel < 0:
        await message.answer("❌ Количество не может быть отрицательным!")
        return
    
    data = await state.get_data()
    fuel_end_calculated = data.get('fuel_end_calculated', 0)
    
    # Новый остаток = расчетный + заправка
    fuel_end = fuel_end_calculated + fuel_refuel
    
    await state.update_data(
        fuel_end=fuel_end,
        fuel_refuel=fuel_refuel,
        fuel_end_manual=0
    )
    
    await calculate_and_save_waybill(message, state)

# ════════════════════════════════════════════════════════════════════════════
# 💾 ФИНАЛЬНЫЙ РАСЧЕТ И СОХРАНЕНИЕ
# ════════════════════════════════════════════════════════════════════════════

async def calculate_and_save_waybill(message: Message, state: FSMContext):
    """Расчет и сохранение путевого листа"""
    data = await state.get_data()
    
    # Проверяем все необходимые данные
    required_fields = ['odo_start', 'odo_end', 'fuel_start', 'fuel_end', 
                      'start_time', 'end_time', 'fuel_rate', 'fuel_actual',
                      'vehicle_id', 'user_id', 'vehicle_number']
    for field in required_fields:
        if field not in data:
            await message.answer(f"❌ Отсутствует поле {field}. Начните заново.", reply_markup=get_main_keyboard())
            await state.clear()
            return
    
    # Расчеты (уже сделаны ранее)
    distance = data['odo_end'] - data['odo_start']
    fuel_norm = distance * data['fuel_rate']
    overuse = data.get('overuse', 0)
    overuse_hours = data.get('overuse_hours', 0)
    overuse_calculated = data.get('overuse_calculated', 0)
    economy = data.get('economy', 0)
    fuel_actual = data['fuel_actual']  # Уже рассчитано
    fuel_start = data['fuel_start']
    fuel_end = data['fuel_end']
    fuel_refuel = data.get('fuel_refuel', 0)
    fuel_end_manual = data.get('fuel_end_manual', 0)
    
    # Проверка логики
    if fuel_end_manual == 0:
        # Для автоматического расчета проверяем формулу
        expected_end = fuel_start - fuel_actual + fuel_refuel
        if abs(fuel_end - expected_end) > 0.01:  # Допустимая погрешность
            logger.warning(f"Расхождение в расчетах: fuel_end={fuel_end}, expected={expected_end}")
    
    # Сохранение в БД
    waybill_data = {
        'vehicle_id': data['vehicle_id'],
        'user_id': data['user_id'],
        'start_time': data['start_time'],
        'end_time': data['end_time'],
        'hours': data.get('hours', 0),
        'odo_start': data['odo_start'],
        'odo_end': data['odo_end'],
        'distance': distance,
        'fuel_start': fuel_start,
        'fuel_end': fuel_end,
        'fuel_refuel': fuel_refuel,
        'fuel_norm': fuel_norm,
        'fuel_actual': fuel_actual,
        'overuse': overuse,
        'overuse_hours': overuse_hours,
        'overuse_calculated': overuse_calculated,
        'economy': economy,
        'fuel_rate': data['fuel_rate'],
        'fuel_end_manual': fuel_end_manual
    }
    
    waybill_id = Database.save_waybill(waybill_data)
    
    if waybill_id:
        # Формирование отчета
        overuse_info = ""
        if overuse_calculated and overuse_hours > 0:
            idle_rate = data.get('idle_rate', 2.0)
            overuse_info = f"\n⏱️ Часы простоя: {overuse_hours:.1f} ч\n📊 Расчет: {overuse_hours:.1f} ч × {idle_rate} л/ч = {overuse:.2f} л"
        elif overuse > 0:
            overuse_info = f"\n📉 Введен вручную: {overuse:.2f} л"
        
        report = f"""
✅ <b>ПУТЕВОЙ ЛИСТ #{waybill_id} СОХРАНЕН</b>
━━━━━━━━━━━━━━━━━━━━━

🚗 <b>Автомобиль:</b> {data['vehicle_number']}
📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d')}

<b>📋 ВВЕДЕННЫЕ ДАННЫЕ:</b>
🕒 Время выезда: {data['start_time']}
🕓 Время возвращения: {data['end_time']}
⏱ Всего в наряде: {data.get('hours', 0):.1f} ч
🛣 Одометр начало: {data['odo_start']:.0f} км
🛣 Одометр конец: {data['odo_end']:.0f} км
⛽ Топливо начало: {fuel_start:.2f} л
📈 Перерасход: {overuse:.2f} л{overuse_info}
📉 Экономия: {economy:.2f} л
{f'⛽ Заправлено: {fuel_refuel:.2f} л' if fuel_refuel > 0 else ''}
{f'✏️ Остаток вручную: {fuel_end:.2f} л' if fuel_end_manual else ''}

<b>📊 РАСЧЕТНЫЕ ПОКАЗАТЕЛИ:</b>
📏 Пробег за день: {distance:.0f} км
📊 Расход по норме: {fuel_norm:.2f} л
📉 Фактический расход: {fuel_actual:.2f} л
⛽ Остаток топлива: <b>{fuel_end:.2f} л</b>
━━━━━━━━━━━━━━━━━━━━━

<b>📝 ФОРМУЛА РАСЧЕТА:</b>
Остаток = Начало ({fuel_start:.2f} л) - Факт.расход ({fuel_actual:.2f} л) 
{f' + Заправка ({fuel_refuel:.2f} л)' if fuel_refuel > 0 else ''} 
= <b>{fuel_end:.2f} л</b>

✅ Данные успешно сохранены!
<b>Для следующего дня будут доступны:</b>
🛣 Показания одометра: {data['odo_end']:.0f} км
⛽ Остаток топлива: {fuel_end:.2f} л
        """
        
        await message.answer(report, reply_markup=get_main_keyboard())
        logger.info(f"✅ Пользователь {data['user_id']} сохранил путевой лист #{waybill_id}")
    else:
        await message.answer(
            "❌ Ошибка сохранения данных. Попробуйте еще раз.",
            reply_markup=get_main_keyboard()
        )
        logger.error(f"❌ Ошибка сохранения путевого листа пользователем {data['user_id']}")
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК БОТА ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    """Запуск при старте бота"""
    logger.info("=" * 70)
    logger.info("🚀 Бот учета путевых листов v3.0")
    logger.info("=" * 70)
    
    # Инициализация базы данных
    init_database()
    
    # Проверка пути к базе данных
    db_path = get_db_path()
    logger.info(f"📊 Путь к базе данных: {db_path}")
    logger.info(f"📁 Volume /data: {'подключен' if os.path.exists('/data') else 'не подключен'}")
    
    # Получение информации о боте
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот: @{bot_info.username}")
    logger.info(f"✅ ID: {bot_info.id}")
    
    # Проверка переменных окружения
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN не установлен!")
    else:
        logger.info("✅ BOT_TOKEN: установлен")
    
    # Информация о базе данных
    db_info = Database.get_database_info()
    logger.info(f"📁 Размер БД: {db_info.get('size', 0) / 1024:.1f} КБ")
    logger.info(f"🚗 Автомобилей: {db_info.get('vehicles_count', 0)}")
    logger.info(f"📝 Путевых листов: {db_info.get('waybills_count', 0)}")
    
    logger.info("=" * 70)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ С VOLUME ПОДДЕРЖКОЙ")
    logger.info("=" * 70)

async def on_shutdown():
    """Очистка при завершении работы"""
    logger.info("🔄 Завершение работы бота...")
    await bot.session.close()
    logger.info("✅ Ресурсы очищены")

async def main():
    """Основная функция запуска бота"""
    try:
        # Запуск
        await on_startup()
        
        # Удаление вебхука (если есть)
        await bot.delete_webhook(drop_pending_updates=True)
        
        # Запуск поллинга
        logger.info("📡 Запуск polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
        
    except KeyboardInterrupt:
        logger.info("⚠️ Остановка по запросу пользователя...")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
    finally:
        await on_shutdown()

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ТОЧКА ВХОДА ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    # Это важно для Railway - запуск через asyncio.run
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка при запуске: {e}")
