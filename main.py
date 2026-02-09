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
    ReplyKeyboardRemove, InlineKeyboardMarkup, InlineKeyboardButton,
    CallbackQuery
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
    """Инициализация базы данных при старте с миграцией"""
    try:
        db_path = get_db_path()
        logger.info(f"🔄 Инициализация базы данных по пути: {db_path}")
        
        conn = sqlite3.connect(db_path, check_same_thread=False)
        cursor = conn.cursor()
        
        # Проверяем существование таблицы vehicles
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='vehicles'")
        vehicles_exists = cursor.fetchone() is not None
        
        if vehicles_exists:
            # Проверяем структуру существующей таблицы
            cursor.execute("PRAGMA table_info(vehicles)")
            columns = {row[1] for row in cursor.fetchall()}
            
            # Удаляем старую таблицу если структура не совпадает
            required_columns = {'id', 'number', 'fuel_rate', 'idle_rate', 'created_at'}
            if not required_columns.issubset(columns) or 'updated_at' in columns:
                logger.info("🔄 Обнаружена старая структура БД, выполняю миграцию...")
                
                # Сохраняем данные
                cursor.execute("SELECT number, fuel_rate, idle_rate FROM vehicles")
                old_vehicles = cursor.fetchall()
                
                # Удаляем старые таблицы
                cursor.execute("DROP TABLE IF EXISTS waybills")
                cursor.execute("DROP TABLE IF EXISTS vehicles")
                
                logger.info(f"📦 Сохранено {len(old_vehicles)} автомобилей для миграции")
        
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
        
        # Восстанавливаем данные после миграции
        if vehicles_exists and 'old_vehicles' in locals():
            for vehicle in old_vehicles:
                try:
                    cursor.execute(
                        "INSERT INTO vehicles (number, fuel_rate, idle_rate) VALUES (?, ?, ?)",
                        vehicle
                    )
                except sqlite3.IntegrityError:
                    pass  # Пропускаем дубликаты
            logger.info(f"✅ Восстановлено {len(old_vehicles)} автомобилей")
        
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
/resetdb - Сброс базы данных (⚠️ удалит все данные)
"""
    await message.answer(help_text)

@router.message(Command("resetdb"))
async def cmd_reset_db(message: Message):
    """Команда для сброса базы данных"""
    try:
        db_path = get_db_path()
        
        # Получаем информацию перед удалением
        db_info = Database.get_database_info()
        
        # Закрываем все соединения
        import gc
        gc.collect()
        
        # Удаляем файл базы данных
        if os.path.exists(db_path):
            os.remove(db_path)
            logger.info(f"🗑️ База данных удалена: {db_path}")
        
        # Создаем новую базу
        init_database()
        
        await message.answer(
            f"<b>✅ БАЗА ДАННЫХ СБРОШЕНА</b>\n\n"
            f"🗑️ Удалено:\n"
            f"• Автомобилей: {db_info.get('vehicles_count', 0)}\n"
            f"• Путевых листов: {db_info.get('waybills_count', 0)}\n\n"
            f"🆕 Создана новая пустая база данных\n\n"
            f"<i>Вы можете начать добавлять автомобили заново</i>",
            reply_markup=get_main_keyboard()
        )
        logger.info(f"✅ Пользователь {message.from_user.id} сбросил базу данных")
    except Exception as e:
        logger.error(f"❌ Ошибка сброса БД: {e}")
        await message.answer(
            f"❌ Ошибка при сбросе базы данных: {e}\n\n"
            f"Попробуйте перезапустить бота на Railway",
            reply_markup=get_main_keyboard()
        )

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
        total_fuel = cursor.fetchone()[0] or 0
        
        cursor.execute("SELECT SUM(overuse_hours) FROM waybills")
        total_idle_hours = cursor.fetchone()[0] or 0
        
        conn.close()
        
        stats_text = f"""
<b>📊 ОБЩАЯ СТАТИСТИКА</b>

🚗 Автомобилей: <b>{db_info.get('vehicles_count', 0)}</b>
📝 Путевых листов: <b>{db_info.get('waybills_count', 0)}</b>
🛣️ Общий пробег: <b>{total_distance:.0f} км</b>
⛽ Расход топлива: <b>{total_fuel:.1f} л</b>
⏱️ Часов простоя: <b>{total_idle_hours:.1f} ч</b>

<b>💾 БАЗА ДАННЫХ:</b>
📁 Размер: {db_info.get('size', 0) / 1024:.1f} КБ
📍 Путь: {db_info.get('path', 'неизвестно')}
✅ Volume: {"подключен ✓" if os.path.exists('/data') else "не подключен ✗"}

<i>Версия бота: 5.0</i>
        """
        
        await message.answer(stats_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@router.message(F.text == "ℹ️ Инфо о боте")
async def cmd_info(message: Message):
    """Информация о боте"""
    try:
        bot_info = await bot.get_me()
        db_info = Database.get_database_info()
        
        info_text = f"""
<b>🤖 ИНФОРМАЦИЯ О БОТЕ</b>

📛 Бот: @{bot_info.username}
🆔 ID: {bot_info.id}
📅 Версия: <b>5.0</b>
🚀 Платформа: Railway Ready

<b>✨ ВОЗМОЖНОСТИ:</b>
✅ Учет путевых листов
✅ Поиск автомобилей
✅ Расчет перерасхода
✅ Статистика по авто
✅ Каскадное удаление
✅ Сохранение данных

<b>📊 ТЕКУЩАЯ БАЗА:</b>
🚗 Автомобилей: {db_info.get('vehicles_count', 0)}
📝 Путевых листов: {db_info.get('waybills_count', 0)}
💾 Размер БД: {db_info.get('size', 0) / 1024:.1f} КБ

<b>🔧 КОНФИГУРАЦИЯ:</b>
✅ BOT_TOKEN: установлен
{"✅" if os.path.exists('/data') else "⚠️"} Volume: {"подключен" if os.path.exists('/data') else "не подключен"}
📁 Путь: <code>{db_info.get('path', 'неизвестно')}</code>

<i>Готов к деплою на Railway 🚀</i>
        """
        
        await message.answer(info_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации: {e}")
        await message.answer("❌ Ошибка получения информации")

# ════════════════════════════════════════════════════════════════════════════
# 🚗 МЕНЮ АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🚗 Мои автомобили")
async def vehicles_menu(message: Message, state: FSMContext):
    """Главное меню автомобилей"""
    await state.clear()
    vehicles_count = len(Database.get_vehicles())
    
    await message.answer(
        f"<b>🚗 УПРАВЛЕНИЕ АВТОМОБИЛЯМИ</b>\n\n"
        f"📊 Всего автомобилей: <b>{vehicles_count}</b>\n\n"
        f"Выберите действие:",
        reply_markup=get_vehicles_menu_keyboard()
    )
    logger.info(f"🚗 Пользователь {message.from_user.id} открыл меню автомобилей")

@router.message(F.text == "◀️ Главное меню")
async def back_to_main_menu(message: Message, state: FSMContext):
    """Возврат в главное меню"""
    await state.clear()
    await message.answer("Главное меню:", reply_markup=get_main_keyboard())

# ════════════════════════════════════════════════════════════════════════════
# 📋 СПИСОК АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📋 Список автомобилей")
async def list_vehicles(message: Message):
    """Вывод списка автомобилей"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ У вас нет зарегистрированных автомобилей.\n\n"
            "➕ Добавьте первый автомобиль!",
            reply_markup=get_vehicles_menu_keyboard()
        )
        return
    
    await message.answer(
        f"<b>📋 СПИСОК АВТОМОБИЛЕЙ</b>\n\n"
        f"Всего: <b>{len(vehicles)}</b>\n"
        f"Нажмите на автомобиль для подробной информации:",
        reply_markup=get_vehicles_inline_keyboard(vehicles, "view")
    )

@router.callback_query(F.data.startswith("view_"))
async def view_vehicle_details(callback: CallbackQuery):
    """Просмотр деталей автомобиля"""
    try:
        vehicle_id = int(callback.data.split("_")[1])
        vehicle = Database.get_vehicle(vehicle_id)
        
        if not vehicle:
            await callback.answer("❌ Автомобиль не найден", show_alert=True)
            return
        
        stats = Database.get_vehicle_stats(vehicle_id)
        vehicle_info = format_vehicle_info(vehicle, stats)
        
        await callback.message.edit_text(
            vehicle_info,
            reply_markup=get_vehicle_details_keyboard(vehicle_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка просмотра деталей: {e}")
        await callback.answer("❌ Ошибка загрузки данных", show_alert=True)

@router.callback_query(F.data.startswith("stats_"))
async def show_vehicle_stats(callback: CallbackQuery):
    """Показать расширенную статистику автомобиля"""
    try:
        vehicle_id = int(callback.data.split("_")[1])
        vehicle = Database.get_vehicle(vehicle_id)
        stats = Database.get_vehicle_stats(vehicle_id)
        
        if not vehicle:
            await callback.answer("❌ Автомобиль не найден", show_alert=True)
            return
        
        stats_text = f"<b>📊 СТАТИСТИКА: {vehicle['number']}</b>\n\n"
        
        if stats.get('trips', 0) > 0:
            avg_distance = stats['total_distance'] / stats['trips']
            avg_fuel = stats['total_fuel'] / stats['trips']
            avg_consumption = (stats['total_fuel'] / stats['total_distance'] * 100) if stats['total_distance'] > 0 else 0
            
            stats_text += f"📝 Всего поездок: <b>{stats['trips']}</b>\n\n"
            stats_text += f"🛣️ Общий пробег: <b>{stats['total_distance']:.0f} км</b>\n"
            stats_text += f"📏 Средний пробег: <b>{avg_distance:.0f} км</b>\n\n"
            stats_text += f"⛽ Общий расход: <b>{stats['total_fuel']:.1f} л</b>\n"
            stats_text += f"⛽ Средний расход: <b>{avg_fuel:.1f} л</b>\n"
            stats_text += f"📊 Расход на 100км: <b>{avg_consumption:.2f} л</b>\n\n"
            stats_text += f"⏱️ Часов простоя: <b>{stats['total_idle_hours']:.1f} ч</b>\n\n"
            
            if stats.get('first_trip'):
                stats_text += f"📅 Первая поездка: {stats['first_trip']}\n"
            if stats.get('last_trip'):
                stats_text += f"📅 Последняя поездка: {stats['last_trip']}\n"
        else:
            stats_text += "📭 Нет данных о поездках"
        
        await callback.message.edit_text(
            stats_text,
            reply_markup=get_vehicle_details_keyboard(vehicle_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка показа статистики: {e}")
        await callback.answer("❌ Ошибка загрузки статистики", show_alert=True)

@router.callback_query(F.data == "back_to_vehicles")
async def back_to_vehicles_list(callback: CallbackQuery):
    """Возврат к списку автомобилей"""
    vehicles = Database.get_vehicles()
    
    await callback.message.edit_text(
        f"<b>📋 СПИСОК АВТОМОБИЛЕЙ</b>\n\n"
        f"Всего: <b>{len(vehicles)}</b>\n"
        f"Нажмите на автомобиль для подробной информации:",
        reply_markup=get_vehicles_inline_keyboard(vehicles, "view")
    )
    await callback.answer()

# ════════════════════════════════════════════════════════════════════════════
# 🔍 ПОИСК АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🔍 Поиск автомобиля")
async def search_vehicle_start(message: Message, state: FSMContext):
    """Начало поиска автомобиля"""
    await state.set_state(VehicleMenuStates.search)
    await message.answer(
        "<b>🔍 ПОИСК АВТОМОБИЛЯ</b>\n\n"
        "Введите номер или часть номера для поиска:\n\n"
        "<b>Примеры:</b>\n"
        "• <code>В123</code> - найдет В123АВ, В123СД\n"
        "• <code>777</code> - найдет все номера с 777\n"
        "• <code>А</code> - найдет все номера на букву А",
        reply_markup=get_back_keyboard()
    )
    logger.info(f"🔍 Пользователь {message.from_user.id} начал поиск автомобиля")

@router.message(VehicleMenuStates.search, F.text == "◀️ Назад")
async def cancel_search(message: Message, state: FSMContext):
    """Отмена поиска"""
    await state.clear()
    await message.answer("Поиск отменен", reply_markup=get_vehicles_menu_keyboard())

@router.message(VehicleMenuStates.search)
async def search_vehicle_query(message: Message, state: FSMContext):
    """Обработка поискового запроса"""
    query = message.text.strip()
    
    if len(query) < 1:
        await message.answer("❌ Запрос слишком короткий. Введите хотя бы 1 символ:")
        return
    
    vehicles = Database.get_vehicles(search_query=query)
    
    if not vehicles:
        await message.answer(
            f"❌ Автомобили с номером содержащим <b>'{query.upper()}'</b> не найдены.\n\n"
            f"Попробуйте другой запрос:"
        )
        return
    
    await state.clear()
    
    await message.answer(
        f"<b>🔍 РЕЗУЛЬТАТЫ ПОИСКА</b>\n\n"
        f"Запрос: <b>{query.upper()}</b>\n"
        f"Найдено: <b>{len(vehicles)}</b>\n\n"
        f"Нажмите на автомобиль для подробностей:",
        reply_markup=get_vehicles_inline_keyboard(vehicles, "view")
    )
    
    logger.info(f"🔍 Пользователь {message.from_user.id} нашел {len(vehicles)} авто по запросу '{query}'")

# ════════════════════════════════════════════════════════════════════════════
# ➕ ДОБАВЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "➕ Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    """Начало добавления автомобиля"""
    await message.answer(
        "<b>➕ ДОБАВЛЕНИЕ АВТОМОБИЛЯ</b>\n\n"
        "🚗 Введите государственный номер автомобиля:\n\n"
        "<i>Например: В123АВ77 или А777ММ199</i>",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AddVehicleStates.number)
    logger.info(f"➕ Пользователь {message.from_user.id} начал добавление автомобиля")

@router.message(AddVehicleStates.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    """Обработка номера автомобиля"""
    number = message.text.strip().upper()
    if len(number) < 3:
        await message.answer("❌ Номер слишком короткий. Попробуйте еще раз:")
        return
    
    existing = Database.get_vehicle_by_number(number)
    if existing:
        await message.answer(
            f"❌ Автомобиль <b>{number}</b> уже существует!\n\n"
            f"⛽ Расход: {existing['fuel_rate']} л/км\n"
            f"⏱️ Простой: {existing['idle_rate']} л/ч\n\n"
            "Введите другой номер:"
        )
        return
    
    await state.update_data(number=number)
    await message.answer(
        "<b>⛽ НОРМА РАСХОДА</b>\n\n"
        "Введите норму расхода топлива (л/км):\n\n"
        "<b>Примеры:</b>\n"
        "• <code>0.12</code> - для легковых\n"
        "• <code>0.25</code> - для грузовых\n"
        "• <code>0.35</code> - для крупной техники"
    )
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
    await message.answer(
        "<b>⏱️ ПЕРЕРАСХОД ПРИ ПРОСТОЕ</b>\n\n"
        "Введите перерасход топлива в час простоя (л/ч):\n\n"
        "<b>Примеры:</b>\n"
        "• <code>0.9</code> - для легковых (стандарт)\n"
        "• <code>2.0</code> - для грузовых (по умолчанию)\n"
        "• <code>3.5</code> - для крупной техники\n\n"
        "<i>Формула: Часы × Перерасход = Итого</i>"
    )
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
            f"✅ <b>АВТОМОБИЛЬ ДОБАВЛЕН!</b>\n\n"
            f"🚗 Номер: <b>{data['number']}</b>\n"
            f"⛽ Расход: {data['fuel_rate']} л/км\n"
            f"⏱️ Простой: {idle_rate} л/ч\n\n"
            f"<b>📊 Формула расчета перерасхода:</b>\n"
            f"Перерасход = Часы × {idle_rate} л/ч\n\n"
            f"<b>Примеры:</b>\n"
            f"• 5 ч × {idle_rate} = {5 * idle_rate:.1f} л\n"
            f"• 10 ч × {idle_rate} = {10 * idle_rate:.1f} л",
            reply_markup=get_vehicles_menu_keyboard()
        )
        logger.info(f"✅ Добавлен автомобиль {data['number']}")
    else:
        await message.answer(
            f"❌ Ошибка при добавлении автомобиля!",
            reply_markup=get_vehicles_menu_keyboard()
        )
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🗑️ УДАЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🗑️ Удалить автомобиль")
async def delete_vehicle_start(message: Message):
    """Начало удаления автомобиля"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ У вас нет зарегистрированных автомобилей.\n\n"
            "➕ Сначала добавьте автомобиль!",
            reply_markup=get_vehicles_menu_keyboard()
        )
        return
    
    await message.answer(
        "<b>🗑️ УДАЛЕНИЕ АВТОМОБИЛЯ</b>\n\n"
        "⚠️ <b>ВНИМАНИЕ!</b> При удалении автомобиля будут удалены:\n"
        "• Все путевые листы\n"
        "• Вся статистика\n"
        "• История поездок\n\n"
        "Нажмите на автомобиль, который хотите удалить:",
        reply_markup=get_vehicles_inline_keyboard(vehicles, "delete_confirm")
    )
    logger.info(f"🗑️ Пользователь {message.from_user.id} начал удаление автомобиля")

@router.callback_query(F.data.startswith("delete_confirm_"))
async def delete_vehicle_confirm(callback: CallbackQuery):
    """Подтверждение удаления автомобиля"""
    try:
        vehicle_id = int(callback.data.split("_")[2])
        vehicle = Database.get_vehicle(vehicle_id)
        
        if not vehicle:
            await callback.answer("❌ Автомобиль не найден", show_alert=True)
            return
        
        stats = Database.get_vehicle_stats(vehicle_id)
        
        warning_text = (
            f"⚠️ <b>ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ</b>\n\n"
            f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n"
            f"⛽ Расход: {vehicle['fuel_rate']} л/км\n"
            f"⏱️ Простой: {vehicle['idle_rate']} л/ч\n\n"
            f"<b>📊 БУДЕТ УДАЛЕНО:</b>\n"
            f"📝 Путевых листов: {stats.get('trips', 0)}\n"
            f"🛣️ Пробег: {stats.get('total_distance', 0):.0f} км\n"
            f"⛽ Расход: {stats.get('total_fuel', 0):.1f} л\n\n"
            f"<b>⚠️ ДАННЫЕ НЕЛЬЗЯ ВОССТАНОВИТЬ!</b>\n\n"
            f"Вы уверены?"
        )
        
        await callback.message.edit_text(
            warning_text,
            reply_markup=get_confirm_delete_keyboard(vehicle_id)
        )
        await callback.answer()
    except Exception as e:
        logger.error(f"❌ Ошибка подтверждения удаления: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("delete_yes_"))
async def delete_vehicle_confirmed(callback: CallbackQuery):
    """Выполнение удаления автомобиля"""
    try:
        vehicle_id = int(callback.data.split("_")[2])
        vehicle = Database.get_vehicle(vehicle_id)
        
        if not vehicle:
            await callback.answer("❌ Автомобиль не найден", show_alert=True)
            return
        
        vehicle_number = vehicle['number']
        
        if Database.delete_vehicle(vehicle_id):
            await callback.message.edit_text(
                f"✅ <b>АВТОМОБИЛЬ УДАЛЕН</b>\n\n"
                f"🗑️ Автомобиль <b>{vehicle_number}</b> успешно удален!\n"
                f"📝 Все связанные путевые листы также удалены.\n\n"
                f"<i>Данные удалены безвозвратно</i>"
            )
            await callback.answer("✅ Удалено", show_alert=False)
            logger.info(f"✅ Удален автомобиль {vehicle_number}")
        else:
            await callback.message.edit_text(f"❌ Ошибка при удалении автомобиля {vehicle_number}")
            await callback.answer("❌ Ошибка удаления", show_alert=True)
    except Exception as e:
        logger.error(f"❌ Ошибка удаления: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

@router.callback_query(F.data.startswith("delete_no_"))
async def delete_vehicle_cancelled(callback: CallbackQuery):
    """Отмена удаления автомобиля"""
    try:
        vehicle_id = int(callback.data.split("_")[2])
        vehicle = Database.get_vehicle(vehicle_id)
        
        await callback.message.edit_text(
            f"✅ Удаление автомобиля <b>{vehicle['number'] if vehicle else 'автомобиль'}</b> отменено."
        )
        await callback.answer("Удаление отменено")
        logger.info(f"❌ Пользователь отменил удаление автомобиля")
    except Exception as e:
        logger.error(f"❌ Ошибка отмены удаления: {e}")
        await callback.answer("❌ Ошибка", show_alert=True)

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК БОТА ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    """Запуск при старте бота"""
    logger.info("=" * 70)
    logger.info("🚀 Бот учета путевых листов v5.0")
    logger.info("=" * 70)
    
    init_database()
    
    db_path = get_db_path()
    logger.info(f"📊 Путь к базе данных: {db_path}")
    logger.info(f"📁 Volume /data: {'✅ подключен' if os.path.exists('/data') else '⚠️ не подключен'}")
    
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот: @{bot_info.username}")
    logger.info(f"✅ ID: {bot_info.id}")
    
    db_info = Database.get_database_info()
    logger.info(f"📁 Размер БД: {db_info.get('size', 0) / 1024:.1f} КБ")
    logger.info(f"🚗 Автомобилей: {db_info.get('vehicles_count', 0)}")
    logger.info(f"📝 Путевых листов: {db_info.get('waybills_count', 0)}")
    
    logger.info("=" * 70)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 70)

async def on_shutdown():
    """Очистка при завершении работы"""
    logger.info("🔄 Завершение работы бота...")
    await bot.session.close()
    logger.info("✅ Ресурсы очищены")

async def main():
    """Основная функция запуска бота"""
    try:
        await on_startup()
        await bot.delete_webhook(drop_pending_updates=True)
        
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
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка при запуске: {e}")
