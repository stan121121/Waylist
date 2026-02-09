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
            [KeyboardButton(text="🕒 Рассчитать по простому")],
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
        
        cursor.execute("SELECT SUM(distance) FROM waybill
