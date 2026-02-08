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
        
        # Включаем поддержку каскадного удаления
        cursor.execute("PRAGMA foreign_keys = ON")
        
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
        """Добавление нового автомобиля"""
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
    def get_vehicle_by_number(number: str):
        """Получение автомобиля по номеру"""
        try:
            conn = get_db_connection()
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
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Включаем поддержку каскадного удаления
            cursor.execute("PRAGMA foreign_keys = ON")
            
            # Получаем информацию об автомобиле перед удалением
            cursor.execute("SELECT number FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            
            if not vehicle:
                conn.close()
                return False
            
            # Удаляем автомобиль (путевые листы удалятся каскадно)
            cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            conn.commit()
            conn.close()
            
            logger.info(f"🗑️ Удален автомобиль {vehicle['number']} и все связанные путевые листы")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления автомобиля: {e}")
            return False
    
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
    idle_rate = State()

class DeleteVehicleStates(StatesGroup):
    select_vehicle = State()
    confirm_delete = State()

class WaybillStates(StatesGroup):
    vehicle_selected = State()
    start_time = State()
    initial_data_choice = State()
    odo_start = State()
    fuel_start = State()
    end_time = State()
    odo_end = State()
    overuse_choice = State()
    overuse_hours = State()
    overuse_manual = State()
    economy = State()
    fuel_end_choice = State()
    fuel_refuel = State()
    fuel_end_manual = State()

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
            [KeyboardButton(text="🗑️ Удалить автомобиль")],
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

def get_vehicles_keyboard(vehicles: list, with_cancel: bool = True) -> ReplyKeyboardMarkup:
    """Клавиатура выбора автомобиля"""
    buttons = []
    for vehicle in vehicles:
        buttons.append([KeyboardButton(text=f"🚙 {vehicle['number']} ({vehicle['fuel_rate']} л/км, {vehicle['idle_rate']} л/ч)")])
    if with_cancel:
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

def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура для подтверждения удаления"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, удалить")],
            [KeyboardButton(text="❌ Нет, отменить")]
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
        "<b>🚛 Система учета путевых листов v4.0</b>\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
        "<b>НОВОЕ в версии 4.0:</b>\n"
        "• Функция удаления автомобилей\n"
        "• Поддержка Volume для Railway\n"
        "• Сохранение данных между деплоями\n"
        "• Учет простоя автомобиля\n"
        "• Расчет перерасхода по часам простоя\n\n"
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

4. <b>Удаление автомобиля:</b>
   • Все путевые листы удалятся автоматически
   • Действие нельзя отменить

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
📅 Версия: 4.0
🚀 Платформа: Railway
📊 База данных: SQLite с Volume поддержкой

<b>📁 НАСТРОЙКИ:</b>
✅ BOT_TOKEN: {"установлен" if BOT_TOKEN else "не установлен"}
✅ Volume /data: {"подключен" if os.path.exists('/data') else "не подключен"}
📁 Путь к БД: {db_info.get('path', 'неизвестно')}

<b>⚙️ ФУНКЦИОНАЛ:</b>
✅ Учет путевых листов
✅ Учет простоя автомобилей
✅ Расчет перерасхода топлива
✅ Удаление автомобилей с каскадом
✅ Сохранение данных между деплоями

<b>🔄 ПОСЛЕДНИЕ ОБНОВЛЕНИЯ:</b>
• Добавлена функция удаления автомобилей
• Поддержка Volume для Railway
• Каскадное удаление путевых листов
• Улучшенная производительность
        """
        
        await message.answer(info_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации: {e}")
        await message.answer("❌ Ошибка получения информации")

# ════════════════════════════════════════════════════════════════════════════
# 🚗 ДОБАВЛЕНИЕ АВТОМОБИЛЯ
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
    
    # Проверяем, существует ли уже автомобиль
    existing = Database.get_vehicle_by_number(number)
    if existing:
        await message.answer(
            f"❌ Автомобиль <b>{number}</b> уже существует!\n"
            f"⛽ Расход: {existing['fuel_rate']} л/км\n"
            f"⏱️ Простой: {existing['idle_rate']} л/ч\n\n"
            "Введите другой номер или нажмите /cancel:"
        )
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
            f"❌ Ошибка при добавлении автомобиля {data['number']}!",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🗑️ УДАЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🗑️ Удалить автомобиль")
async def delete_vehicle_start(message: Message, state: FSMContext):
    """Начало удаления автомобиля"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ У вас нет зарегистрированных автомобилей.\n"
            "Сначала добавьте автомобиль!",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Сохраняем список автомобилей для выбора
    await state.update_data(vehicles=vehicles)
    await state.set_state(DeleteVehicleStates.select_vehicle)
    
    await message.answer(
        "🚗 Выберите автомобиль для удаления:\n"
        "<b>⚠️ Внимание:</b> Все путевые листы этого автомобиля будут также удалены!",
        reply_markup=get_vehicles_keyboard(vehicles)
    )
    logger.info(f"🗑️ Пользователь {message.from_user.id} начал удаление автомобиля")

@router.message(DeleteVehicleStates.select_vehicle, F.text.startswith("🚙 "))
async def delete_vehicle_selected(message: Message, state: FSMContext):
    """Обработка выбора автомобиля для удаления"""
    data = await state.get_data()
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
    
    # Сохраняем выбранный автомобиль
    await state.update_data(
        vehicle_id=vehicle['id'],
        vehicle_number=vehicle['number']
    )
    
    await message.answer(
        f"⚠️ <b>ВНИМАНИЕ! ВЫ УДАЛЯЕТЕ АВТОМОБИЛЬ</b>\n\n"
        f"🚗 Номер: <b>{vehicle['number']}</b>\n"
        f"⛽ Расход: {vehicle['fuel_rate']} л/км\n"
        f"⏱️ Простой: {vehicle['idle_rate']} л/ч\n\n"
        f"<b>ВМЕСТЕ С АВТОМОБИЛЕМ БУДУТ УДАЛЕНЫ:</b>\n"
        f"• Все путевые листы этого автомобиля\n"
        f"• Вся статистика и история\n"
        f"• Данные нельзя будет восстановить!\n\n"
        f"<b>Вы уверены, что хотите удалить этот автомобиль?</b>",
        reply_markup=get_confirm_keyboard()
    )
    await state.set_state(DeleteVehicleStates.confirm_delete)

@router.message(DeleteVehicleStates.confirm_delete, F.text == "✅ Да, удалить")
async def delete_vehicle_confirm(message: Message, state: FSMContext):
    """Подтверждение удаления автомобиля"""
    data = await state.get_data()
    vehicle_id = data.get('vehicle_id')
    vehicle_number = data.get('vehicle_number')
    
    if not vehicle_id:
        await message.answer("❌ Ошибка: автомобиль не найден", reply_markup=get_main_keyboard())
        await state.clear()
        return
    
    # Удаляем автомобиль
    if Database.delete_vehicle(vehicle_id):
        await message.answer(
            f"✅ Автомобиль <b>{vehicle_number}</b> успешно удален!\n"
            f"🗑️ Все связанные путевые листы также удалены.",
            reply_markup=get_main_keyboard()
        )
        logger.info(f"✅ Пользователь {message.from_user.id} удалил автомобиль {vehicle_number}")
    else:
        await message.answer(
            f"❌ Ошибка при удалении автомобиля {vehicle_number}",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()

@router.message(DeleteVehicleStates.confirm_delete, F.text == "❌ Нет, отменить")
async def delete_vehicle_cancel(message: Message, state: FSMContext):
    """Отмена удаления автомобиля"""
    data = await state.get_data()
    vehicle_number = data.get('vehicle_number', 'автомобиль')
    
    await message.answer(
        f"✅ Удаление автомобиля <b>{vehicle_number}</b> отменено.",
        reply_markup=get_main_keyboard()
    )
    logger.info(f"❌ Пользователь {message.from_user.id} отменил удаление автомобиля")
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 📊 СПИСОК АВТОМОБИЛЕЙ
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
    text += f"📈 Всего автомобилей: <b>{len(vehicles)}</b>\n"
    text += "📝 <i>Для расчета перерасхода введите часы простоя</i>"
    
    await message.answer(text)

# ════════════════════════════════════════════════════════════════════════════
# 📝 НОВЫЙ ПУТЕВОЙ ЛИСТ (ОСТАЛЬНЫЙ КОД БЕЗ ИЗМЕНЕНИЙ)
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

@router.message(F.text.startswith("🚙 "))
async def vehicle_selected(message: Message, state: FSMContext):
    """Обработка выбора автомобиля для путевого листа"""
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
    
    # Создание путевого листа
    await state.update_data(
        vehicle_id=vehicle['id'],
        vehicle_number=vehicle['number'],
        fuel_rate=vehicle['fuel_rate'],
        idle_rate=vehicle['idle_rate'],
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
# 🚀 ЗАПУСК БОТА ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    """Запуск при старте бота"""
    logger.info("=" * 70)
    logger.info("🚀 Бот учета путевых листов v4.0")
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
