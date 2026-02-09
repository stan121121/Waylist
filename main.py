import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton
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
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# 🔐 КОНФИГУРАЦИЯ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ (ДЛЯ RAILWAY)
# ════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в переменных окружения!")
    logger.info("📝 На Railway добавьте переменную окружения BOT_TOKEN")
    exit(1)

logger.info("✅ Бот инициализирован, токен получен")

# ════════════════════════════════════════════════════════════════════════════
# 🤖 ИНИЦИАЛИЗАЦИЯ БОТА И ДИСПЕТЧЕРА
# ════════════════════════════════════════════════════════════════════════════

bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ════════════════════════════════════════════════════════════════════════════
# 💾 НАСТРОЙКА БАЗЫ ДАННЫХ С ПОДДЕРЖКОЙ VOLUME
# ════════════════════════════════════════════════════════════════════════════

def get_db_path() -> str:
    """Определяет путь к базе данных с учетом Volume в Railway"""
    if os.path.exists('/data'):
        db_dir = '/data'
        logger.info("✅ Обнаружен Volume /data для хранения базы данных")
    else:
        db_dir = '.'
        logger.info("📁 Используется локальная папка для базы данных")
    
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, 'waybills.db')
    logger.info(f"📊 Путь к базе данных: {db_path}")
    return db_path

@asynccontextmanager
async def get_db():
    """Асинхронный контекстный менеджер для БД"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    except Exception as e:
        conn.rollback()
        logger.error(f"❌ Ошибка БД: {e}")
        raise
    finally:
        conn.close()

def init_database():
    """Инициализация базы данных при старте"""
    try:
        db_path = get_db_path()
        logger.info(f"🔄 Инициализация базы данных по пути: {db_path}")
        
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        # Таблица автомобилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL,
                idle_rate REAL DEFAULT 2.0,
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
                fuel_refuel REAL DEFAULT 0,
                fuel_norm REAL,
                fuel_actual REAL,
                overuse REAL DEFAULT 0,
                overuse_hours REAL DEFAULT 0,
                overuse_calculated INTEGER DEFAULT 0,
                economy REAL DEFAULT 0,
                fuel_rate REAL,
                fuel_end_manual INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE
            )
        ''')
        
        cursor.execute("PRAGMA foreign_keys = ON")
        
        # Индексы для оптимизации
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_user_date ON waybills(user_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_date ON waybills(vehicle_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_vehicles_number ON vehicles(number)')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ════════════════════════════════════════════════════════════════════════════
# 📊 КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ (ОПТИМИЗИРОВАННЫЙ)
# ════════════════════════════════════════════════════════════════════════════

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float, idle_rate: float = 2.0) -> Optional[int]:
        """Добавление нового автомобиля"""
        try:
            conn = sqlite3.connect(get_db_path())
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
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
    def get_vehicles(search_query: Optional[str] = None) -> List[sqlite3.Row]:
        """Получение списка автомобилей с опциональным поиском"""
        try:
            conn = sqlite3.connect(get_db_path())
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            if search_query:
                # Поиск по номеру (частичное совпадение)
                cursor.execute(
                    "SELECT id, number, fuel_rate, idle_rate FROM vehicles WHERE number LIKE ? ORDER BY number",
                    (f"%{search_query.upper()}%",)
                )
            else:
                cursor.execute("SELECT id, number, fuel_rate, idle_rate FROM vehicles ORDER BY number")
            
            vehicles = cursor.fetchall()
            conn.close()
            return vehicles
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка автомобилей: {e}")
            return []
    
    @staticmethod
    def get_vehicle(vehicle_id: int) -> Optional[sqlite3.Row]:
        """Получение информации об автомобиле"""
        try:
            conn = sqlite3.connect(get_db_path())
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate, idle_rate FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            conn.close()
            return vehicle
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля: {e}")
            return None
    
    @staticmethod
    def get_vehicle_by_number(number: str) -> Optional[sqlite3.Row]:
        """Получение автомобиля по номеру"""
        try:
            conn = sqlite3.connect(get_db_path())
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate, idle_rate FROM vehicles WHERE number = ?", (number.upper(),))
            vehicle = cursor.fetchone()
            conn.close()
            return vehicle
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля по номеру: {e}")
            return None
    
    @staticmethod
    def delete_vehicle(vehicle_id: int) -> bool:
        """Удаление автомобиля и всех связанных путевых листов"""
        try:
            conn = sqlite3.connect(get_db_path())
            cursor = conn.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            
            cursor.execute("SELECT number FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            
            if not vehicle:
                conn.close()
                return False
            
            cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            conn.commit()
            conn.close()
            
            logger.info(f"🗑️ Удален автомобиль {vehicle[0]} и все связанные путевые листы")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления автомобиля: {e}")
            return False
    
    @staticmethod
    def get_vehicle_stats(vehicle_id: int) -> Dict[str, Any]:
        """Получение статистики по автомобилю"""
        try:
            conn = sqlite3.connect(get_db_path())
            cursor = conn.cursor()
            
            cursor.execute('''
                SELECT 
                    COUNT(*) as trips,
                    SUM(distance) as total_distance,
                    SUM(fuel_actual) as total_fuel,
                    SUM(overuse_hours) as total_idle_hours,
                    MIN(date) as first_trip,
                    MAX(date) as last_trip
                FROM waybills 
                WHERE vehicle_id = ?
            ''', (vehicle_id,))
            
            stats = cursor.fetchone()
            conn.close()
            
            if stats:
                return {
                    'trips': stats[0] or 0,
                    'total_distance': stats[1] or 0,
                    'total_fuel': stats[2] or 0,
                    'total_idle_hours': stats[3] or 0,
                    'first_trip': stats[4],
                    'last_trip': stats[5]
                }
            return {}
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return {}
    
    @staticmethod
    def get_database_info() -> Dict[str, Any]:
        """Получение информации о базе данных"""
        try:
            db_path = get_db_path()
            exists = os.path.exists(db_path)
            size = os.path.getsize(db_path) if exists else 0
            
            conn = sqlite3.connect(db_path)
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
    idle_rate = State()

class VehicleMenuStates(StatesGroup):
    main_menu = State()
    search = State()
    view_details = State()

class DeleteVehicleStates(StatesGroup):
    confirm_delete = State()

class WaybillStates(StatesGroup):
    vehicle_selected = State()
    start_time = State()
    initial_data_choice = State()
    odo_start = State()
    fuel_start = State()

# ════════════════════════════════════════════════════════════════════════════
# ⌨️  КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════════════════════════

def get_main_keyboard() -> ReplyKeyboardMarkup:
    """Основная клавиатура"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новый путевой лист")],
            [KeyboardButton(text="🚗 Мои автомобили")],
            [KeyboardButton(text="📈 Статистика")],
            [KeyboardButton(text="ℹ️ Инфо о боте")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_vehicles_menu_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура меню автомобилей"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список автомобилей")],
            [KeyboardButton(text="🔍 Поиск автомобиля")],
            [KeyboardButton(text="➕ Добавить автомобиль")],
            [KeyboardButton(text="🗑️ Удалить автомобиль")],
            [KeyboardButton(text="◀️ Главное меню")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Управление автомобилями..."
    )

def get_vehicles_inline_keyboard(vehicles: List[sqlite3.Row], action: str = "view") -> InlineKeyboardMarkup:
    """Inline клавиатура для списка автомобилей"""
    buttons = []
    for vehicle in vehicles[:20]:  # Ограничение на 20 для предотвращения ошибок Telegram
        button_text = f"🚙 {vehicle['number']} • {vehicle['fuel_rate']} л/км"
        callback_data = f"{action}_{vehicle['id']}"
        buttons.append([InlineKeyboardButton(text=button_text, callback_data=callback_data)])
    
    return InlineKeyboardMarkup(inline_keyboard=buttons)

def get_vehicle_details_keyboard(vehicle_id: int) -> InlineKeyboardMarkup:
    """Клавиатура для деталей автомобиля"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Статистика", callback_data=f"stats_{vehicle_id}")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data=f"delete_confirm_{vehicle_id}")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_to_vehicles")]
    ])

def get_confirm_delete_keyboard(vehicle_id: int) -> InlineKeyboardMarkup:
    """Клавиатура подтверждения удаления"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data=f"delete_yes_{vehicle_id}")],
        [InlineKeyboardButton(text="❌ Нет, отменить", callback_data=f"delete_no_{vehicle_id}")]
    ])

def get_skip_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для пропуска"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0")],
            [KeyboardButton(text="⏭ Пропустить")]
        ],
        resize_keyboard=True
    )

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой назад"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="◀️ Назад")]],
        resize_keyboard=True
    )

# ════════════════════════════════════════════════════════════════════════════
# 🛠️  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════════════════

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

def format_vehicle_info(vehicle: sqlite3.Row, stats: Optional[Dict] = None) -> str:
    """Форматирование информации об автомобиле"""
    text = f"<b>🚙 {vehicle['number']}</b>\n"
    text += f"⛽ Расход: {vehicle['fuel_rate']} л/км\n"
    text += f"⏱️ Простой: {vehicle['idle_rate']} л/ч\n"
    
    if stats:
        text += f"\n<b>📊 Статистика:</b>\n"
        text += f"📝 Путевых листов: {stats.get('trips', 0)}\n"
        text += f"🛣️ Общий пробег: {stats.get('total_distance', 0):.0f} км\n"
        text += f"⛽ Расход топлива: {stats.get('total_fuel', 0):.1f} л\n"
        text += f"⏱️ Часов простоя: {stats.get('total_idle_hours', 0):.1f} ч\n"
        
        if stats.get('first_trip'):
            text += f"📅 Первая поездка: {stats['first_trip']}\n"
        if stats.get('last_trip'):
            text += f"📅 Последняя поездка: {stats['last_trip']}\n"
    
    return text

# ════════════════════════════════════════════════════════════════════════════
# 🏠 ОБРАБОТЧИКИ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    logger.info(f"🚀 Пользователь {message.from_user.id} запустил бота")
    
    await message.answer(
        "<b>🚛 Система учета путевых листов v5.0</b>\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
        "<b>✨ НОВОЕ в версии 5.0:</b>\n"
        "• Переработано меню автомобилей\n"
        "• Добавлен поиск по номеру авто\n"
        "• Улучшенная навигация\n"
        "• Оптимизация производительности\n"
        "• Inline-кнопки для быстрого доступа\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    """Обработчик команды /help"""
    help_text = """
<b>📋 СПРАВКА ПО БОТУ</b>

<b>🚗 УПРАВЛЕНИЕ АВТОМОБИЛЯМИ:</b>
• Список автомобилей - просмотр всех авто
• Поиск - найти авто по номеру
• Добавить - зарегистрировать новый авто
• Удалить - удалить авто с историей

<b>📝 ПУТЕВЫЕ ЛИСТЫ:</b>
• Создание листа за день
• Автоматический расчет расхода
• Учет простоя и перерасхода

<b>🔍 ПОИСК АВТОМОБИЛЕЙ:</b>
Введите номер или его часть:
• "В123" - найдет В123АВ, В123СД и т.д.
• "777" - найдет все номера с 777

<b>⚠️ ВАЖНО:</b>
• При удалении авто удаляются все его путевые листы
• Данные сохраняются между деплоями
• Используйте Volume на Railway

<b>💡 КОМАНДЫ:</b>
/start - Главное меню
/help - Эта справка
/cancel - Отмена действия
/stats - Статистика бота
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
        
        conn = sqlite3.connect(get_db_path())
        cursor = conn.cursor()
        
        cursor.execute("SELECT SUM(distance) FROM waybills")
        total_distance = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(fuel_actual) FROM waybills")
        total
