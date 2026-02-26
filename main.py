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
# ⚙️  НАСТРОЙКА ЛОГИРОВАНИЯ
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

logger.info("✅ BOT_TOKEN получен")

# ════════════════════════════════════════════════════════════════════════════
# 🤖 ИНИЦИАЛИЗАЦИЯ БОТА
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
# 💾 БАЗА ДАННЫХ
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
                fuel_rate REAL NOT NULL,
                idle_rate REAL NOT NULL,
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
# 📊 КЛАСС ДЛЯ РАБОТЫ С БД
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
                    AVG(fuel_actual / NULLIF(distance, 0) * 100) as avg_consumption
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
        datetime.strptime(time_str.strip(), "%H:%M")
        return True
    except ValueError:
        return False

def validate_number(value: str, min_val: float = None, max_val: float = None) -> tuple:
    try:
        text = value.replace(',', '.').strip()
        num = float(text)
        if min_val is not None and num < min_val:
            return False, 0, f"Значение не может быть меньше {min_val}"
        if max_val is not None and num > max_val:
            return False, 0, f"Значение не может быть больше {max_val}"
        return True, num, ""
    except ValueError:
        return False, 0, "Пожалуйста, введите корректное число"

def r3(value: float) -> float:
    """Округление до 3 знаков — главное исправление ошибки округления"""
    return round(value, 3)

# ════════════════════════════════════════════════════════════════════════════
# 🏠 ОБРАБОТЧИКИ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    logger.info(f"🚀 Пользователь {message.from_user.id} запустил бота")
    await message.answer(
        "<b>🚛 Система учёта путевых листов v3.1</b>\n\n"
        "Ведите учёт пробега и расхода топлива прямо в Telegram.\n\n"
        "<b>Возможности:</b>\n"
        "• Учёт расхода на 100 км и при простое (л/ч)\n"
        "• Расчёт перерасхода по литрам или по часам простоя\n"
        "• Ручной ввод и автоматический расчёт остатка топлива\n"
        "• Учёт заправки\n"
        "• Статистика за 7 дней\n\n"
        "Выберите действие:",
        reply_markup=get_main_keyboard()
    )

@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(
        "<b>📋 Команды:</b>\n"
        "/start — Главное меню\n"
        "/help — Справка\n"
        "/cancel — Отмена действия\n"
        "/stats — Общая статистика\n\n"
        "<b>Как работать:</b>\n"
        "1. Добавьте автомобиль (номер, расход на 100 км, расход при простое)\n"
        "2. Создайте путевой лист — введите данные за день\n"
        "3. Бот рассчитает пробег, расход и остаток топлива\n\n"
        "<b>Формат ввода:</b>\n"
        "• Время: ЧЧ:ММ (например 08:30)\n"
        "• Числа: целые или дробные (разделитель — точка или запятая)"
    )

@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state is None:
        await message.answer("🤷 Нет активных действий для отмены", reply_markup=get_main_keyboard())
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
            f"🛣️ Общий пробег: {total_distance:.0f} км\n"
            f"⛽ Общий расход: {total_fuel:.3f} л\n"
            f"⏱️ Общий простой: {total_idle_hours:.1f} ч\n"
            f"📈 Общий перерасход: {total_overuse:.3f} л"
        )
    except Exception as e:
        logger.error(f"❌ Ошибка статистики: {e}")
        await message.answer("❌ Ошибка получения статистики")

# ════════════════════════════════════════════════════════════════════════════
# 🚗 ДОБАВЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "🚗 Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    await state.update_data(action='add_vehicle')
    await message.answer("🚗 Введите государственный номер автомобиля:", reply_markup=ReplyKeyboardRemove())
    await state.set_state(AddVehicleStates.number)

@router.message(AddVehicleStates.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    number = message.text.strip().upper()
    if len(number) < 3:
        await message.answer("❌ Номер слишком короткий. Попробуйте ещё раз:")
        return
    await state.update_data(number=number)
    await message.answer(
        "⛽ Введите <b>расход на 100 км</b> (л/100км):\n"
        "Например: <code>15.5</code>"
    )
    await state.set_state(AddVehicleStates.fuel_rate)

@router.message(AddVehicleStates.fuel_rate)
async def add_vehicle_fuel_rate(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0.1, max_val=100)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число (например: <code>15.5</code>):")
        return
    await state.update_data(fuel_rate=value)
    await message.answer(
        "⏱️ Введите <b>расход при простое</b> (л/ч):\n"
        "Например: <code>2.0</code>"
    )
    await state.set_state(AddVehicleStates.idle_rate)

@router.message(AddVehicleStates.idle_rate)
async def add_vehicle_idle_rate(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0.1, max_val=10)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число (например: <code>2.0</code>):")
        return

    data = await state.get_data()
    idle_rate = value

    # Проверяем режим: добавление или редактирование
    if data.get('action') == 'edit_vehicle' and 'edit_vehicle_id' in data:
        success = Database.update_vehicle(data['edit_vehicle_id'], data['fuel_rate'], idle_rate)
        if success:
            await message.answer(
                f"✅ Автомобиль <b>{data['edit_vehicle_number']}</b> обновлён!\n\n"
                f"⛽ Расход на 100 км: {data['fuel_rate']} л/100км\n"
                f"⏱️ Расход при простое: {idle_rate} л/ч",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer("❌ Ошибка обновления. Попробуйте снова.", reply_markup=get_main_keyboard())
    else:
        vehicle_id = Database.add_vehicle(data['number'], data['fuel_rate'], idle_rate)
        if vehicle_id:
            await message.answer(
                f"✅ Автомобиль <b>{data['number']}</b> добавлен!\n\n"
                f"⛽ Расход на 100 км: {data['fuel_rate']} л/100км\n"
                f"⏱️ Расход при простое: {idle_rate} л/ч",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                f"❌ Автомобиль {data['number']} уже существует!",
                reply_markup=get_main_keyboard()
            )

    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# ✏️ РЕДАКТИРОВАНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "✏️ Редактировать автомобиль")
async def edit_vehicle_start(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет зарегистрированных автомобилей.", reply_markup=get_main_keyboard())
        return
    await state.update_data(vehicles=vehicles, action='edit_vehicle')
    await message.answer("🚗 Выберите автомобиль для редактирования:", reply_markup=get_vehicles_keyboard(vehicles))

# ════════════════════════════════════════════════════════════════════════════
# 📊 СПИСОК АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📊 Мои автомобили")
async def list_vehicles(message: Message):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет зарегистрированных автомобилей.", reply_markup=get_main_keyboard())
        return
    text = "<b>🚗 СПИСОК АВТОМОБИЛЕЙ</b>\n" + "━" * 38 + "\n\n"
    for v in vehicles:
        text += (
            f"<b>🚙 {v['number']}</b>\n"
            f"⛽ Расход: {v['fuel_rate']} л/100км\n"
            f"⏱️ Простой: {v['idle_rate']} л/ч\n\n"
        )
    text += "━" * 38 + "\n"
    text += "✏️ Используйте «Редактировать автомобиль» для изменения параметров."
    await message.answer(text)

# ════════════════════════════════════════════════════════════════════════════
# 📈 СТАТИСТИКА ПО АВТОМОБИЛЮ
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📈 Статистика")
async def show_statistics(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    if not vehicles:
        await message.answer("❌ Нет автомобилей для статистики.", reply_markup=get_main_keyboard())
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
    await message.answer("🚗 Выберите автомобиль для путевого листа:", reply_markup=get_vehicles_keyboard(vehicles))
    logger.info(f"📝 Пользователь {message.from_user.id} начал новый путевой лист")

# ════════════════════════════════════════════════════════════════════════════
# 🚙 ВЫБОР АВТОМОБИЛЯ — ОБЩИЙ ОБРАБОТЧИК
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text.startswith("🚙 "))
async def vehicle_selected(message: Message, state: FSMContext):
    """Универсальный обработчик выбора автомобиля"""
    data = await state.get_data()
    action = data.get('action')
    vehicles = data.get('vehicles', [])

    if not action:
        return

    # Парсим номер из кнопки
    try:
        vehicle_text = message.text[2:].strip()
        vehicle_number = vehicle_text.split(" (")[0]
    except Exception:
        await message.answer("❌ Ошибка выбора. Попробуйте снова.", reply_markup=get_main_keyboard())
        await state.clear()
        return

    vehicle = next((v for v in vehicles if v['number'] == vehicle_number), None)
    if not vehicle:
        await message.answer("❌ Автомобиль не найден.", reply_markup=get_main_keyboard())
        await state.clear()
        return

    user_id = message.from_user.id

    # ── Статистика ──
    if action == 'stats':
        stats = Database.get_statistics(vehicle['id'], user_id, 7)
        if not stats or not stats['trips']:
            await message.answer(
                f"<b>📊 Статистика: {vehicle['number']}</b>\n\nНет данных за последние 7 дней.",
                reply_markup=get_main_keyboard()
            )
        else:
            avg = stats['avg_consumption'] or 0
            await message.answer(
                f"<b>📊 Статистика: {vehicle['number']}</b>\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"<b>За последние 7 дней:</b>\n"
                f"🚗 Поездок: {stats['trips']}\n"
                f"📏 Пробег: {stats['total_distance']:.0f} км\n"
                f"⛽ Топливо: {stats['total_fuel']:.3f} л\n"
                f"⏱️ Простой: {stats['total_idle_hours']:.1f} ч\n"
                f"📈 Перерасход: {stats['total_overuse']:.3f} л\n"
                f"⛽ Заправлено: {stats['total_refuel']:.3f} л\n"
                f"📊 Средний расход: {avg:.2f} л/100км",
                reply_markup=get_main_keyboard()
            )
        await state.clear()

    # ── Редактирование ──
    elif action == 'edit_vehicle':
        await state.update_data(
            edit_vehicle_id=vehicle['id'],
            edit_vehicle_number=vehicle['number']
        )
        await message.answer(
            f"✏️ <b>Редактирование: {vehicle['number']}</b>\n\n"
            f"Текущие параметры:\n"
            f"⛽ Расход на 100 км: {vehicle['fuel_rate']} л/100км\n"
            f"⏱️ Расход при простое: {vehicle['idle_rate']} л/ч\n\n"
            f"Введите <b>новый расход на 100 км</b> (л/100км):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(AddVehicleStates.fuel_rate)

    # ── Путевой лист ──
    elif action == 'waybill':
        await state.update_data(
            vehicle_id=vehicle['id'],
            vehicle_number=vehicle['number'],
            fuel_rate=vehicle['fuel_rate'],
            idle_rate=vehicle['idle_rate'],
            user_id=user_id
        )

        last = Database.get_last_waybill(vehicle['id'], user_id)
        if last:
            await state.update_data(
                previous_odo=last['odo_end'],
                previous_fuel=last['fuel_end'],
                previous_date=last['date']
            )
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
                f"📅 Последний путевой лист: {last['date']}\n"
                f"🛣 Одометр конец: {last['odo_end']:.0f} км\n"
                f"⛽ Остаток топлива: {last['fuel_end']:.3f} л\n\n"
                f"<b>Использовать эти данные как начальные?</b>",
                reply_markup=get_initial_data_keyboard()
            )
            await state.set_state(WaybillStates.initial_data_choice)
        else:
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n"
                f"⛽ Расход: {vehicle['fuel_rate']} л/100км | ⏱️ Простой: {vehicle['idle_rate']} л/ч\n\n"
                f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.set_state(WaybillStates.start_time)

# ════════════════════════════════════════════════════════════════════════════
# 🗂️  НАЧАЛЬНЫЕ ДАННЫЕ
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
            f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
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
# 📋 ВВОД ДАННЫХ ПУТЕВОГО ЛИСТА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.start_time)
async def start_time_input(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: <code>08:30</code>):")
        return
    await state.update_data(start_time=message.text.strip())
    data = await state.get_data()
    if 'odo_start' in data and 'fuel_start' in data:
        await message.answer("🕓 Введите время возвращения с линии (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)
    elif 'odo_start' not in data:
        await message.answer("🛣 Введите показания одометра на начало дня (км):")
        await state.set_state(WaybillStates.odo_start)
    else:
        await message.answer("⛽ Введите остаток топлива при выезде (л):")
        await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.odo_start)
async def odo_start_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    await state.update_data(odo_start=value)
    data = await state.get_data()
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска на линию (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        await message.answer("⛽ Введите остаток топлива при выезде (л):")
        await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.fuel_start)
async def fuel_start_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    await state.update_data(fuel_start=value)
    data = await state.get_data()
    if 'start_time' not in data:
        await message.answer("🕒 Введите время выпуска на линию (ЧЧ:ММ):")
        await state.set_state(WaybillStates.start_time)
    else:
        await message.answer("🕓 Введите время возвращения с линии (ЧЧ:ММ):")
        await state.set_state(WaybillStates.end_time)

@router.message(WaybillStates.end_time)
async def end_time_input(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: <code>17:30</code>):")
        return
    data = await state.get_data()
    hours = calculate_hours(data["start_time"], message.text.strip())
    await state.update_data(end_time=message.text.strip(), hours=hours)
    await message.answer(
        f"⏱ Всего в наряде: <b>{hours} ч</b>\n\n"
        "🚗 Введите показания одометра на конец дня (км):"
    )
    await state.set_state(WaybillStates.odo_end)

@router.message(WaybillStates.odo_end)
async def odo_end_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    data = await state.get_data()
    distance = value - data['odo_start']
    if distance < 0:
        await message.answer("❌ Показания одометра не могут быть меньше начальных!")
        return
    await state.update_data(odo_end=value, distance=distance)
    idle_rate = data.get('idle_rate', 0)
    await message.answer(
        f"📏 Пробег за день: <b>{distance:.0f} км</b>\n\n"
        f"<b>Выберите способ расчёта перерасхода:</b>\n"
        f"• Ввести перерасход в литрах\n"
        f"• Рассчитать по простою ({idle_rate} л/ч × часы простоя)\n"
        f"• Нет перерасхода",
        reply_markup=get_overuse_keyboard()
    )
    await state.set_state(WaybillStates.overuse_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⏱️ ПЕРЕРАСХОД
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.overuse_choice)
async def overuse_choice_input(message: Message, state: FSMContext):
    if message.text == "💵 Ввести перерасход в литрах":
        await message.answer("💵 Введите перерасход топлива (л):", reply_markup=ReplyKeyboardRemove())
        await state.set_state(WaybillStates.overuse_manual)
    elif message.text == "⏱ Рассчитать по простою":
        data = await state.get_data()
        await message.answer(
            f"⏱️ Введите количество часов простоя:\n"
            f"<i>Перерасход = часы × {data['idle_rate']} л/ч</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.idle_hours)
    elif message.text == "⏭ Нет перерасхода":
        await state.update_data(overuse=0.0, overuse_type="none", idle_hours=0.0)
        await message.answer("💰 Введите экономию топлива (л) или 0:", reply_markup=get_skip_keyboard())
        await state.set_state(WaybillStates.economy)
    else:
        await message.answer("❌ Выберите вариант из клавиатуры:", reply_markup=get_overuse_keyboard())

@router.message(WaybillStates.overuse_manual)
async def overuse_manual_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    await state.update_data(overuse=r3(value), overuse_type="manual", idle_hours=0.0)
    await message.answer("💰 Введите экономию топлива (л) или 0:", reply_markup=get_skip_keyboard())
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.idle_hours)
async def idle_hours_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    data = await state.get_data()
    idle_rate = data['idle_rate']
    overuse = r3(value * idle_rate)
    await state.update_data(idle_hours=value, overuse=overuse, overuse_type="idle")
    await message.answer(
        f"✅ Перерасход по простою:\n"
        f"⏱️ {value:.1f} ч × {idle_rate} л/ч = <b>{overuse:.3f} л</b>\n\n"
        f"💰 Введите экономию топлива (л) или 0:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def economy_input(message: Message, state: FSMContext):
    if message.text == "⏭ Пропустить":
        economy = 0.0
    else:
        valid, value, error = validate_number(message.text, min_val=0)
        if not valid:
            await message.answer(f"❌ {error}\nВведите число или нажмите «Пропустить»:")
            return
        economy = value

    data = await state.get_data()
    fuel_start = data['fuel_start']
    distance = data['distance']
    fuel_rate_per_km = data['fuel_rate'] / 100.0

    # ───── ИСПРАВЛЕНИЕ: все промежуточные значения округляем до 3 знаков ─────
    fuel_norm = r3(distance * fuel_rate_per_km)
    overuse   = data.get('overuse', 0.0)
    fuel_actual = r3(fuel_norm - economy + overuse)
    fuel_end_calculated = r3(fuel_start - fuel_actual)
    # ─────────────────────────────────────────────────────────────────────────

    await state.update_data(
        economy=economy,
        fuel_norm=fuel_norm,
        fuel_actual=fuel_actual,
        fuel_end_calculated=fuel_end_calculated
    )

    overuse_type = data.get('overuse_type', 'none')
    if overuse_type == 'manual':
        overuse_info = f"💵 Ручной ввод: {overuse:.3f} л"
    elif overuse_type == 'idle':
        ih = data.get('idle_hours', 0)
        ir = data['idle_rate']
        overuse_info = f"⏱️ По простою: {ih:.1f} ч × {ir} л/ч = {overuse:.3f} л"
    else:
        overuse_info = "⏭ Нет перерасхода"

    await message.answer(
        f"📊 <b>ПРЕДВАРИТЕЛЬНЫЙ РАСЧЁТ</b>\n"
        f"⛽ Топливо начало: {fuel_start:.3f} л\n"
        f"📏 Пробег: {distance:.0f} км\n"
        f"📊 Норма расхода: {fuel_norm:.3f} л\n"
        f"📈 {overuse_info}\n"
        f"📉 Экономия: {economy:.3f} л\n"
        f"📉 Факт. расход: {fuel_actual:.3f} л\n"
        f"📉 Остаток (расчёт): <b>{fuel_end_calculated:.3f} л</b>\n\n"
        f"<b>Выберите способ ввода остатка топлива:</b>",
        reply_markup=get_fuel_end_keyboard()
    )
    await state.set_state(WaybillStates.fuel_end_choice)

# ════════════════════════════════════════════════════════════════════════════
# ⛽ ОСТАТОК ТОПЛИВА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.fuel_end_choice)
async def fuel_end_choice_input(message: Message, state: FSMContext):
    data = await state.get_data()
    calc = data['fuel_end_calculated']

    if message.text == "📊 Рассчитать автоматически":
        await state.update_data(fuel_end=calc, fuel_refuel=0.0, fuel_end_manual=0)
        await calculate_and_save_waybill(message, state)

    elif message.text == "✏️ Ввести остаток вручную":
        await message.answer(
            f"✏️ Введите остаток топлива на конец дня (л):\n"
            f"<i>Расчётный остаток: {calc:.3f} л</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_end_manual)

    elif message.text == "⛽ Добавить заправку":
        await message.answer(
            f"⛽ Введите количество заправленного топлива (л):\n"
            f"<i>После заправки остаток = {calc:.3f} л + заправка</i>",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_refuel)

    else:
        await message.answer("❌ Выберите вариант из клавиатуры:", reply_markup=get_fuel_end_keyboard())

@router.message(WaybillStates.fuel_end_manual)
async def fuel_end_manual_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    data = await state.get_data()
    calc = data['fuel_end_calculated']
    # Если ввели больше расчётного — разница считается заправкой
    fuel_refuel = r3(value - calc) if value > calc else 0.0
    await state.update_data(fuel_end=r3(value), fuel_refuel=fuel_refuel, fuel_end_manual=1)
    await calculate_and_save_waybill(message, state)

@router.message(WaybillStates.fuel_refuel)
async def fuel_refuel_input(message: Message, state: FSMContext):
    valid, value, error = validate_number(message.text, min_val=0)
    if not valid:
        await message.answer(f"❌ {error}\nВведите корректное число:")
        return
    data = await state.get_data()
    calc = data['fuel_end_calculated']
    fuel_end = r3(calc + value)
    await state.update_data(fuel_end=fuel_end, fuel_refuel=r3(value), fuel_end_manual=0)
    await calculate_and_save_waybill(message, state)

# ════════════════════════════════════════════════════════════════════════════
# 💾 ФИНАЛЬНЫЙ РАСЧЁТ И СОХРАНЕНИЕ
# ════════════════════════════════════════════════════════════════════════════

async def calculate_and_save_waybill(message: Message, state: FSMContext):
    data = await state.get_data()

    required = ['odo_start', 'odo_end', 'fuel_start', 'fuel_end',
                'start_time', 'end_time', 'fuel_rate', 'fuel_actual',
                'vehicle_id', 'user_id', 'vehicle_number', 'idle_rate']
    for field in required:
        if field not in data:
            await message.answer(f"❌ Ошибка: поле «{field}» отсутствует. Начните заново.", reply_markup=get_main_keyboard())
            await state.clear()
            return

    distance      = r3(data['odo_end'] - data['odo_start'])
    fuel_norm     = data['fuel_norm']
    overuse       = data.get('overuse', 0.0)
    economy       = data.get('economy', 0.0)
    fuel_actual   = data['fuel_actual']
    fuel_start    = data['fuel_start']
    fuel_end      = data['fuel_end']
    fuel_refuel   = data.get('fuel_refuel', 0.0)
    fuel_end_manual = data.get('fuel_end_manual', 0)
    idle_hours    = data.get('idle_hours', 0.0)
    idle_rate     = data['idle_rate']
    overuse_type  = data.get('overuse_type', '')
    hours         = data.get('hours', 0.0)
    fuel_rate_100 = data['fuel_rate']

    # Описание перерасхода
    if overuse_type == 'idle':
        overuse_desc = f"⏱️ {idle_hours:.1f} ч × {idle_rate} л/ч = {overuse:.3f} л"
    elif overuse_type == 'manual':
        overuse_desc = f"💵 {overuse:.3f} л"
    else:
        overuse_desc = "⏭ Нет"

    waybill_data = {
        'vehicle_id'    : data['vehicle_id'],
        'user_id'       : data['user_id'],
        'date'          : datetime.now().strftime('%Y-%m-%d'),
        'start_time'    : data['start_time'],
        'end_time'      : data['end_time'],
        'hours'         : hours,
        'idle_hours'    : idle_hours,
        'odo_start'     : data['odo_start'],
        'odo_end'       : data['odo_end'],
        'distance'      : distance,
        'fuel_start'    : fuel_start,
        'fuel_end'      : fuel_end,
        'fuel_refuel'   : fuel_refuel,
        'fuel_norm'     : fuel_norm,
        'fuel_actual'   : fuel_actual,
        'overuse'       : overuse,
        'overuse_type'  : overuse_type,
        'economy'       : economy,
        'fuel_rate'     : fuel_rate_100,
        'idle_rate'     : idle_rate,
        'fuel_end_manual': fuel_end_manual
    }

    waybill_id = Database.save_waybill(waybill_data)

    if waybill_id:
        idle_line   = f"\n⏱️ Простой: {idle_hours:.1f} ч" if idle_hours > 0 else ""
        refuel_line = f"\n⛽ Заправка: {fuel_refuel:.3f} л" if fuel_refuel > 0 else ""
        manual_line = f"\n✏️ Остаток введён вручную: {fuel_end:.3f} л" if fuel_end_manual else ""

        report = (
            f"✅ <b>ПУТЕВОЙ ЛИСТ #{waybill_id} СОХРАНЁН</b>\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚗 <b>Автомобиль:</b> {data['vehicle_number']}\n"
            f"📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d')}\n\n"
            f"<b>📋 ВВЕДЁННЫЕ ДАННЫЕ</b>\n"
            f"🕒 Выезд: {data['start_time']}\n"
            f"🕓 Возврат: {data['end_time']}\n"
            f"⏱ Всего в наряде: {hours:.1f} ч"
            f"{idle_line}\n"
            f"🛣 Одометр начало: {data['odo_start']:.0f} км\n"
            f"🛣 Одометр конец: {data['odo_end']:.0f} км\n"
            f"⛽ Топливо начало: {fuel_start:.3f} л\n"
            f"📈 Перерасход: {overuse_desc}\n"
            f"📉 Экономия: {economy:.3f} л"
            f"{refuel_line}"
            f"{manual_line}\n\n"
            f"<b>📊 РАСЧЁТНЫЕ ПОКАЗАТЕЛИ</b>\n"
            f"📏 Пробег: {distance:.0f} км\n"
            f"📊 Норма ({fuel_rate_100} л/100км): {fuel_norm:.3f} л\n"
            f"📉 Фактический расход: {fuel_actual:.3f} л\n"
            f"⛽ Остаток топлива: <b>{fuel_end:.3f} л</b>\n\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"<b>Формула:</b> {fuel_start:.3f} − {fuel_actual:.3f}"
            + (f" + {fuel_refuel:.3f}" if fuel_refuel > 0 else "")
            + f" = <b>{fuel_end:.3f} л</b>\n\n"
            f"✅ Данные сохранены. Для следующего дня:\n"
            f"🛣 Одометр: {data['odo_end']:.0f} км\n"
            f"⛽ Остаток: {fuel_end:.3f} л"
        )
        await message.answer(report, reply_markup=get_main_keyboard())
        logger.info(f"✅ Пользователь {data['user_id']} сохранил путевой лист #{waybill_id}")
    else:
        await message.answer("❌ Ошибка сохранения данных. Попробуйте ещё раз.", reply_markup=get_main_keyboard())
        logger.error(f"❌ Ошибка сохранения путевого листа пользователем {data['user_id']}")

    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК
# ════════════════════════════════════════════════════════════════════════════

async def on_startup():
    logger.info("=" * 70)
    logger.info("🚀 Бот учёта путевых листов v3.1")
    logger.info("=" * 70)
    init_database()
    bot_info = await bot.get_me()
    logger.info(f"✅ Бот: @{bot_info.username}")
    vehicles = Database.get_vehicles()
    logger.info(f"✅ Автомобилей в базе: {len(vehicles)}")
    logger.info("=" * 70)
    logger.info("✅ БОТ ГОТОВ К РАБОТЕ")
    logger.info("=" * 70)

async def on_shutdown():
    logger.info("🔄 Завершение работы...")
    await bot.session.close()
    logger.info("✅ Ресурсы освобождены")

async def main():
    try:
        await on_startup()
        await bot.delete_webhook(drop_pending_updates=True)
        logger.info("📡 Запуск polling...")
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    except KeyboardInterrupt:
        logger.info("⚠️ Остановка по запросу пользователя")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
        raise
    finally:
        await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("\n👋 До свидания!")
    except Exception as e:
        logger.error(f"💥 Фатальная ошибка: {e}")
