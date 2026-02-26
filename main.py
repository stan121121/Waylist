import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove
)
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден!")
    exit(1)

logger.info("✅ Бот инициализирован")

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

def get_db_path() -> str:
    if os.path.exists('/data'):
        db_dir = '/data'
        logger.info("✅ Volume /data обнаружен")
    else:
        db_dir = '.'
        logger.info("📁 Используется локальная папка")
    os.makedirs(db_dir, exist_ok=True)
    db_path = os.path.join(db_dir, 'waybills.db')
    logger.info(f"📊 Путь к БД: {db_path}")
    return db_path

def get_db_connection():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def migrate_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(vehicles)")
        columns = [col[1] for col in cursor.fetchall()]
        if 'updated_at' not in columns:
            logger.info("🔄 Добавляем столбец updated_at в таблицу vehicles")
            cursor.execute("ALTER TABLE vehicles ADD COLUMN updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP")
        cursor.execute("PRAGMA table_info(waybills)")
        columns = [col[1] for col in cursor.fetchall()]
        required_columns = ['overuse_hours', 'overuse_calculated', 'fuel_refuel', 'fuel_end_manual']
        for column in required_columns:
            if column not in columns:
                logger.info(f"🔄 Добавляем столбец {column} в таблицу waybills")
                if column == 'overuse_hours':
                    cursor.execute(f"ALTER TABLE waybills ADD COLUMN {column} REAL DEFAULT 0")
                elif column == 'overuse_calculated' or column == 'fuel_end_manual':
                    cursor.execute(f"ALTER TABLE waybills ADD COLUMN {column} INTEGER DEFAULT 0")
                elif column == 'fuel_refuel':
                    cursor.execute(f"ALTER TABLE waybills ADD COLUMN {column} REAL DEFAULT 0")
        conn.commit()
        conn.close()
        logger.info("✅ Миграция базы данных выполнена")
    except Exception as e:
        logger.error(f"❌ Ошибка миграции БД: {e}")

def init_database():
    try:
        db_path = get_db_path()
        logger.info(f"🔄 Инициализация базы данных по пути: {db_path}")
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL CHECK(fuel_rate > 0 AND fuel_rate <= 5),
                idle_rate REAL DEFAULT 2.0 CHECK(idle_rate > 0 AND idle_rate <= 10),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        ''')
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
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vehicles_number 
            ON vehicles(number)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_user_date 
            ON waybills(vehicle_id, user_id, date DESC)
        ''')
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
        migrate_database()
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float, idle_rate: float = 2.0) -> Optional[int]:
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
            logger.info(f"✅ Добавлен автомобиль {number}")
            return vehicle_id
        except sqlite3.IntegrityError:
            logger.warning(f"⚠️ Автомобиль {number} уже существует")
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка добавления автомобиля: {e}")
            return None

    @staticmethod
    def get_vehicles(force_refresh: bool = False) -> List[Dict]:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate, 
                       strftime('%Y-%m-%d %H:%M', created_at) as created_at
                FROM vehicles 
                ORDER BY number COLLATE NOCASE
            """)
            vehicles = []
            for row in cursor.fetchall():
                vehicles.append({
                    'id': row['id'],
                    'number': row['number'],
                    'fuel_rate': row['fuel_rate'],
                    'idle_rate': row['idle_rate'],
                    'created_at': row['created_at']
                })
            conn.close()
            return vehicles
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка автомобилей: {e}")
            return []

    @staticmethod
    def get_vehicle(vehicle_id: int) -> Optional[Dict]:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate,
                       strftime('%Y-%m-%d %H:%M', created_at) as created_at
                FROM vehicles 
                WHERE id = ?
            """, (vehicle_id,))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    'id': row['id'],
                    'number': row['number'],
                    'fuel_rate': row['fuel_rate'],
                    'idle_rate': row['idle_rate'],
                    'created_at': row['created_at']
                }
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля: {e}")
            return None

    @staticmethod
    def get_vehicle_by_number(number: str) -> Optional[Dict]:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate
                FROM vehicles 
                WHERE number = ?
            """, (number.upper(),))
            row = cursor.fetchone()
            conn.close()
            if row:
                return {
                    'id': row['id'],
                    'number': row['number'],
                    'fuel_rate': row['fuel_rate'],
                    'idle_rate': row['idle_rate']
                }
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля по номеру: {e}")
            return None

    @staticmethod
    def search_vehicles(search_term: str) -> List[Dict]:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate
                FROM vehicles 
                WHERE number LIKE ? 
                ORDER BY number COLLATE NOCASE
            """, (f'%{search_term.upper()}%',))
            vehicles = []
            for row in cursor.fetchall():
                vehicles.append(dict(row))
            conn.close()
            return vehicles
        except Exception as e:
            logger.error(f"❌ Ошибка поиска автомобилей: {e}")
            return []

    @staticmethod
    def delete_vehicle(vehicle_id: int) -> bool:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT number FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            if not vehicle:
                conn.close()
                return False
            cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            conn.commit()
            conn.close()
            logger.info(f"🗑️ Удален автомобиль {vehicle['number']}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления автомобиля: {e}")
            return False

    @staticmethod
    def get_last_waybill(vehicle_id: int, user_id: int) -> Optional[Dict]:
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
            row = cursor.fetchone()
            conn.close()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения последнего путевого листа: {e}")
            return None

    @staticmethod
    def save_waybill(data: Dict[str, Any]) -> Optional[int]:
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
    def get_statistics(vehicle_id: int, user_id: int, days: int = 7) -> Optional[Dict]:
        try:
            conn = get_db_connection()
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
            conn.close()
            if row:
                return dict(row)
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения статистики: {e}")
            return None

    @staticmethod
    def get_database_info() -> Dict[str, Any]:
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
    fuel_end_choice = State()
    fuel_refuel = State()
    fuel_end_manual = State()


def get_main_keyboard() -> ReplyKeyboardMarkup:
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

def get_vehicles_keyboard() -> ReplyKeyboardMarkup:
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

def get_back_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True
    )

def get_cancel_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )

def get_skip_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0")],
            [KeyboardButton(text="⏭ Пропустить")]
        ],
        resize_keyboard=True
    )

def get_vehicles_list_keyboard(vehicles: List[Dict]) -> ReplyKeyboardMarkup:
    buttons = []
    for vehicle in vehicles:
        buttons.append([KeyboardButton(text=f"🚙 {vehicle['number']}")])
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_initial_data_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Использовать данные предыдущего дня")],
            [KeyboardButton(text="✏️ Ввести вручную")]
        ],
        resize_keyboard=True
    )

def get_overuse_choice_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="🕒 Рассчитать по простому")],
            [KeyboardButton(text="✏️ Ввести перерасход вручную")],
            [KeyboardButton(text="✅ Нет перерасхода")]
        ],
        resize_keyboard=True
    )

def get_fuel_end_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📊 Рассчитать автоматически")],
            [KeyboardButton(text="✏️ Ввести остаток вручную")],
            [KeyboardButton(text="⛽ Добавить заправку")]
        ],
        resize_keyboard=True
    )

def get_confirm_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="✅ Да, удалить")],
            [KeyboardButton(text="❌ Нет, отменить")]
        ],
        resize_keyboard=True
    )


def calculate_hours_minutes(start_time: str, end_time: str) -> tuple[int, int]:
    try:
        def normalize_time(time_str: str) -> str:
            parts = time_str.split(':')
            if len(parts) >= 2:
                return f"{int(parts[0]):02d}:{int(parts[1]):02d}"
            return time_str
        start_time_norm = normalize_time(start_time)
        end_time_norm = normalize_time(end_time)
        fmt = "%H:%M"
        start = datetime.strptime(start_time_norm, fmt)
        end = datetime.strptime(end_time_norm, fmt)
        if end < start:
            end += timedelta(days=1)
        delta = end - start
        total_seconds = delta.total_seconds()
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        return hours, minutes
    except Exception as e:
        logger.error(f"❌ Ошибка расчета часов и минут: {e}")
        return 0, 0

def calculate_hours_decimal(start_time: str, end_time: str) -> float:
    try:
        hours, minutes = calculate_hours_minutes(start_time, end_time)
        return hours + minutes / 60.0
    except Exception as e:
        logger.error(f"❌ Ошибка расчета часов в десятичном формате: {e}")
        return 0.0

def validate_time(time_str: str) -> bool:
    try:
        time_str = time_str.strip()
        time_formats = ["%H:%M", "%H:%M:%S", "%H.%M", "%H.%M.%S"]
        for time_format in time_formats:
            try:
                datetime.strptime(time_str, time_format)
                return True
            except ValueError:
                continue
        if ':' in time_str:
            parts = time_str.split(':')
            if len(parts) >= 2:
                try:
                    hours = int(parts[0])
                    minutes = int(parts[1])
                    if 0 <= hours <= 23 and 0 <= minutes <= 59:
                        return True
                except ValueError:
                    pass
        return False
    except Exception:
        return False

def normalize_time(time_str: str) -> str:
    try:
        time_str = time_str.strip()
        time_str = time_str.replace('.', ':')
        parts = time_str.split(':')
        if len(parts) >= 2:
            hours = int(parts[0])
            minutes = int(parts[1])
            if 0 <= hours <= 23 and 0 <= minutes <= 59:
                return f"{hours:02d}:{minutes:02d}"
        return time_str
    except Exception:
        return time_str

def format_time_duration(hours: int, minutes: int) -> str:
    if hours == 0 and minutes == 0:
        return "0 мин"
    elif hours == 0:
        return f"{minutes} мин"
    elif minutes == 0:
        return f"{hours} ч"
    else:
        return f"{hours} ч {minutes} мин"

def validate_number(value: str) -> bool:
    try:
        float(value)
        return True
    except ValueError:
        return False

# ═══════════════════════════════════════════════════════════════════
# ИСПРАВЛЕНИЕ 1: round() перед форматированием — устраняет ошибку
# плавающей точки (например, 20.942999... → 20.943)
# ═══════════════════════════════════════════════════════════════════
def format_volume(value: float) -> str:
    """Форматирование объема топлива с 3 знаками после запятой"""
    return f"{round(value, 3):.3f}".rstrip('0').rstrip('.')


async def save_and_show_waybill(message: Message, state: FSMContext):
    """Сохранение и отображение путевого листа"""
    data = await state.get_data()
    data['date'] = datetime.now().strftime('%Y-%m-%d')
    waybill_id = Database.save_waybill(data)

    if waybill_id:
        start_time = data.get('start_time', '--:--')
        end_time = data.get('end_time', '--:--')
        hours_decimal = data.get('hours', 0)
        hours = int(hours_decimal)
        minutes = int(round((hours_decimal - hours) * 60))
        if minutes >= 60:
            hours += 1
            minutes -= 60

        distance = data.get('distance', 0)
        fuel_actual = data.get('fuel_actual', 0)

        # ═══════════════════════════════════════════════════════════════════
        # ИСПРАВЛЕНИЕ 2: показываем удельный расход в двух форматах —
        # л/100км (стандарт диспетчера) и л/км (норма по путевому листу)
        # ═══════════════════════════════════════════════════════════════════
        if distance > 0:
            consumption_per_100km = round(fuel_actual / distance * 100, 3)
            consumption_per_km = round(fuel_actual / distance, 5)
            consumption_str = (
                f"{consumption_per_100km:.3f} л/100км  "
                f"({consumption_per_km:.5f} л/км)"
            )
        else:
            consumption_str = "0.000 л/100км  (0.00000 л/км)"

        summary = f"""
<b>✅ ПУТЕВОЙ ЛИСТ СОХРАНЕН #{waybill_id}</b>

🚙 <b>Автомобиль:</b> {data.get('vehicle_number')}
📅 <b>Дата:</b> {data.get('date')}

<b>📊 РАСЧЕТЫ:</b>
🕒 <b>Время работы:</b> {start_time} - {end_time}
⏱ <b>Всего времени:</b> {format_time_duration(hours, minutes)}
🛣 <b>Расстояние:</b> {distance:.0f} км
⛽ <b>Норма расхода:</b> {format_volume(data.get('fuel_norm', 0))} л
📈 <b>Перерасход:</b> {format_volume(data.get('overuse', 0))} л
💚 <b>Экономия:</b> {format_volume(data.get('economy', 0))} л
⛽ <b>Фактический расход:</b> {format_volume(fuel_actual)} л
⛽ <b>Заправка:</b> {format_volume(data.get('fuel_refuel', 0))} л
⛽ <b>Остаток:</b> {format_volume(data.get('fuel_end', 0))} л

<b>📈 ПОКАЗАТЕЛИ:</b>
🏭 <b>Удельный расход:</b> {consumption_str}
💰 <b>Эффективность:</b> {"Экономия ✅" if data.get('economy', 0) > data.get('overuse', 0) else "Перерасход ❌"}
"""
        await message.answer(summary, reply_markup=get_main_keyboard())
    else:
        await message.answer(
            "❌ Ошибка сохранения путевого листа!\nПопробуйте снова.",
            reply_markup=get_main_keyboard()
        )

    await state.clear()


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"🚀 Пользователь {message.from_user.id} запустил бота")
    await message.answer(
        "<b>🚛 Система учета путевых листов</b>\n\n"
        "<b>📋 Основные функции:</b>\n"
        "• Учет путевых листов\n"
        "• Контроль расхода топлива (формат: 25.572 л)\n"
        "• Учет простоя автомобилей\n"
        "• Поиск и управление автомобилями\n\n"
        "<b>⚡ Оптимизировано для Railway:</b>\n"
        "• Volume поддержка\n"
        "• Автоматические миграции\n"
        "• Быстрая работа\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    help_text = """
<b>📋 ДОСТУПНЫЕ КОМАНДЫ:</b>

/start - Главное меню
/help - Эта справка
/cancel - Отмена действия
/stats - Статистика бота
/info - Информация о боте

<b>🚗 УПРАВЛЕНИЕ АВТОМОБИЛЯМИ:</b>
• Добавление нового автомобиля
• Поиск по номеру
• Просмотр списка
• Удаление автомобилей

<b>📝 СОЗДАНИЕ ПУТЕВОГО ЛИСТА:</b>
1. Выберите автомобиль
2. Введите время выезда/возвращения
3. Введите показания одометра
4. Укажите перерасход (по простому или вручную)
5. Введите остаток топлива

<b>📊 ФОРМАТЫ ДАННЫХ:</b>
• Время: ЧЧ:ММ (06:30, 20:00)
• Одометр: целые числа (142434)
• Топливо: 3 знака после запятой (25.572 л)
"""
    await message.answer(help_text)

@router.message(Command("cancel"))
@router.message(F.text.in_(["❌ Отмена", "⬅️ Назад", "⬅️ Назад в меню"]))
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state:
        await state.clear()
        logger.info(f"❌ Пользователь {message.from_user.id} отменил действие")
    if message.text == "⬅️ Назад в меню":
        await message.answer("Главное меню:", reply_markup=get_main_keyboard())
    elif message.text == "⬅️ Назад":
        await message.answer("Меню автомобилей:", reply_markup=get_vehicles_keyboard())
    else:
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())

@router.message(Command("stats"))
@router.message(F.text == "📈 Статистика")
async def cmd_stats(message: Message):
    try:
        db_info = Database.get_database_info()
        stats_text = f"""
<b>📊 СТАТИСТИКА СИСТЕМЫ</b>

🚗 <b>Автомобилей в базе:</b> {db_info.get('vehicles_count', 0)}
📝 <b>Путевых листов:</b> {db_info.get('waybills_count', 0)}

<b>📁 ИНФОРМАЦИЯ О БАЗЕ ДАННЫХ:</b>
📍 <b>Путь:</b> {db_info.get('path', 'неизвестно')}
📏 <b>Размер:</b> {db_info.get('size', 0) / 1024:.1f} КБ
✅ <b>Volume /data:</b> {"подключен ✅" if os.path.exists('/data') else "не подключен ❌"}
"""
        await message.answer(stats_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

@router.message(Command("info"))
@router.message(F.text == "ℹ️ Инфо о боте")
async def cmd_info(message: Message):
    try:
        bot_info = await bot.get_me()
        info_text = f"""
<b>🤖 ИНФОРМАЦИЯ О БОТЕ</b>

📛 <b>Имя:</b> @{bot_info.username}
🆔 <b>ID:</b> {bot_info.id}
📅 <b>Версия:</b> 2.1
🚀 <b>Платформа:</b> Railway
⚡ <b>Статус:</b> Работает

<b>🔧 ТЕХНИЧЕСКИЕ ХАРАКТЕРИСТИКИ:</b>
• База данных: SQLite с Volume поддержкой
• Автоматические миграции
• Индексы: оптимизированы для скорости
• Логирование: в файл и консоль
"""
        await message.answer(info_text)
    except Exception as e:
        logger.error(f"❌ Ошибка получения информации: {e}")
        await message.answer("❌ Ошибка получения информации")


@router.message(F.text == "🚗 Автомобили")
async def vehicles_menu(message: Message):
    await message.answer(
        "<b>🚗 УПРАВЛЕНИЕ АВТОМОБИЛЯМИ</b>\n\nВыберите действие:",
        reply_markup=get_vehicles_keyboard()
    )

@router.message(F.text == "📋 Список автомобилей")
async def list_vehicles(message: Message):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer(
            "❌ В базе нет автомобилей.\nДобавьте первый автомобиль!",
            reply_markup=get_vehicles_keyboard()
        )
        return
    text = "<b>🚗 СПИСОК АВТОМОБИЛЕЙ</b>\n" + "━" * 35 + "\n\n"
    for i, vehicle in enumerate(vehicles, 1):
        text += f"<b>{i}. {vehicle['number']}</b>\n"
        text += f"   ⛽ Расход: {format_volume(vehicle['fuel_rate'])} л/км\n"
        text += f"   ⏱️ Простой: {format_volume(vehicle['idle_rate'])} л/ч\n"
        text += f"   📅 Добавлен: {vehicle['created_at']}\n\n"
    text += f"📊 <b>Всего автомобилей:</b> {len(vehicles)}\n"
    await message.answer(text, reply_markup=get_vehicles_keyboard())

@router.message(F.text == "🔍 Поиск автомобиля")
async def search_vehicle_start(message: Message, state: FSMContext):
    await message.answer(
        "🔍 Введите номер автомобиля или его часть для поиска:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(SearchVehicleStates.search_term)

@router.message(SearchVehicleStates.search_term)
async def search_vehicle_process(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Поиск отменен", reply_markup=get_vehicles_keyboard())
        return
    search_term = message.text.strip()
    if not search_term or len(search_term) < 2:
        await message.answer("❌ Введите хотя бы 2 символа для поиска")
        return
    vehicles = Database.search_vehicles(search_term)
    if not vehicles:
        await message.answer(
            f"🔍 По запросу '<b>{search_term}</b>' ничего не найдено.\n"
            "Попробуйте другой поисковый запрос.",
            reply_markup=get_vehicles_keyboard()
        )
        await state.clear()
        return
    text = f"<b>🔍 РЕЗУЛЬТАТЫ ПОИСКА:</b> '{search_term}'\n" + "━" * 35 + "\n\n"
    for i, vehicle in enumerate(vehicles, 1):
        text += f"<b>{i}. {vehicle['number']}</b>\n"
        text += f"   ⛽ Расход: {format_volume(vehicle['fuel_rate'])} л/км\n"
        text += f"   ⏱️ Простой: {format_volume(vehicle['idle_rate'])} л/ч\n\n"
    text += f"📊 <b>Найдено автомобилей:</b> {len(vehicles)}"
    await message.answer(text, reply_markup=get_vehicles_keyboard())
    await state.clear()

@router.message(F.text == "🚗 Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    await message.answer(
        "🚗 Введите государственный номер автомобиля:",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddVehicleStates.number)

@router.message(AddVehicleStates.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Добавление отменено", reply_markup=get_vehicles_keyboard())
        return
    number = message.text.strip().upper()
    if len(number) < 3:
        await message.answer("❌ Номер слишком короткий. Минимум 3 символа.")
        return
    existing = Database.get_vehicle_by_number(number)
    if existing:
        await message.answer(
            f"❌ Автомобиль <b>{number}</b> уже существует!\nВведите другой номер:"
        )
        return
    await state.update_data(number=number)
    await message.answer(
        "⛽ Введите норму расхода топлива (л/км):\n"
        "<i>Например: 0.120 (3 знака после запятой)</i>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddVehicleStates.fuel_rate)

@router.message(AddVehicleStates.fuel_rate)
async def add_vehicle_fuel_rate(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Добавление отменено", reply_markup=get_vehicles_keyboard())
        return
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число (например: 0.120):")
        return
    fuel_rate = float(message.text)
    if not (0.001 <= fuel_rate <= 5):
        await message.answer("❌ Норма расхода должна быть от 0.001 до 5 л/км:")
        return
    await state.update_data(fuel_rate=fuel_rate)
    await message.answer(
        "⏱️ Введите перерасход топлива в час простоя (л/ч):\n"
        "<i>Например: 2.000 (стандартное значение 2.000 л/ч)</i>",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(AddVehicleStates.idle_rate)

@router.message(AddVehicleStates.idle_rate)
async def add_vehicle_idle_rate(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Добавление отменено", reply_markup=get_vehicles_keyboard())
        return
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число (например: 2.000):")
        return
    idle_rate = float(message.text)
    if not (0.100 <= idle_rate <= 10):
        await message.answer("❌ Перерасход должен быть от 0.100 до 10 л/ч:")
        return
    data = await state.get_data()
    vehicle_id = Database.add_vehicle(data['number'], data['fuel_rate'], idle_rate)
    if vehicle_id:
        await message.answer(
            f"✅ <b>Автомобиль успешно добавлен!</b>\n\n"
            f"🚙 <b>Номер:</b> {data['number']}\n"
            f"⛽ <b>Расход:</b> {format_volume(data['fuel_rate'])} л/км\n"
            f"⏱️ <b>Перерасход при простое:</b> {format_volume(idle_rate)} л/ч\n\n"
            f"📊 <b>Пример расчета перерасхода:</b>\n"
            f"5 ч простоя × {format_volume(idle_rate)} л/ч = <b>{format_volume(5 * idle_rate)} л</b>\n\n"
            f"Теперь вы можете создавать путевые листы для этого автомобиля.",
            reply_markup=get_vehicles_keyboard()
        )
    else:
        await message.answer(
            f"❌ Не удалось добавить автомобиль {data['number']}",
            reply_markup=get_vehicles_keyboard()
        )
    await state.clear()

@router.message(F.text == "🗑️ Удалить автомобиль")
async def delete_vehicle_start(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer(
            "❌ В базе нет автомобилей для удаления.",
            reply_markup=get_vehicles_keyboard()
        )
        return
    await state.update_data(vehicles=vehicles)
    await message.answer(
        "🚗 Выберите автомобиль для удаления:\n"
        "<b>⚠️ Внимание:</b> Все путевые листы этого автомобиля будут также удалены!",
        reply_markup=get_vehicles_list_keyboard(vehicles)
    )
    await state.set_state(DeleteVehicleStates.select_vehicle)

@router.message(DeleteVehicleStates.select_vehicle, F.text.startswith("🚙 "))
async def delete_vehicle_select(message: Message, state: FSMContext):
    vehicle_number = message.text[2:].strip()
    data = await state.get_data()
    vehicles = data.get('vehicles', [])
    vehicle = None
    for v in vehicles:
        if v['number'] == vehicle_number:
            vehicle = v
            break
    if not vehicle:
        await message.answer("❌ Автомобиль не найден", reply_markup=get_vehicles_keyboard())
        await state.clear()
        return
    await state.update_data(vehicle_id=vehicle['id'], vehicle_number=vehicle['number'])
    await message.answer(
        f"⚠️ <b>ПОДТВЕРЖДЕНИЕ УДАЛЕНИЯ</b>\n\n"
        f"Вы действительно хотите удалить автомобиль?\n\n"
        f"🚙 <b>{vehicle['number']}</b>\n"
        f"⛽ Расход: {format_volume(vehicle['fuel_rate'])} л/км\n"
        f"⏱️ Простой: {format_volume(vehicle['idle_rate'])} л/ч\n\n"
        f"<b>❗ Вместе с автомобилем будут удалены:</b>\n"
        f"• Все путевые листы\n"
        f"• Вся статистика\n"
        f"• Данные нельзя восстановить!\n\n"
        f"<b>Подтвердите удаление:</b>",
        reply_markup=get_confirm_keyboard()
    )
    await state.set_state(DeleteVehicleStates.confirm_delete)

@router.message(DeleteVehicleStates.confirm_delete, F.text == "✅ Да, удалить")
async def delete_vehicle_confirm(message: Message, state: FSMContext):
    data = await state.get_data()
    vehicle_id = data.get('vehicle_id')
    vehicle_number = data.get('vehicle_number')
    if Database.delete_vehicle(vehicle_id):
        await message.answer(
            f"✅ Автомобиль <b>{vehicle_number}</b> успешно удален!\n"
            f"🗑️ Все связанные данные также удалены.",
            reply_markup=get_vehicles_keyboard()
        )
        logger.info(f"✅ Удален автомобиль {vehicle_number}")
    else:
        await message.answer(
            f"❌ Ошибка при удалении автомобиля {vehicle_number}",
            reply_markup=get_vehicles_keyboard()
        )
    await state.clear()

@router.message(DeleteVehicleStates.confirm_delete, F.text == "❌ Нет, отменить")
async def delete_vehicle_cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    vehicle_number = data.get('vehicle_number', 'автомобиль')
    await message.answer(
        f"✅ Удаление автомобиля <b>{vehicle_number}</b> отменено.",
        reply_markup=get_vehicles_keyboard()
    )
    await state.clear()


@router.message(F.text == "📝 Новый путевой лист")
async def new_waybill(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer(
            "❌ В базе нет автомобилей.\n"
            "Сначала добавьте автомобиль в меню 'Автомобили'!",
            reply_markup=get_main_keyboard()
        )
        return
    await state.update_data(vehicles=vehicles)
    await message.answer(
        "🚗 Выберите автомобиль для путевого листа:",
        reply_markup=get_vehicles_list_keyboard(vehicles)
    )
    await state.set_state(WaybillStates.vehicle_selected)

@router.message(WaybillStates.vehicle_selected, F.text.startswith("🚙 "))
async def waybill_vehicle_selected(message: Message, state: FSMContext):
    vehicle_number = message.text[2:].strip()
    data = await state.get_data()
    vehicles = data.get('vehicles', [])
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
    vehicle_info = Database.get_vehicle(vehicle['id'])
    if not vehicle_info:
        await message.answer("❌ Ошибка получения информации об автомобиле",
                             reply_markup=get_main_keyboard())
        await state.clear()
        return
    await state.update_data(
        vehicle_id=vehicle_info['id'],
        vehicle_number=vehicle_info['number'],
        fuel_rate=vehicle_info['fuel_rate'],
        idle_rate=vehicle_info['idle_rate'],
        user_id=user_id
    )
    last_waybill = Database.get_last_waybill(vehicle_info['id'], user_id)
    if last_waybill:
        await state.update_data(
            previous_odo=last_waybill['odo_end'],
            previous_fuel=last_waybill['fuel_end'],
            previous_date=last_waybill['date']
        )
        await message.answer(
            f"🚗 <b>Автомобиль:</b> {vehicle_info['number']}\n\n"
            f"📅 <b>Последний путевой лист:</b> {last_waybill['date']}\n"
            f"🛣 <b>Одометр на конец дня:</b> {last_waybill['odo_end']:.0f} км\n"
            f"⛽ <b>Остаток топлива:</b> {format_volume(last_waybill['fuel_end'])} л\n\n"
            f"<b>Использовать эти данные как начальные для нового дня?</b>",
            reply_markup=get_initial_data_keyboard()
        )
        await state.set_state(WaybillStates.initial_data_choice)
    else:
        await message.answer(
            f"🚗 <b>Автомобиль:</b> {vehicle_info['number']}\n\n"
            f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.start_time)

@router.message(WaybillStates.start_time)
async def waybill_start_time(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_time(message.text):
        await message.answer(
            "❌ Неверный формат времени. Введите время в формате <b>ЧЧ:ММ</b>\n"
            "<i>Примеры: 06:30, 6:30, 06.30, 06:30:00, 6.30</i>\n\nНажмите ❌ Отмена для отмены",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    start_time = normalize_time(message.text)
    await state.update_data(start_time=start_time)
    data = await state.get_data()
    if data.get('odo_start') is not None and data.get('fuel_start') is not None:
        await message.answer(
            f"🚗 <b>Автомобиль:</b> {data.get('vehicle_number', 'неизвестно')}\n"
            f"🕒 <b>Время выпуска:</b> {start_time}\n"
            f"🛣 <b>Одометр на начало:</b> {data.get('odo_start', 0):.0f} км\n"
            f"⛽ <b>Топливо на начало:</b> {format_volume(data.get('fuel_start', 0))} л\n\n"
            f"🕒 Введите время возвращения на базу (ЧЧ:ММ):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.end_time)
    else:
        await message.answer(
            f"🕒 <b>Время выпуска:</b> {start_time}\n\n"
            f"📊 Введите показания одометра на начало дня (км):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.odo_start)

@router.message(WaybillStates.odo_start)
async def waybill_odo_start(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите показания одометра (например, 123456) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    odo_start = float(message.text)
    if odo_start < 0:
        await message.answer("❌ Показания одометра не могут быть отрицательными")
        return
    await state.update_data(odo_start=odo_start)
    await message.answer(
        f"🛣 <b>Одометр на начало:</b> {odo_start:.0f} км\n\n"
        f"⛽ Введите количество топлива на начало дня (л):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.fuel_start)
async def waybill_fuel_start(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество топлива (например, 25.572) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    fuel_start = float(message.text)
    if fuel_start < 0:
        await message.answer("❌ Количество топлива не может быть отрицательным")
        return
    await state.update_data(fuel_start=fuel_start)
    data = await state.get_data()
    await message.answer(
        f"🚗 <b>Автомобиль:</b> {data.get('vehicle_number', 'неизвестно')}\n"
        f"🕒 <b>Время выпуска:</b> {data.get('start_time', 'не указано')}\n"
        f"🛣 <b>Одометр на начало:</b> {data.get('odo_start', 0):.0f} км\n"
        f"⛽ <b>Топливо на начало:</b> {format_volume(fuel_start)} л\n\n"
        f"🕒 Введите время возвращения на базу (ЧЧ:ММ):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(WaybillStates.end_time)

@router.message(WaybillStates.end_time)
async def waybill_end_time(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_time(message.text):
        await message.answer(
            "❌ Неверный формат времени. Введите время в формате <b>ЧЧ:ММ</b>\n"
            "<i>Примеры: 20:00, 8:00, 20.00, 20:00:00, 8.00</i>\n\nНажмите ❌ Отмена для отмены",
            reply_markup=get_cancel_keyboard(),
            parse_mode="HTML"
        )
        return
    end_time = normalize_time(message.text)
    data = await state.get_data()
    start_time = data.get('start_time')
    if not start_time:
        await message.answer("❌ Ошибка: не найдено время начала")
        await state.clear()
        return
    hours, minutes = calculate_hours_minutes(start_time, end_time)
    hours_decimal = calculate_hours_decimal(start_time, end_time)
    await state.update_data(end_time=end_time, hours=hours_decimal)
    await message.answer(
        f"🕒 <b>Время возвращения:</b> {end_time}\n"
        f"⏱ <b>Всего времени:</b> {format_time_duration(hours, minutes)}\n\n"
        f"📊 Введите показания одометра на конец дня (км):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(WaybillStates.odo_end)

@router.message(WaybillStates.odo_end)
async def waybill_odo_end(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите показания одометра (например, 123500) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    odo_end = float(message.text)
    data = await state.get_data()
    odo_start = data.get('odo_start', 0)
    if odo_end < odo_start:
        await message.answer(
            f"❌ Показания одометра на конец ({odo_end:.0f} км) "
            f"меньше, чем на начало ({odo_start:.0f} км).\n"
            f"Введите корректные данные:"
        )
        return
    distance = odo_end - odo_start
    fuel_rate = data.get('fuel_rate', 0)
    fuel_norm = distance * fuel_rate
    await state.update_data(odo_end=odo_end, distance=distance, fuel_norm=fuel_norm)
    await message.answer(
        f"🛣 <b>Одометр на конец:</b> {odo_end:.0f} км\n"
        f"📏 <b>Пройдено расстояние:</b> {distance:.0f} км\n"
        f"⛽ <b>Норма расхода:</b> {format_volume(fuel_norm)} л\n\n"
        f"📊 <b>Как учитывать перерасход топлива?</b>\n"
        f"• 🕒 Рассчитать по простому - умножение часов простоя на норму\n"
        f"• ✏️ Ввести перерасход вручную\n"
        f"• ✅ Нет перерасхода",
        reply_markup=get_overuse_choice_keyboard()
    )
    await state.set_state(WaybillStates.overuse_choice)

@router.message(WaybillStates.initial_data_choice)
async def waybill_initial_data_choice(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if message.text == "✅ Использовать данные предыдущего дня":
        data = await state.get_data()
        previous_odo = data.get('previous_odo', 0)
        previous_fuel = data.get('previous_fuel', 0)
        await state.update_data(odo_start=previous_odo, fuel_start=previous_fuel)
        await message.answer(
            f"✅ Используем данные предыдущего дня:\n"
            f"🛣 <b>Одометр:</b> {previous_odo:.0f} км\n"
            f"⛽ <b>Топливо:</b> {format_volume(previous_fuel)} л\n\n"
            f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.start_time)
    elif message.text == "✏️ Ввести вручную":
        await message.answer(
            "📊 Введите показания одометра на начало дня (км):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.odo_start)
    else:
        await message.answer(
            "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
            reply_markup=get_initial_data_keyboard()
        )

@router.message(WaybillStates.overuse_choice)
async def waybill_overuse_choice(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if message.text == "🕒 Рассчитать по простому":
        data = await state.get_data()
        idle_rate = data.get('idle_rate', 2.0)
        await message.answer(
            f"⏱️ Введите количество часов простоя (например: 1.5):\n"
            f"<i>Норма расхода при простое: {format_volume(idle_rate)} л/ч</i>",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.overuse_hours)
    elif message.text == "✏️ Ввести перерасход вручную":
        await message.answer(
            "⛽ Введите количество перерасходованного топлива (л):\n"
            "<i>Например: 2.500 (3 знака после запятой)</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.overuse_manual)
    elif message.text == "✅ Нет перерасхода":
        await state.update_data(overuse=0, overuse_hours=0, overuse_calculated=0)
        data = await state.get_data()
        await message.answer(
            f"🚗 <b>Автомобиль:</b> {data.get('vehicle_number')}\n\n"
            "📊 Теперь введите экономию топлива (л):\n"
            "<i>Если экономии нет, введите 0</i>",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.economy)
    else:
        await message.answer(
            "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
            reply_markup=get_overuse_choice_keyboard()
        )

@router.message(WaybillStates.overuse_hours)
async def waybill_overuse_hours(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if message.text == "⏭ Пропустить":
        await state.update_data(overuse_hours=0, overuse_calculated=0, overuse=0)
    elif not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество часов простоя (например, 2.5) или нажмите ⏭ Пропустить",
            reply_markup=get_skip_keyboard()
        )
        return
    else:
        overuse_hours = float(message.text)
        if overuse_hours < 0:
            await message.answer(
                "❌ Часы простоя не могут быть отрицательными. Введите положительное число или 0",
                reply_markup=get_skip_keyboard()
            )
            return
        data = await state.get_data()
        idle_rate = data.get('idle_rate', 2.0)
        overuse = overuse_hours * idle_rate
        await state.update_data(overuse_hours=overuse_hours, overuse_calculated=1, overuse=overuse)
    data = await state.get_data()
    overuse = data.get('overuse', 0)
    await message.answer(
        f"✅ Перерасход по простому: {format_volume(overuse)} л\n\n"
        "📊 Теперь введите экономию топлива (л):\n"
        "<i>Если экономии нет, введите 0</i>",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.overuse_manual)
async def waybill_overuse_manual(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество перерасхода (например, 2.500) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    overuse = float(message.text)
    if overuse < 0:
        await message.answer("❌ Перерасход не может быть отрицательным")
        return
    await state.update_data(overuse=overuse, overuse_hours=0, overuse_calculated=0)
    await message.answer(
        f"✅ Перерасход учтен: {format_volume(overuse)} л\n\n"
        "📊 Теперь введите экономию топлива (л):\n"
        "<i>Если экономии нет, введите 0</i>",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def waybill_economy(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if message.text == "⏭ Пропустить":
        economy = 0
    elif not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество экономии (например, 2.500) или нажмите ⏭ Пропустить",
            reply_markup=get_skip_keyboard()
        )
        return
    else:
        economy = float(message.text)
        if economy < 0:
            await message.answer(
                "❌ Экономия не может быть отрицательной. Введите положительное число или 0",
                reply_markup=get_skip_keyboard()
            )
            return
    await state.update_data(economy=economy)
    data = await state.get_data()
    fuel_start = data.get('fuel_start', 0)
    fuel_norm = data.get('fuel_norm', 0)
    overuse = data.get('overuse', 0)
    fuel_actual = fuel_norm + overuse - economy
    fuel_end = fuel_start - fuel_actual
    if fuel_end < 0:
        await message.answer(
            f"⚠️ <b>Внимание!</b> Отрицательный остаток топлива: {format_volume(fuel_end)} л\n"
            f"Возможно, была заправка или введены неверные данные.\n\n"
            f"⛽ <b>Как ввести остаток топлива на конец дня?</b>",
            reply_markup=get_fuel_end_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_choice)
    else:
        await state.update_data(fuel_actual=fuel_actual, fuel_end=fuel_end, fuel_end_manual=0)
        await save_and_show_waybill(message, state)

@router.message(WaybillStates.fuel_end_choice)
async def waybill_fuel_end_choice(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if message.text == "📊 Рассчитать автоматически":
        data = await state.get_data()
        fuel_start = data.get('fuel_start', 0)
        fuel_norm = data.get('fuel_norm', 0)
        overuse = data.get('overuse', 0)
        economy = data.get('economy', 0)
        fuel_actual = fuel_norm + overuse - economy
        fuel_end = fuel_start - fuel_actual
        if fuel_end < 0:
            await message.answer(
                f"⚠️ <b>Внимание!</b> Отрицательный остаток топлива: {format_volume(fuel_end)} л\n"
                f"Возможно, была заправка или введены неверные данные.\n\n"
                f"⛽ <b>Как ввести остаток топлива на конец дня?</b>",
                reply_markup=get_fuel_end_keyboard()
            )
            return
        await state.update_data(fuel_actual=fuel_actual, fuel_end=fuel_end, fuel_end_manual=0)
        await save_and_show_waybill(message, state)
    elif message.text == "✏️ Ввести остаток вручную":
        await message.answer(
            "⛽ Введите остаток топлива на конец дня (л):\n"
            f"<i>Формат: 3 знака после запятой (например: 15.500)</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_manual)
    elif message.text == "⛽ Добавить заправку":
        await message.answer(
            "⛽ Введите количество заправленного топлива (л):\n"
            f"<i>Формат: 3 знака после запятой (например: 20.000)</i>",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.fuel_refuel)
    else:
        await message.answer(
            "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
            reply_markup=get_fuel_end_keyboard()
        )

@router.message(WaybillStates.fuel_refuel)
async def waybill_fuel_refuel(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество топлива (например, 20.000) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    fuel_refuel = float(message.text)
    if fuel_refuel < 0:
        await message.answer("❌ Количество топлива не может быть отрицательным")
        return
    await state.update_data(fuel_refuel=fuel_refuel)
    data = await state.get_data()
    fuel_start = data.get('fuel_start', 0)
    fuel_norm = data.get('fuel_norm', 0)
    overuse = data.get('overuse', 0)
    economy = data.get('economy', 0)
    fuel_actual = fuel_norm + overuse - economy
    fuel_end = fuel_start + fuel_refuel - fuel_actual
    if fuel_end < 0:
        await message.answer(
            f"⚠️ <b>Внимание!</b> Отрицательный остаток топлива: {format_volume(fuel_end)} л\n"
            f"Возможно, введены неверные данные.\n\n"
            f"⛽ Введите остаток топлива на конец дня (л):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_manual)
    else:
        await state.update_data(fuel_actual=fuel_actual, fuel_end=fuel_end, fuel_end_manual=0)
        await save_and_show_waybill(message, state)

@router.message(WaybillStates.fuel_end_manual)
async def waybill_fuel_end_manual(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество топлива (например, 15.500) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    fuel_end = float(message.text)
    if fuel_end < 0:
        await message.answer("❌ Остаток топлива не может быть отрицательным")
        return
    data = await state.get_data()
    fuel_start = data.get('fuel_start', 0)
    fuel_refuel = data.get('fuel_refuel', 0)
    fuel_actual = fuel_start + fuel_refuel - fuel_end
    await state.update_data(fuel_end=fuel_end, fuel_actual=fuel_actual, fuel_end_manual=1)
    await save_and_show_waybill(message, state)


@router.message()
async def unknown_command(message: Message):
    logger.info(f"❓ Неизвестная команда от {message.from_user.id}: {message.text}")
    if validate_number(message.text):
        await message.answer(
            "⚠️ Вы ввели число, но не находитесь в процессе ввода данных.\n\n"
            "Выберите действие из меню:",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            "🤔 Я не понимаю эту команду.\n\n"
            "Используйте кнопки меню или команды:\n"
            "/start - Главное меню\n"
            "/help - Справка\n"
            "/cancel - Отмена действия",
            reply_markup=get_main_keyboard()
        )


async def on_startup():
    logger.info("=" * 60)
    logger.info("🚀 Бот учета путевых листов v2.1")
    logger.info("=" * 60)
    init_database()
    db_path = get_db_path()
    logger.info(f"📊 Путь к БД: {db_path}")
    logger.info(f"📁 Volume /data: {'подключен' if os.path.exists('/data') else 'не подключен'}")
    bot_info = await bot.get_me()
    logger.info(f"🤖 Бот: @{bot_info.username}")
    logger.info(f"🆔 ID: {bot_info.id}")
    db_info = Database.get_database_info()
    logger.info(f"📁 Размер БД: {db_info.get('size', 0) / 1024:.1f} КБ")
    logger.info(f"🚗 Автомобилей: {db_info.get('vehicles_count', 0)}")
    logger.info(f"📝 Путевых листов: {db_info.get('waybills_count', 0)}")
    logger.info("=" * 60)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 60)

async def on_shutdown():
    logger.info("🔄 Завершение работы бота...")
    await bot.session.close()
    logger.info("✅ Ресурсы очищены")

async def main():
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

if __name__ == "__main__":
    asyncio.run(main())
