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
        logging.StreamHandler(),
        logging.FileHandler('bot.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ════════════════════════════════════════════════════════════════════════════
# 🔐 КОНФИГУРАЦИЯ ЧЕРЕЗ ПЕРЕМЕННЫЕ ОКРУЖЕНИЯ
# ════════════════════════════════════════════════════════════════════════════

BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("❌ BOT_TOKEN не найден в переменных окружения!")
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
# 💾 БАЗА ДАННЫХ С УЧЁТОМ ПРОСТОЯ
# ════════════════════════════════════════════════════════════════════════════

def get_db_connection():
    conn = sqlite3.connect('waybills.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL,      -- л/100км
                idle_rate REAL NOT NULL,       -- л/ч
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
                total_hours REAL,
                idle_hours REAL DEFAULT 0,
                odo_start REAL,
                odo_end REAL,
                distance REAL,
                fuel_start REAL,
                fuel_end REAL,
                fuel_refuel REAL DEFAULT 0,
                fuel_norm REAL,
                fuel_actual REAL,
                overuse REAL DEFAULT 0,
                overuse_type TEXT DEFAULT '',
                economy REAL DEFAULT 0,
                fuel_rate REAL,
                idle_rate REAL,
                fuel_end_manual INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
            )
        ''')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_user_date ON waybills(user_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_date ON waybills(vehicle_id, date)')
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ════════════════════════════════════════════════════════════════════════════
# 📊 КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ
# ════════════════════════════════════════════════════════════════════════════

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float, idle_rate: float) -> Optional[int]:
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
    def update_vehicle(vehicle_id: int, fuel_rate: float, idle_rate: float) -> bool:
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE vehicles SET fuel_rate = ?, idle_rate = ? WHERE id = ?",
                (fuel_rate, idle_rate, vehicle_id)
            )
            conn.commit()
            success = cursor.rowcount > 0
            conn.close()
            return success
        except Exception as e:
            logger.error(f"❌ Ошибка обновления автомобиля: {e}")
            return False

    @staticmethod
    def get_vehicles() -> list:
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
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO waybills 
                (vehicle_id, user_id, date, start_time, end_time, total_hours, idle_hours,
                 odo_start, odo_end, distance, fuel_start, fuel_end, fuel_refuel,
                 fuel_norm, fuel_actual, overuse, overuse_type, economy, fuel_rate, idle_rate, fuel_end_manual)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                data['vehicle_id'],
                data['user_id'],
                data.get('date', datetime.now().strftime('%Y-%m-%d')),
                data.get('start_time'),
                data.get('end_time'),
                data.get('hours'),
                data.get('idle_hours', 0),
                data.get('odo_start'),
                data.get('odo_end'),
                data.get('distance'),
                data.get('fuel_start'),
                data.get('fuel_end'),
                data.get('fuel_refuel', 0),
                data.get('fuel_norm'),
                data.get('fuel_actual'),
                data.get('overuse', 0),
                data.get('overuse_type', ''),
                data.get('economy', 0),
                data.get('fuel_rate'),
                data.get('idle_rate'),
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
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
                SELECT 
                    COUNT(*) as trips,
                    SUM(distance) as total_distance,
                    SUM(fuel_actual) as total_fuel,
                    SUM(fuel_refuel) as total_refuel,
                    SUM(idle_hours) as total_idle_hours,
                    SUM(overuse) as total_overuse,
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

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM
# ════════════════════════════════════════════════════════════════════════════

class AddVehicleStates(StatesGroup):
    number = State()
    fuel_rate = State()
    idle_rate = State()

class WaybillStates(StatesGroup):
    vehicle_selected = State()
    start_time = State()
    initial_data_choice = State()
    odo_start = State()
    fuel_start = State()
    end_time = State()
    odo_end = State()
    overuse_choice = State()
    overuse_manual = State()
    idle_hours = State()
    economy = State()
    fuel_end_choice = State()
    fuel_refuel = State()
    fuel_end_manual = State()

# ════════════════════════════════════════════════════════════════════════════
# ⌨️  КЛАВИАТУРЫ
# ════════════════════════════════════════════════════════════════════════════

def get_main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новый путевой лист")],
            [KeyboardButton(text="🚗 Добавить автомобиль")],
            [KeyboardButton(text="✏️ Редактировать автомобиль")],
            [KeyboardButton(text="📊 Мои автомобили")],
            [KeyboardButton(text="📈 Статистика")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_skip_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0")],
            [KeyboardButton(text="⏭ Пропустить")]
        ],
        resize_keyboard=True
    )

def get_vehicles_keyboard(vehicles: list) -> ReplyKeyboardMarkup:
    buttons = []
    for v in vehicles:
        buttons.append([KeyboardButton(
            text=f"🚙 {v['number']} ({v['fuel_rate']} л/100км, {v['idle_rate']} л/ч)"
        )])
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

def get_overuse_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💵 Ввести перерасход в литрах")],
            [KeyboardButton(text="⏱ Рассчитать по простою")],
            [KeyboardButton(text="⏭ Нет перерасхода")]
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

# ════════════════════════════════════════════════════════════════════════════
# 🛠️  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ════════════════════════════════════════════════════════════════════════════

def calculate_hours(start_time: str, end_time: str) -> float:
    try:
        fmt = "%H:%M"
        start = datetime.strptime(start_time, fmt)
        end = datetime.strptime(end_time, fmt)
        if end < start:
            end += timedelta(days=1)
        return round((end - start).total_seconds() / 3600, 2)
    except Exception as e:
        logger.error(f"❌ Ошибка расчета часов: {e}")
        return 0.0

def validate_time(time_str: str) -> bool:
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except ValueError:
        return False

def validate_number(value: str, min_val: float = None, max_val: float = None) -> tuple[bool, float, str]:
    try:
        text = value.replace(',', '.').strip()
        num = float(text)
        if min_val is not None and num < min_val:
            return False, 0, f"Значение не может быть меньше {min_val}"
        if max_val is not None and num > max_val:
            return False, 0, f"Значение не может быть больше {max_val}"
        return True, num, ""
    except ValueError:
        return False, 0, "Введите корректное число"

# ════════════════════════════════════════════════════════════════════════════
# 🏠 ОБРАБОТЧИКИ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "<b>🚛 Система учета путевых листов v3.1</b>\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>📋 Доступные команды:</b>\n\n"
        "/start - Главное меню\n"
        "/help - Эта справка\n"
        "/cancel - Отмена текущего действия\n"
        "/stats - Статистика бота"
    )

@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("🤷 Нет активных действий", reply_markup=get_main_keyboard())
        return
    await state.clear()
    await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())

@router.message(Command("stats"))
async def cmd_stats(message: Message):
    try:
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
        cursor.execute("SELECT SUM(idle_hours) FROM waybills")
        total_idle_hours = cursor.fetchone()[0] or 0
        cursor.execute("SELECT SUM(overuse) FROM waybills")
        total_overuse = cursor.fetchone()[0] or 0
        conn.close()
        await message.answer(
            f"<b>📊 СТАТИСТИКА БОТА</b>\n\n"
            f"🚗 Автомобилей: {vehicles_count}\n"
            f"📝 Путевых листов: {waybills_count}\n"
            f"🛣️ Пробег: {total_distance:.0f} км\n"
            f"⛽ Топливо: {total_fuel:.1f} л\n"
            f"⏱️ Простой: {total_idle_hours:.1f} ч\n"
            f"📈 Перерасход: {total_overuse:.1f} л"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

# ════════════════════════════════════════════════════════════════════════════
# 🚗 ДОБАВЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🚗 Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    await message.answer("🚗 Введите гос. номер:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AddVehicleStates.number)

@router.message(AddVehicleStates.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    number = message.text.strip().upper()
    if len(number) < 3:
        await message.answer("❌ Слишком короткий номер. Повторите:")
        return
    await state.update_data(number=number)
    await message.answer("⛽ Введите расход на 100 км (л/100км):\nПример: <code>15.5</code>")
    await state.set_state(AddVehicleStates.fuel_rate)

@router.message(AddVehicleStates.fuel_rate)
async def add_vehicle_fuel_rate(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0.1, max_val=100)
    if not valid:
        await message.answer(f"❌ {err}\nВведите корректное число:")
        return
    await state.update_data(fuel_rate=value)
    await message.answer("⏱️ Введите расход при простое (л/ч):\nПример: <code>2.0</code>")
    await state.set_state(AddVehicleStates.idle_rate)

@router.message(AddVehicleStates.idle_rate)
async def add_vehicle_idle_rate(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0.1, max_val=10)
    if not valid:
        await message.answer(f"❌ {err}\nВведите корректное число:")
        return
    data = await state.get_data()
    # Проверяем, редактирование это или добавление
    if 'edit_vehicle_id' in data:
        # Редактирование
        success = Database.update_vehicle(data['edit_vehicle_id'], data['fuel_rate'], value)
        if success:
            await message.answer(
                f"✅ Автомобиль <b>{data['edit_vehicle_number']}</b> обновлён!\n"
                f"⛽ Расход: {data['fuel_rate']} л/100км\n"
                f"⏱️ Простой: {value} л/ч",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer("❌ Ошибка обновления", reply_markup=get_main_keyboard())
    else:
        # Добавление нового
        vehicle_id = Database.add_vehicle(data['number'], data['fuel_rate'], value)
        if vehicle_id:
            await message.answer(
                f"✅ Автомобиль <b>{data['number']}</b> добавлен!\n"
                f"⛽ Расход: {data['fuel_rate']} л/100км\n"
                f"⏱️ Простой: {value} л/ч",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(f"❌ Автомобиль {data['number']} уже существует!", reply_markup=get_main_keyboard())
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# ✏️ РЕДАКТИРОВАНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "✏️ Редактировать автомобиль")
async def edit_vehicle_start(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет автомобилей", reply_markup=get_main_keyboard())
        return
    await state.update_data(vehicles=vehicles, action='edit_vehicle')
    await message.answer("Выберите автомобиль:", reply_markup=get_vehicles_keyboard(vehicles))

@router.message(F.text.startswith("🚙 "))
async def vehicle_selected_for_edit(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('action') != 'edit_vehicle':
        return
    vehicles = data.get('vehicles', [])
    try:
        vehicle_text = message.text[2:]
        vehicle_number = vehicle_text.split(" (")[0]
    except:
        await message.answer("❌ Ошибка выбора", reply_markup=get_main_keyboard())
        await state.clear()
        return
    vehicle = next((v for v in vehicles if v['number'] == vehicle_number), None)
    if not vehicle:
        await message.answer("❌ Автомобиль не найден", reply_markup=get_main_keyboard())
        await state.clear()
        return
    await state.update_data(
        edit_vehicle_id=vehicle['id'],
        edit_vehicle_number=vehicle['number'],
        edit_current_fuel_rate=vehicle['fuel_rate'],
        edit_current_idle_rate=vehicle['idle_rate']
    )
    await message.answer(
        f"✏️ Редактирование <b>{vehicle['number']}</b>\n"
        f"Текущие: {vehicle['fuel_rate']} л/100км, {vehicle['idle_rate']} л/ч\n"
        f"Введите новый расход на 100 км:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AddVehicleStates.fuel_rate)

# ════════════════════════════════════════════════════════════════════════════
# 📊 СПИСОК АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📊 Мои автомобили")
async def list_vehicles(message: Message):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет автомобилей", reply_markup=get_main_keyboard())
        return
    text = "<b>🚗 СПИСОК АВТОМОБИЛЕЙ</b>\n" + "━" * 40 + "\n\n"
    for v in vehicles:
        text += f"<b>{v['number']}</b>\n⛽ {v['fuel_rate']} л/100км | ⏱️ {v['idle_rate']} л/ч\n\n"
    await message.answer(text)

# ════════════════════════════════════════════════════════════════════════════
# 📈 СТАТИСТИКА ПО АВТО
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📈 Статистика")
async def show_statistics(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет автомобилей", reply_markup=get_main_keyboard())
        return
    await state.update_data(vehicles=vehicles, action='stats')
    await message.answer("Выберите автомобиль:", reply_markup=get_vehicles_keyboard(vehicles))

# ════════════════════════════════════════════════════════════════════════════
# 📝 НОВЫЙ ПУТЕВОЙ ЛИСТ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📝 Новый путевой лист")
async def new_waybill(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Сначала добавьте автомобиль!", reply_markup=get_main_keyboard())
        return
    await state.update_data(vehicles=vehicles, action='waybill')
    await message.answer("Выберите автомобиль:", reply_markup=get_vehicles_keyboard(vehicles))

# ════════════════════════════════════════════════════════════════════════════
# 🚙 ВЫБОР АВТОМОБИЛЯ ДЛЯ ПУТЕВОГО ЛИСТА
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text.startswith("🚙 "))
async def vehicle_selected_for_waybill(message: Message, state: FSMContext):
    data = await state.get_data()
    if data.get('action') != 'waybill':
        return
    vehicles = data.get('vehicles', [])
    try:
        vehicle_text = message.text[2:]
        vehicle_number = vehicle_text.split(" (")[0]
    except:
        await message.answer("❌ Ошибка выбора", reply_markup=get_main_keyboard())
        await state.clear()
        return
    vehicle = next((v for v in vehicles if v['number'] == vehicle_number), None)
    if not vehicle:
        await message.answer("❌ Автомобиль не найден", reply_markup=get_main_keyboard())
        await state.clear()
        return

    await state.update_data(
        vehicle_id=vehicle['id'],
        vehicle_number=vehicle['number'],
        fuel_rate=vehicle['fuel_rate'],      # л/100км
        idle_rate=vehicle['idle_rate'],
        user_id=message.from_user.id
    )

    last = Database.get_last_waybill(vehicle['id'], message.from_user.id)
    if last:
        await state.update_data(
            previous_odo=last['odo_end'],
            previous_fuel=last['fuel_end'],
            previous_date=last['date']
        )
        await message.answer(
            f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
            f"📅 Последний: {last['date']}\n"
            f"🛣 Одометр: {last['odo_end']:.0f} км\n"
            f"⛽ Остаток: {last['fuel_end']:.3f} л\n\n"
            f"Использовать эти данные?",
            reply_markup=get_initial_data_keyboard()
        )
        await state.set_state(WaybillStates.initial_data_choice)
    else:
        await message.answer(
            f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n"
            f"⛽ Расход: {vehicle['fuel_rate']} л/100км\n"
            f"⏱️ Простой: {vehicle['idle_rate']} л/ч\n\n"
            f"🕒 Введите время выпуска (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.start_time)

# ════════════════════════════════════════════════════════════════════════════
# 🔄 ВЫБОР НАЧАЛЬНЫХ ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.initial_data_choice)
async def handle_initial_data_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    if message.text == "✅ Использовать данные предыдущего дня":
        await state.update_data(
            odo_start=data['previous_odo'],
            fuel_start=data['previous_fuel']
        )
        await message.answer(
            f"✅ Использованы данные от {data['previous_date']}:\n"
            f"🛣 Одометр: {data['previous_odo']:.0f} км\n"
            f"⛽ Топливо: {data['previous_fuel']:.3f} л\n\n"
            f"🕒 Введите время выпуска (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.start_time)
    else:
        await message.answer(
            "✏️ Введите показания одометра на начало дня (км):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.odo_start)

# ════════════════════════════════════════════════════════════════════════════
# 📝 ВВОД ВРЕМЕНИ И ОДОМЕТРА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.start_time)
async def start_time_input(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите ЧЧ:ММ (например 08:30):")
        return
    await state.update_data(start_time=message.text)
    data = await state.get_data()
    if 'odo_start' in data and 'fuel_start' in data:
        await message.answer("🕓 Введите время возвращения (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)
    else:
        if 'odo_start' not in data:
            await message.answer("🛣 Введите показания одометра на начало дня (км):")
            await state.set_state(WaybillStates.odo_start)
        else:
            await message.answer("⛽ Введите остаток топлива при выезде (л):")
            await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.odo_start)
async def odo_start_input(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите корректное число:")
        return
    await state.update_data(odo_start=value)
    data = await state.get_data()
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        await message.answer("⛽ Введите остаток топлива при выезде (л):")
        await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.fuel_start)
async def fuel_start_input(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите корректное число:")
        return
    await state.update_data(fuel_start=value)
    data = await state.get_data()
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        await message.answer("🕓 Введите время возвращения (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)

@router.message(WaybillStates.end_time)
async def end_time_input(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите ЧЧ:ММ:")
        return
    data = await state.get_data()
    hours = calculate_hours(data["start_time"], message.text)
    await state.update_data(end_time=message.text, hours=hours)
    await message.answer(
        f"⏱ Всего в наряде: <b>{hours} ч</b>\n\n"
        f"🚗 Введите показания одометра на конец дня (км):"
    )
    await state.set_state(WaybillStates.odo_end)

@router.message(WaybillStates.odo_end)
async def odo_end_input(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите корректное число:")
        return
    data = await state.get_data()
    odo_end = value
    distance = odo_end - data['odo_start']
    if distance < 0:
        await message.answer("❌ Одометр на конец не может быть меньше начального!")
        return
    await state.update_data(odo_end=odo_end, distance=distance)
    idle_rate = data.get('idle_rate', 0)
    await message.answer(
        f"📏 Пробег: <b>{distance:.0f} км</b>\n\n"
        f"<b>Выберите способ перерасхода:</b>\n"
        f"• Ввести в литрах\n"
        f"• Рассчитать по простою ({idle_rate} л/ч × часы)\n"
        f"• Нет перерасхода",
        reply_markup=get_overuse_keyboard()
    )
    await state.set_state(WaybillStates.overuse_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⏱️ РАСЧЁТ ПЕРЕРАСХОДА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.overuse_choice)
async def overuse_choice(message: Message, state: FSMContext):
    if message.text == "💵 Ввести перерасход в литрах":
        await message.answer("💵 Введите количество перерасхода (л):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(WaybillStates.overuse_manual)
    elif message.text == "⏱ Рассчитать по простою":
        await message.answer(
            "⏱️ Введите количество часов простоя:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.idle_hours)
    elif message.text == "⏭ Нет перерасхода":
        await state.update_data(overuse=0, overuse_type="none", idle_hours=0)
        await message.answer("💰 Введите экономию (л) или 0:", reply_markup=get_skip_keyboard())
        await state.set_state(WaybillStates.economy)
    else:
        await message.answer("❌ Выберите вариант из клавиатуры:", reply_markup=get_overuse_keyboard())

@router.message(WaybillStates.overuse_manual)
async def overuse_manual(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите число:")
        return
    await state.update_data(overuse=value, overuse_type="manual", idle_hours=0)
    await message.answer("💰 Введите экономию (л) или 0:", reply_markup=get_skip_keyboard())
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.idle_hours)
async def idle_hours_input(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите число:")
        return
    data = await state.get_data()
    idle_rate = data['idle_rate']
    overuse = round(value * idle_rate, 3)
    await state.update_data(idle_hours=value, overuse=overuse, overuse_type="idle")
    await message.answer(
        f"✅ Перерасход по простою: {value:.1f} ч × {idle_rate} л/ч = {overuse:.3f} л\n\n"
        f"💰 Введите экономию (л) или 0:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def economy_input(message: Message, state: FSMContext):
    if message.text == "⏭ Пропустить":
        economy = 0.0
    else:
        valid, value, err = validate_number(message.text, min_val=0)
        if not valid:
            await message.answer(f"❌ {err}\nВведите число или нажмите 'Пропустить':")
            return
        economy = value

    data = await state.get_data()
    fuel_start = data['fuel_start']
    distance = data['distance']
    fuel_rate_per_100km = data['fuel_rate']          # л/100км
    fuel_rate_per_km = fuel_rate_per_100km / 100.0   # л/км

    # Расчёт с округлением до 3 знаков
    fuel_norm = round(distance * fuel_rate_per_km, 3)
    overuse = data.get('overuse', 0.0)
    fuel_actual = round(fuel_norm - economy + overuse, 3)
    fuel_end_calculated = round(fuel_start - fuel_actual, 3)

    await state.update_data(
        economy=economy,
        fuel_norm=fuel_norm,
        fuel_actual=fuel_actual,
        fuel_end_calculated=fuel_end_calculated,
        fuel_rate_per_km=fuel_rate_per_km
    )

    # Информация о перерасходе
    overuse_type = data.get('overuse_type', 'none')
    overuse_info = ""
    if overuse_type == 'manual':
        overuse_info = f"💵 Ручной ввод: {overuse:.3f} л"
    elif overuse_type == 'idle':
        idle_hours = data.get('idle_hours', 0)
        idle_rate = data['idle_rate']
        overuse_info = f"⏱️ По простою: {idle_hours:.1f} ч × {idle_rate} л/ч = {overuse:.3f} л"
    else:
        overuse_info = "⏭ Нет перерасхода"

    await message.answer(
        f"📊 <b>ПРЕДВАРИТЕЛЬНЫЙ РАСЧЁТ</b>\n"
        f"⛽ Топливо начало: {fuel_start:.3f} л\n"
        f"📏 Пробег: {distance:.0f} км\n"
        f"📊 Норма: {fuel_norm:.3f} л\n"
        f"📈 {overuse_info}\n"
        f"📉 Экономия: {economy:.3f} л\n"
        f"📉 Факт. расход: {fuel_actual:.3f} л\n"
        f"📉 Остаток (расчёт): {fuel_end_calculated:.3f} л\n\n"
        f"<b>Выберите способ ввода остатка:</b>",
        reply_markup=get_fuel_end_keyboard()
    )
    await state.set_state(WaybillStates.fuel_end_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⛽ ВВОД ОСТАТКА ТОПЛИВА (С ОКРУГЛЕНИЕМ)
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.fuel_end_choice)
async def fuel_end_choice(message: Message, state: FSMContext):
    data = await state.get_data()
    calc = data['fuel_end_calculated']

    if message.text == "📊 Рассчитать автоматически":
        await state.update_data(fuel_end=calc, fuel_refuel=0, fuel_end_manual=0)
        await calculate_and_save_waybill(message, state)
    elif message.text == "✏️ Ввести остаток вручную":
        await message.answer(
            f"✏️ Введите остаток топлива (л):\n"
            f"<i>Расчётный остаток: {calc:.3f} л</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_end_manual)
    elif message.text == "⛽ Добавить заправку":
        await message.answer(
            f"⛽ Введите количество заправленного топлива (л):\n"
            f"<i>После заправки остаток = {calc:.3f} + заправка</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_refuel)
    else:
        await message.answer("❌ Выберите вариант из клавиатуры:", reply_markup=get_fuel_end_keyboard())

@router.message(WaybillStates.fuel_end_manual)
async def fuel_end_manual(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите число:")
        return
    data = await state.get_data()
    calc = data['fuel_end_calculated']
    fuel_refuel = round(max(0.0, value - calc), 3)
    await state.update_data(fuel_end=value, fuel_refuel=fuel_refuel, fuel_end_manual=1)
    await calculate_and_save_waybill(message, state)

@router.message(WaybillStates.fuel_refuel)
async def fuel_refuel_input(message: Message, state: FSMContext):
    valid, value, err = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {err}\nВведите число:")
        return
    data = await state.get_data()
    calc = data['fuel_end_calculated']
    fuel_end = round(calc + value, 3)
    await state.update_data(fuel_end=fuel_end, fuel_refuel=value, fuel_end_manual=0)
    await calculate_and_save_waybill(message, state)

# ════════════════════════════════════════════════════════════════════════════
# 💾 ФИНАЛЬНЫЙ РАСЧЁТ И СОХРАНЕНИЕ
# ════════════════════════════════════════════════════════════════════════════

async def calculate_and_save_waybill(message: Message, state: FSMContext):
    data = await state.get_data()
    required = ['odo_start', 'odo_end', 'fuel_start', 'fuel_end', 'start_time', 'end_time',
                'fuel_rate', 'fuel_actual', 'vehicle_id', 'user_id', 'vehicle_number', 'idle_rate']
    for field in required:
        if field not in data:
            await message.answer(f"❌ Ошибка: отсутствует {field}. Начните заново.", reply_markup=get_main_keyboard())
            await state.clear()
            return

    distance = data['odo_end'] - data['odo_start']
    fuel_norm = data['fuel_norm']
    overuse = data.get('overuse', 0)
    economy = data.get('economy', 0)
    fuel_actual = data['fuel_actual']
    fuel_start = data['fuel_start']
    fuel_end = data['fuel_end']
    fuel_refuel = data.get('fuel_refuel', 0)
    fuel_end_manual = data.get('fuel_end_manual', 0)
    idle_hours = data.get('idle_hours', 0)
    idle_rate = data['idle_rate']
    overuse_type = data.get('overuse_type', '')
    hours = data.get('hours', 0)
    fuel_rate_per_100km = data['fuel_rate']

    # Формируем описание перерасхода
    if overuse_type == 'idle':
        overuse_desc = f"⏱️ {idle_hours:.1f} ч × {idle_rate} л/ч = {overuse:.3f} л"
    elif overuse_type == 'manual':
        overuse_desc = f"💵 {overuse:.3f} л"
    else:
        overuse_desc = "⏭ Нет"

    # Сохраняем
    waybill_data = {
        'vehicle_id': data['vehicle_id'],
        'user_id': data['user_id'],
        'start_time': data['start_time'],
        'end_time': data['end_time'],
        'hours': hours,
        'idle_hours': idle_hours,
        'odo_start': data['odo_start'],
        'odo_end': data['odo_end'],
        'distance': distance,
        'fuel_start': fuel_start,
        'fuel_end': fuel_end,
        'fuel_refuel': fuel_refuel,
        'fuel_norm': fuel_norm,
        'fuel_actual': fuel_actual,
        'overuse': overuse,
        'overuse_type': overuse_type,
        'economy': economy,
        'fuel_rate': fuel_rate_per_100km,
        'idle_rate': idle_rate,
        'fuel_end_manual': fuel_end_manual
    }
    waybill_id = Database.save_waybill(waybill_data)

    if waybill_id:
        report = f"""
✅ <b>ПУТЕВОЙ ЛИСТ #{waybill_id} СОХРАНЕН</b>
━━━━━━━━━━━━━━━━━━━━━━━━━

🚗 <b>Автомобиль:</b> {data['vehicle_number']}
📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d')}

<b>📋 ВВЕДЕННЫЕ ДАННЫЕ</b>
🕒 Выезд: {data['start_time']}
🕓 Возврат: {data['end_time']}
⏱ Всего: {hours:.1f} ч
{f'⏱ Простой: {idle_hours:.1f} ч' if idle_hours > 0 else ''}
🛣 Одометр начало: {data['odo_start']:.0f} км
🛣 Одометр конец: {data['odo_end']:.0f} км
⛽ Топливо начало: {fuel_start:.3f} л
📈 Перерасход: {overuse_desc}
📉 Экономия: {economy:.3f} л
{f'⛽ Заправка: {fuel_refuel:.3f} л' if fuel_refuel > 0 else ''}
{f'✏️ Остаток вручную: {fuel_end:.3f} л' if fuel_end_manual else ''}

<b>📊 РАСЧЁТНЫЕ ПОКАЗАТЕЛИ</b>
📏 Пробег: {distance:.0f} км
📊 Норма расхода: {fuel_rate_per_100km} л/100км
📊 Расход по норме: {fuel_norm:.3f} л
📉 Фактический расход: {fuel_actual:.3f} л
⛽ Остаток топлива: <b>{fuel_end:.3f} л</b>
━━━━━━━━━━━━━━━━━━━━━━━━━

✅ Данные сохранены. Для следующего дня будут доступны:
🛣 Одометр: {data['odo_end']:.0f} км
⛽ Остаток: {fuel_end:.3f} л
        """
        await message.answer(report, reply_markup=get_main_keyboard())
        logger.info(f"✅ Пользователь {data['user_id']} сохранил путевой лист #{waybill_id}")
    else:
        await message.answer("❌ Ошибка сохранения", reply_markup=get_main_keyboard())
        logger.error(f"❌ Ошибка сохранения путевого листа пользователем {data['user_id']}")
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК ДЛЯ RAILWAY
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    logger.info("=" * 70)
    logger.info("🚀 Бот учета путевых листов v3.1 (Railway)")
    logger.info("=" * 70)
    init_database()
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот: @{bot_info.username}")
    logger.info("✅ База данных готова")
    logger.info("✅ Все расчёты с точностью до 3 знаков")
    logger.info("=" * 70)
    logger.info("✅ БОТ ЗАПУЩЕН")
    logger.info("=" * 70)

async def on_shutdown():
    logger.info("🔄 Завершение...")
    await bot.session.close()
    logger.info("✅ Ресурсы освобождены")

async def main():
    try:
        await on_startup()
        await bot.delete_webhook(drop_pending_updates=True)
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("⚠️ Остановка по запросу")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
    finally:
        await on_shutdown()

if __name__ == "__main__":
    asyncio.run(main())
