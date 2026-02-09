import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from contextlib import contextmanager
from functools import lru_cache

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
# ⚙️ НАСТРОЙКА ЛОГИРОВАНИЯ
# ════════════════════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# 🔐 КОНФИГУРАЦИЯ
# ════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден!")
    exit(1)

# Константы
DB_DIR = '/data' if os.path.exists('/data') else '.'
DB_PATH = os.path.join(DB_DIR, 'waybills.db')

logger.info("✅ Бот инициализирован")

# ════════════════════════════════════════════════════════════════════════════
# 🤖 ИНИЦИАЛИЗАЦИЯ БОТА
# ════════════════════════════════════════════════════════════════════════════

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# ════════════════════════════════════════════════════════════════════════════
# 💾 МЕНЕДЖЕР БАЗЫ ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

class DatabaseManager:
    """Менеджер базы данных с пулом соединений"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        os.makedirs(DB_DIR, exist_ok=True)
        logger.info(f"📊 Путь к БД: {DB_PATH}")
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для безопасной работы с БД"""
        conn = sqlite3.connect(DB_PATH, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA synchronous = NORMAL")
        try:
            yield conn
        except Exception as e:
            conn.rollback()
            logger.error(f"❌ Ошибка БД: {e}")
            raise
        else:
            conn.commit()
        finally:
            conn.close()
    
    def init_schema(self):
        """Инициализация схемы базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Таблица автомобилей
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    number TEXT UNIQUE NOT NULL,
                    fuel_rate REAL NOT NULL CHECK(fuel_rate > 0 AND fuel_rate <= 5),
                    idle_rate REAL DEFAULT 2.0 CHECK(idle_rate > 0 AND idle_rate <= 10),
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
                    total_hours REAL DEFAULT 0,
                    odo_start REAL DEFAULT 0,
                    odo_end REAL DEFAULT 0,
                    distance REAL DEFAULT 0,
                    fuel_start REAL DEFAULT 0,
                    fuel_end REAL DEFAULT 0,
                    fuel_refuel REAL DEFAULT 0,
                    fuel_norm REAL DEFAULT 0,
                    fuel_actual REAL DEFAULT 0,
                    overuse REAL DEFAULT 0,
                    overuse_hours REAL DEFAULT 0,
                    overuse_calculated INTEGER DEFAULT 0,
                    economy REAL DEFAULT 0,
                    fuel_rate REAL DEFAULT 0,
                    fuel_end_manual INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (vehicle_id) REFERENCES vehicles (id) ON DELETE CASCADE
                )
            ''')
            
            # Индексы
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_vehicles_number ON vehicles(number)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_composite ON waybills(vehicle_id, user_id, date DESC)')
            
            logger.info("✅ База данных инициализирована")
    
    def migrate(self):
        """Миграция базы данных"""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Проверка и добавление недостающих столбцов
            cursor.execute("PRAGMA table_info(waybills)")
            existing_columns = {col[1] for col in cursor.fetchall()}
            
            required_columns = {
                'overuse_hours': 'REAL DEFAULT 0',
                'overuse_calculated': 'INTEGER DEFAULT 0',
                'fuel_refuel': 'REAL DEFAULT 0',
                'fuel_end_manual': 'INTEGER DEFAULT 0'
            }
            
            for column, definition in required_columns.items():
                if column not in existing_columns:
                    logger.info(f"🔄 Добавление столбца {column}")
                    cursor.execute(f"ALTER TABLE waybills ADD COLUMN {column} {definition}")
            
            logger.info("✅ Миграция завершена")

# Инициализация БД
db_manager = DatabaseManager()

# ════════════════════════════════════════════════════════════════════════════
# 📊 РЕПОЗИТОРИЙ ДЛЯ РАБОТЫ С ДАННЫМИ
# ════════════════════════════════════════════════════════════════════════════

class VehicleRepository:
    """Репозиторий для работы с автомобилями"""
    
    @staticmethod
    def add(number: str, fuel_rate: float, idle_rate: float = 2.0) -> Optional[int]:
        """Добавление автомобиля"""
        try:
            with db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "INSERT INTO vehicles (number, fuel_rate, idle_rate) VALUES (?, ?, ?)",
                    (number.upper(), fuel_rate, idle_rate)
                )
                vehicle_id = cursor.lastrowid
                logger.info(f"✅ Добавлен автомобиль {number}")
                return vehicle_id
        except sqlite3.IntegrityError:
            logger.warning(f"⚠️ Автомобиль {number} уже существует")
            return None
    
    @staticmethod
    def get_all() -> List[Dict]:
        """Получение всех автомобилей"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate, 
                       strftime('%Y-%m-%d %H:%M', created_at) as created_at
                FROM vehicles 
                ORDER BY number COLLATE NOCASE
            """)
            return [dict(row) for row in cursor.fetchall()]
    
    @staticmethod
    def get_by_id(vehicle_id: int) -> Optional[Dict]:
        """Получение автомобиля по ID"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate,
                       strftime('%Y-%m-%d %H:%M', created_at) as created_at
                FROM vehicles 
                WHERE id = ?
            """, (vehicle_id,))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def get_by_number(number: str) -> Optional[Dict]:
        """Получение автомобиля по номеру"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT id, number, fuel_rate, idle_rate FROM vehicles WHERE number = ?",
                (number.upper(),)
            )
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def search(search_term: str) -> List[Dict]:
        """Поиск автомобилей"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate
                FROM vehicles 
                WHERE number LIKE ? 
                ORDER BY number COLLATE NOCASE
            """, (f'%{search_term.upper()}%',))
            return [dict(row) for row in cursor.fetchall()]
    
    @staticmethod
    def delete(vehicle_id: int) -> bool:
        """Удаление автомобиля"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT number FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            
            if not vehicle:
                return False
            
            cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            logger.info(f"🗑️ Удален автомобиль {vehicle['number']}")
            return True


class WaybillRepository:
    """Репозиторий для работы с путевыми листами"""
    
    @staticmethod
    def get_last(vehicle_id: int, user_id: int) -> Optional[Dict]:
        """Получение последнего путевого листа"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT odo_end, fuel_end, date 
                FROM waybills 
                WHERE vehicle_id = ? AND user_id = ?
                ORDER BY date DESC, id DESC 
                LIMIT 1
            ''', (vehicle_id, user_id))
            row = cursor.fetchone()
            return dict(row) if row else None
    
    @staticmethod
    def save(data: Dict[str, Any]) -> Optional[int]:
        """Сохранение путевого листа"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO waybills 
                (vehicle_id, user_id, date, start_time, end_time, total_hours, 
                 odo_start, odo_end, distance, fuel_start, fuel_end, fuel_refuel,
                 fuel_norm, fuel_actual, overuse, overuse_hours, overuse_calculated, 
                 economy, fuel_rate, fuel_end_manual)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['vehicle_id'], data['user_id'], 
                data.get('date', datetime.now().strftime('%Y-%m-%d')),
                data.get('start_time'), data.get('end_time'), data.get('hours'),
                data.get('odo_start'), data.get('odo_end'), data.get('distance'),
                data.get('fuel_start'), data.get('fuel_end'), data.get('fuel_refuel', 0),
                data.get('fuel_norm'), data.get('fuel_actual'), data.get('overuse', 0),
                data.get('overuse_hours', 0), data.get('overuse_calculated', 0),
                data.get('economy', 0), data.get('fuel_rate'), data.get('fuel_end_manual', 0)
            ))
            waybill_id = cursor.lastrowid
            logger.info(f"✅ Сохранен путевой лист #{waybill_id}")
            return waybill_id
    
    @staticmethod
    def get_statistics(vehicle_id: int, user_id: int, days: int = 7) -> Optional[Dict]:
        """Получение статистики"""
        with db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as trips,
                    COALESCE(SUM(distance), 0) as total_distance,
                    COALESCE(SUM(fuel_actual), 0) as total_fuel,
                    COALESCE(SUM(fuel_refuel), 0) as total_refuel,
                    COALESCE(SUM(overuse_hours), 0) as total_idle_hours,
                    CASE 
                        WHEN COALESCE(SUM(distance), 0) > 0 
                        THEN COALESCE(SUM(fuel_actual) / SUM(distance) * 100, 0)
                        ELSE 0
                    END as avg_consumption
                FROM waybills 
                WHERE vehicle_id = ? AND user_id = ? 
                AND date >= date('now', '-' || ? || ' days')
            ''', (vehicle_id, user_id, days))
            row = cursor.fetchone()
            return dict(row) if row else None

# ════════════════════════════════════════════════════════════════════════════
# 🛠️ УТИЛИТЫ
# ════════════════════════════════════════════════════════════════════════════

class TimeUtils:
    """Утилиты для работы со временем"""
    
    @staticmethod
    def normalize(time_str: str) -> str:
        """Нормализация времени в формат HH:MM"""
        time_str = time_str.strip().replace('.', ':')
        parts = time_str.split(':')
        if len(parts) >= 2:
            hours, minutes = int(parts[0]), int(parts[1])
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return f"{hours:02d}:{minutes:02d}"
        return time_str
    
    @staticmethod
    def validate(time_str: str) -> bool:
        """Валидация формата времени"""
        try:
            time_str = time_str.strip().replace('.', ':')
            parts = time_str.split(':')
            if len(parts) >= 2:
                hours, minutes = int(parts[0]), int(parts[1])
                return 0 <= hours <= 23 and 0 <= minutes <= 59
            return False
        except (ValueError, IndexError):
            return False
    
    @staticmethod
    def calculate_duration(start_time: str, end_time: str) -> tuple[int, int]:
        """Расчет длительности (часы, минуты)"""
        try:
            fmt = "%H:%M"
            start = datetime.strptime(TimeUtils.normalize(start_time), fmt)
            end = datetime.strptime(TimeUtils.normalize(end_time), fmt)
            
            if end < start:
                end += timedelta(days=1)
            
            delta = end - start
            total_seconds = delta.total_seconds()
            hours = int(total_seconds // 3600)
            minutes = int((total_seconds % 3600) // 60)
            
            return hours, minutes
        except Exception as e:
            logger.error(f"❌ Ошибка расчета длительности: {e}")
            return 0, 0
    
    @staticmethod
    def to_decimal(start_time: str, end_time: str) -> float:
        """Расчет длительности в десятичном формате"""
        hours, minutes = TimeUtils.calculate_duration(start_time, end_time)
        return hours + minutes / 60.0
    
    @staticmethod
    def format_duration(hours: int, minutes: int) -> str:
        """Форматирование длительности"""
        if hours == 0 and minutes == 0:
            return "0 мин"
        elif hours == 0:
            return f"{minutes} мин"
        elif minutes == 0:
            return f"{hours} ч"
        else:
            return f"{hours} ч {minutes} мин"


class FormatUtils:
    """Утилиты форматирования"""
    
    @staticmethod
    def volume(value: float) -> str:
        """Форматирование объема топлива"""
        return f"{value:.3f}".rstrip('0').rstrip('.')
    
    @staticmethod
    def validate_number(value: str) -> bool:
        """Валидация числа"""
        try:
            float(value)
            return True
        except ValueError:
            return False


class WaybillCalculator:
    """Калькулятор для путевых листов"""
    
    @staticmethod
    def calculate_fuel_end(fuel_start: float, fuel_refuel: float, fuel_actual: float) -> float:
        """Расчет остатка топлива"""
        return fuel_start + fuel_refuel - fuel_actual
    
    @staticmethod
    def calculate_fuel_actual(fuel_norm: float, overuse: float, economy: float) -> float:
        """Расчет фактического расхода"""
        return fuel_norm + overuse - economy
    
    @staticmethod
    def calculate_overuse_by_idle(idle_hours: float, idle_rate: float) -> float:
        """Расчет перерасхода по простою"""
        return idle_hours * idle_rate

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM
# ════════════════════════════════════════════════════════════════════════════

class AddVehicleStates(StatesGroup):
    number = State()
    fuel_rate = State()
    idle_rate = State()

class SearchVehicleStates(StatesGroup):
    search_term = State()

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
    refuel_choice = State()
    fuel_refuel = State()
    fuel_end_choice = State()
    fuel_end_manual = State()

# ════════════════════════════════════════════════════════════════════════════
# ⌨️ ФАБРИКА КЛАВИАТУР
# ════════════════════════════════════════════════════════════════════════════

class KeyboardFactory:
    """Фабрика для создания клавиатур"""
    
    @staticmethod
    @lru_cache(maxsize=1)
    def main_menu() -> ReplyKeyboardMarkup:
        """Главное меню"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📝 Новый путевой лист")],
                [KeyboardButton(text="🚗 Автомобили")],
                [KeyboardButton(text="📈 Статистика")],
                [KeyboardButton(text="ℹ️ Инфо о боте")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие..."
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def vehicles_menu() -> ReplyKeyboardMarkup:
        """Меню автомобилей"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📋 Список автомобилей")],
                [KeyboardButton(text="🔍 Поиск автомобиля")],
                [KeyboardButton(text="🚗 Добавить автомобиль")],
                [KeyboardButton(text="🗑️ Удалить автомобиль")],
                [KeyboardButton(text="⬅️ Назад в меню")]
            ],
            resize_keyboard=True,
            input_field_placeholder="Выберите действие..."
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def cancel() -> ReplyKeyboardMarkup:
        """Кнопка отмены"""
        return ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="❌ Отмена")]],
            resize_keyboard=True
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def skip() -> ReplyKeyboardMarkup:
        """Кнопка пропуска"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="0")],
                [KeyboardButton(text="⏭ Пропустить")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    def vehicles_list(vehicles: List[Dict]) -> ReplyKeyboardMarkup:
        """Список автомобилей"""
        buttons = [[KeyboardButton(text=f"🚙 {v['number']}")] for v in vehicles]
        buttons.append([KeyboardButton(text="❌ Отмена")])
        return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
    
    @staticmethod
    @lru_cache(maxsize=1)
    def initial_data() -> ReplyKeyboardMarkup:
        """Выбор начальных данных"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Использовать данные предыдущего дня")],
                [KeyboardButton(text="✏️ Ввести вручную")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def overuse_choice() -> ReplyKeyboardMarkup:
        """Выбор способа учета перерасхода"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="🕒 Рассчитать по простою")],
                [KeyboardButton(text="✏️ Ввести перерасход вручную")],
                [KeyboardButton(text="✅ Нет перерасхода")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def refuel_choice() -> ReplyKeyboardMarkup:
        """Выбор наличия дозаправки"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Да, была дозаправка")],
                [KeyboardButton(text="❌ Нет дозаправки")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def fuel_end() -> ReplyKeyboardMarkup:
        """Выбор способа ввода остатка топлива"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="📊 Рассчитать автоматически")],
                [KeyboardButton(text="✏️ Ввести остаток вручную")]
            ],
            resize_keyboard=True
        )
    
    @staticmethod
    @lru_cache(maxsize=1)
    def confirm() -> ReplyKeyboardMarkup:
        """Подтверждение"""
        return ReplyKeyboardMarkup(
            keyboard=[
                [KeyboardButton(text="✅ Да, удалить")],
                [KeyboardButton(text="❌ Нет, отменить")]
            ],
            resize_keyboard=True
        )

# ════════════════════════════════════════════════════════════════════════════
# 📊 ФОРМАТИРОВАНИЕ СВОДКИ
# ════════════════════════════════════════════════════════════════════════════

async def save_and_show_waybill(message: Message, state: FSMContext):
    """Сохранение и отображение путевого листа"""
    data = await state.get_data()
    data['date'] = datetime.now().strftime('%Y-%m-%d')
    
    waybill_id = WaybillRepository.save(data)
    
    if waybill_id:
        hours_decimal = data.get('hours', 0)
        hours = int(hours_decimal)
        minutes = int(round((hours_decimal - hours) * 60))
        if minutes >= 60:
            hours += 1
            minutes -= 60
        
        distance = data.get('distance', 0)
        fuel_actual = data.get('fuel_actual', 0)
        fuel_consumption = fuel_actual / distance * 100 if distance > 0 else 0
        
        summary = f"""
<b>✅ ПУТЕВОЙ ЛИСТ СОХРАНЕН #{waybill_id}</b>

🚙 <b>Автомобиль:</b> {data.get('vehicle_number')}
📅 <b>Дата:</b> {data.get('date')}

<b>📊 РАСЧЕТЫ:</b>
🕒 <b>Время работы:</b> {data.get('start_time')} - {data.get('end_time')}
⏱ <b>Всего времени:</b> {TimeUtils.format_duration(hours, minutes)}
🛣 <b>Расстояние:</b> {distance:.0f} км
⛽ <b>Норма расхода:</b> {FormatUtils.volume(data.get('fuel_norm', 0))} л
📈 <b>Перерасход:</b> {FormatUtils.volume(data.get('overuse', 0))} л
💚 <b>Экономия:</b> {FormatUtils.volume(data.get('economy', 0))} л
⛽ <b>Фактический расход:</b> {FormatUtils.volume(fuel_actual)} л
⛽ <b>Дозаправка:</b> {FormatUtils.volume(data.get('fuel_refuel', 0))} л
⛽ <b>Остаток:</b> {FormatUtils.volume(data.get('fuel_end', 0))} л

<b>📈 ПОКАЗАТЕЛИ:</b>
🏭 <b>Удельный расход:</b> {fuel_consumption:.3f} л/100км
💰 <b>Эффективность:</b> {"Экономия ✅" if data.get('economy', 0) > data.get('overuse', 0) else "Перерасход ❌"}
"""
        
        await message.answer(summary, reply_markup=KeyboardFactory.main_menu())
    else:
        await message.answer(
            "❌ Ошибка сохранения путевого листа!\nПопробуйте снова.",
            reply_markup=KeyboardFactory.main_menu()
        )
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🏠 ОБРАБОТЧИКИ КОМАНД (сокращенная версия - остальное аналогично)
# ════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Обработчик команды /start"""
    await state.clear()
    logger.info(f"🚀 Пользователь {message.from_user.id} запустил бота")
    
    await message.answer(
        "<b>🚛 Система учета путевых листов</b>\n\n"
        "<b>📋 Основные функции:</b>\n"
        "• Учет путевых листов\n"
        "• Контроль расхода топлива\n"
        "• Учет простоя автомобилей\n"
        "• Поиск и управление автомобилями\n\n"
        "Выберите действие:",
        reply_markup=KeyboardFactory.main_menu()
    )

@router.message(Command("cancel"))
@router.message(F.text.in_(["❌ Отмена", "⬅️ Назад", "⬅️ Назад в меню"]))
async def cmd_cancel(message: Message, state: FSMContext):
    """Отмена текущего действия"""
    current_state = await state.get_state()
    if current_state:
        await state.clear()
    
    if message.text == "⬅️ Назад в меню":
        await message.answer("Главное меню:", reply_markup=KeyboardFactory.main_menu())
    elif message.text == "⬅️ Назад":
        await message.answer("Меню автомобилей:", reply_markup=KeyboardFactory.vehicles_menu())
    else:
        await message.answer("✅ Действие отменено", reply_markup=KeyboardFactory.main_menu())

@router.message(F.text == "🚗 Автомобили")
async def vehicles_menu(message: Message):
    """Меню управления автомобилями"""
    await message.answer(
        "<b>🚗 УПРАВЛЕНИЕ АВТОМОБИЛЯМИ</b>\n\nВыберите действие:",
        reply_markup=KeyboardFactory.vehicles_menu()
    )

@router.message(F.text == "📋 Список автомобилей")
async def list_vehicles(message: Message):
    """Вывод списка автомобилей"""
    vehicles = VehicleRepository.get_all()
    
    if not vehicles:
        await message.answer(
            "❌ В базе нет автомобилей.\nДобавьте первый автомобиль!",
            reply_markup=KeyboardFactory.vehicles_menu()
        )
        return
    
    text = "<b>🚗 СПИСОК АВТОМОБИЛЕЙ</b>\n" + "━" * 35 + "\n\n"
    
    for i, vehicle in enumerate(vehicles, 1):
        text += f"<b>{i}. {vehicle['number']}</b>\n"
        text += f"   ⛽ Расход: {FormatUtils.volume(vehicle['fuel_rate'])} л/км\n"
        text += f"   ⏱️ Простой: {FormatUtils.volume(vehicle['idle_rate'])} л/ч\n"
        text += f"   📅 Добавлен: {vehicle['created_at']}\n\n"
    
    text += f"📊 <b>Всего автомобилей:</b> {len(vehicles)}\n"
    
    await message.answer(text, reply_markup=KeyboardFactory.vehicles_menu())

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК БОТА
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    """Инициализация при запуске"""
    logger.info("=" * 60)
    logger.info("🚀 Бот учета путевых листов")
    logger.info("=" * 60)
    
    db_manager.init_schema()
    db_manager.migrate()
    
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот: @{bot_info.username} (ID: {bot_info.id})")
    logger.info("=" * 60)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 60)

async def main():
    """Основная функция"""
    try:
        await on_startup()
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("⚠️ Остановка бота...")
    finally:
        await bot.session.close()

if __name__ == "__main__":
    asyncio.run(main())
