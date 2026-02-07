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
# 🔐 ЗАГРУЗКА ПЕРЕМЕННЫХ ОКРУЖЕНИЯ
# ════════════════════════════════════════════════════════════════════════════

# Для локальной разработки используем python-dotenv
try:
    from dotenv import load_dotenv
    load_dotenv()
    logger.info(".env файл загружен для локальной разработки")
except ImportError:
    logger.info("python-dotenv не установлен, используем переменные окружения системы")

# Получение токена из переменных окружения
BOT_TOKEN = os.getenv("BOT_TOKEN")

if not BOT_TOKEN:
    logger.error("BOT_TOKEN не найден в переменных окружения!")
    logger.info("На Railway добавьте переменную окружения BOT_TOKEN")
    logger.info("Локально: создайте .env файл с BOT_TOKEN=ваш_токен")
    exit(1)

logger.info("Бот инициализирован, токен получен")

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
# 💾 НАСТРОЙКА БАЗЫ ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

def get_db_connection():
    """Создание подключения к SQLite базе данных"""
    conn = sqlite3.connect('waybills.db', check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn

def init_database():
    """Инициализация базы данных при старте"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Таблица автомобилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL,
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
                fuel_norm REAL,
                fuel_actual REAL,
                overuse REAL DEFAULT 0,
                economy REAL DEFAULT 0,
                fuel_rate REAL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                FOREIGN KEY (vehicle_id) REFERENCES vehicles (id)
            )
        ''')
        
        # Индексы для улучшения производительности
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_user_date ON waybills(user_id, date)')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_date ON waybills(vehicle_id, date)')
        
        conn.commit()
        conn.close()
        logger.info("База данных инициализирована")
    except Exception as e:
        logger.error(f"Ошибка инициализации БД: {e}")

# ════════════════════════════════════════════════════════════════════════════
# 📊 КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float) -> Optional[int]:
        """Добавление нового автомобиля"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO vehicles (number, fuel_rate) VALUES (?, ?)",
                (number.upper(), fuel_rate)
            )
            conn.commit()
            vehicle_id = cursor.lastrowid
            conn.close()
            logger.info(f"Добавлен автомобиль {number}")
            return vehicle_id
        except sqlite3.IntegrityError:
            logger.warning(f"Автомобиль {number} уже существует")
            return None
        except Exception as e:
            logger.error(f"Ошибка добавления автомобиля: {e}")
            return None
    
    @staticmethod
    def get_vehicles() -> list:
        """Получение списка автомобилей"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate FROM vehicles ORDER BY number")
            vehicles = cursor.fetchall()
            conn.close()
            return vehicles
        except Exception as e:
            logger.error(f"Ошибка получения списка автомобилей: {e}")
            return []
    
    @staticmethod
    def get_vehicle(vehicle_id: int):
        """Получение информации об автомобиле"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, number, fuel_rate FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            conn.close()
            return vehicle
        except Exception as e:
            logger.error(f"Ошибка получения автомобиля: {e}")
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
            logger.error(f"Ошибка получения последнего путевого листа: {e}")
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
                 odo_start, odo_end, distance, fuel_start, fuel_end, 
                 fuel_norm, fuel_actual, overuse, economy, fuel_rate)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                data.get('fuel_norm'),
                data.get('fuel_actual'),
                data.get('overuse', 0),
                data.get('economy', 0),
                data.get('fuel_rate')
            ))
            conn.commit()
            waybill_id = cursor.lastrowid
            conn.close()
            logger.info(f"Сохранен путевой лист #{waybill_id}")
            return waybill_id
        except Exception as e:
            logger.error(f"Ошибка сохранения путевого листа: {e}")
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
                    AVG(fuel_actual/distance*100) as avg_consumption
                FROM waybills 
                WHERE vehicle_id = ? AND user_id = ? 
                AND date >= date('now', '-' || ? || ' days')
            ''', (vehicle_id, user_id, days))
            stats = cursor.fetchone()
            conn.close()
            return stats
        except Exception as e:
            logger.error(f"Ошибка получения статистики: {e}")
            return None

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM
# ════════════════════════════════════════════════════════════════════════════

class AddVehicleStates(StatesGroup):
    number = State()
    fuel_rate = State()

class WaybillStates(StatesGroup):
    vehicle_selected = State()
    start_time = State()
    odo_start = State()
    fuel_start = State()
    end_time = State()
    odo_end = State()
    overuse = State()
    economy = State()

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
            [KeyboardButton(text="📈 Статистика")]
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
        buttons.append([KeyboardButton(text=f"🚙 {vehicle['number']} ({vehicle['fuel_rate']} л/км)")])
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_confirm_keyboard(odo_value: float, fuel_value: float) -> ReplyKeyboardMarkup:
    """Клавиатура подтверждения данных"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=f"✅ Одометр: {odo_value:.0f} км")],
            [KeyboardButton(text=f"✅ Топливо: {fuel_value:.2f} л")],
            [KeyboardButton(text="✏️ Ввести вручную")]
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
        logger.error(f"Ошибка расчета часов: {e}")
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
    logger.info(f"Пользователь {message.from_user.id} запустил бота")
    
    await message.answer(
        "<b>🚛 Система учета путевых листов</b>\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
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

<b>📝 Как работать с ботом:</b>

1. <b>Добавьте автомобиль</b> - укажите гос. номер и норму расхода
2. <b>Создайте путевой лист</b> - заполните данные за день
3. <b>Бот автоматически рассчитает:</b>
   • Пробег за день
   • Расход по норме и фактический
   • Остаток топлива
4. <b>Смотрите статистику</b> за последние 7 дней

<b>⚠️ Внимание:</b>
• Время указывайте в формате ЧЧ:ММ
• Показания одометра - в километрах
• Топливо - в литрах
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
    logger.info(f"Пользователь {message.from_user.id} отменил действие")
    await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())

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
    logger.info(f"Пользователь {message.from_user.id} начал добавление автомобиля")

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
    
    data = await state.get_data()
    vehicle_id = Database.add_vehicle(data['number'], fuel_rate)
    
    if vehicle_id:
        await message.answer(
            f"✅ Автомобиль <b>{data['number']}</b> добавлен!\n"
            f"⛽ Норма расхода: {fuel_rate} л/км",
            reply_markup=get_main_keyboard()
        )
    else:
        await message.answer(
            f"❌ Автомобиль {data['number']} уже существует!",
            reply_markup=get_main_keyboard()
        )
    
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
        text += f"🚙 <b>{vehicle['number']}</b>\n⛽ Расход: {vehicle['fuel_rate']} л/км\n\n"
    
    await message.answer(text)

# ════════════════════════════════════════════════════════════════════════════
# 📈 СТАТИСТИКА
# ════════════════════════════════════════════════════════════════════════════

@router.message(F.text == "📈 Статистика")
async def show_statistics(message: Message, state: FSMContext):
    """Показ статистики"""
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ Нет автомобилей для статистики",
            reply_markup=get_main_keyboard()
        )
        return
    
    # Сохраняем список автомобилей для выбора
    await state.update_data(vehicles=vehicles, action='stats')
    
    await message.answer(
        "Выберите автомобиль для просмотра статистики:",
        reply_markup=get_vehicles_keyboard(vehicles)
    )

# ════════════════════════════════════════════════════════════════════════════
# 📝 НОВЫЙ ПУТЕВОЙ ЛИСТ
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
    logger.info(f"Пользователь {message.from_user.id} начал новый путевой лист")

# ════════════════════════════════════════════════════════════════════════════
# 🚙 ВЫБОР АВТОМОБИЛЯ
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
                f"⛽ Топлива: {stats['total_fuel']:.2f} л\n"
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
            user_id=user_id
        )
        
        # Проверяем последний путевой лист
        last_waybill = Database.get_last_waybill(vehicle['id'], user_id)
        
        if last_waybill:
            await state.update_data(
                suggested_odo=last_waybill['odo_end'],
                suggested_fuel=last_waybill['fuel_end']
            )
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
                f"📅 Последний путевой лист: {last_waybill['date']}\n"
                f"🛣 Одометр: {last_waybill['odo_end']:.0f} км\n"
                f"⛽ Остаток топлива: {last_waybill['fuel_end']:.2f} л\n\n"
                f"Использовать эти значения?",
                reply_markup=get_confirm_keyboard(last_waybill['odo_end'], last_waybill['fuel_end'])
            )
            await state.set_state(WaybillStates.vehicle_selected)
        else:
            await message.answer(
                f"🚗 Автомобиль: <b>{vehicle['number']}</b>\n\n"
                f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
                reply_markup=ReplyKeyboardRemove()
            )
            await state.set_state(WaybillStates.start_time)

# ════════════════════════════════════════════════════════════════════════════
# 📝 ПРОЦЕСС ЗАПОЛНЕНИЯ ПУТЕВОГО ЛИСТА
# ════════════════════════════════════════════════════════════════════════════

@router.message(WaybillStates.vehicle_selected)
async def handle_previous_data(message: Message, state: FSMContext):
    """Обработка выбора использования предыдущих данных"""
    data = await state.get_data()
    
    if message.text.startswith("✅ Одометр"):
        await state.update_data(odo_start=data['suggested_odo'])
        await message.answer(
            f"✅ Одометр: {data['suggested_odo']:.0f} км\n\n"
            f"⛽ Остаток топлива при выезде:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.fuel_start)
    elif message.text.startswith("✅ Топливо"):
        await state.update_data(fuel_start=data['suggested_fuel'])
        await message.answer(
            f"✅ Топливо: {data['suggested_fuel']:.2f} л\n\n"
            f"🛣 Показания одометра на начало дня:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.odo_start)
    else:
        await message.answer(
            "🕒 Введите время выпуска на линию (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(WaybillStates.start_time)

@router.message(WaybillStates.start_time)
async def start_time_input(message: Message, state: FSMContext):
    """Ввод времени начала"""
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: <code>08:30</code>)")
        return
    
    await state.update_data(start_time=message.text)
    await message.answer("🛣 Показания одометра на начало дня:")
    await state.set_state(WaybillStates.odo_start)

@router.message(WaybillStates.odo_start)
async def odo_start_input(message: Message, state: FSMContext):
    """Ввод показаний одометра на начало"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    await state.update_data(odo_start=float(message.text))
    await message.answer("⛽ Остаток топлива при выезде:")
    await state.set_state(WaybillStates.fuel_start)

@router.message(WaybillStates.fuel_start)
async def fuel_start_input(message: Message, state: FSMContext):
    """Ввод остатка топлива на начало"""
    if not validate_number(message.text):
        await message.answer("❌ Введите корректное число!")
        return
    
    await state.update_data(fuel_start=float(message.text))
    await message.answer("🕓 Время возвращения с линии (ЧЧ:ММ):")
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
        "🚗 Показания одометра на конец дня:"
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
    distance = odo_end - data["odo_start"]
    
    if distance < 0:
        await message.answer("❌ Показания одометра не могут быть меньше начальных!")
        return
    
    await state.update_data(odo_end=odo_end, distance=distance)
    await message.answer(
        f"📏 Пробег за день: <b>{distance:.0f} км</b>\n\n"
        "⚠️ Перерасход топлива (л) или пропустить:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.overuse)

@router.message(WaybillStates.overuse)
async def overuse_input(message: Message, state: FSMContext):
    """Ввод перерасхода"""
    if message.text == "⏭ Пропустить":
        await state.update_data(overuse=0)
    elif not validate_number(message.text):
        await message.answer("❌ Введите корректное число или нажмите 'Пропустить'!")
        return
    else:
        await state.update_data(overuse=float(message.text))
    
    await message.answer(
        "💰 Экономия топлива (л) или пропустить:",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def economy_input(message: Message, state: FSMContext):
    """Ввод экономии и расчет результатов"""
    if message.text == "⏭ Пропустить":
        economy = 0
    elif not validate_number(message.text):
        await message.answer("❌ Введите корректное число или нажмите 'Пропустить'!")
        return
    else:
        economy = float(message.text)
    
    await state.update_data(economy=economy)
    data = await state.get_data()
    
    # Расчеты
    fuel_norm = data['distance'] * data['fuel_rate']
    fuel_actual = fuel_norm - data['economy'] + data['overuse']
    fuel_end = data['fuel_start'] - fuel_actual
    
    # Сохранение в БД
    waybill_data = {
        'vehicle_id': data['vehicle_id'],
        'user_id': data['user_id'],
        'start_time': data['start_time'],
        'end_time': data['end_time'],
        'hours': data['hours'],
        'odo_start': data['odo_start'],
        'odo_end': data['odo_end'],
        'distance': data['distance'],
        'fuel_start': data['fuel_start'],
        'fuel_end': fuel_end,
        'fuel_norm': fuel_norm,
        'fuel_actual': fuel_actual,
        'overuse': data['overuse'],
        'economy': data['economy'],
        'fuel_rate': data['fuel_rate']
    }
    
    waybill_id = Database.save_waybill(waybill_data)
    
    if waybill_id:
        # Формирование отчета
        report = f"""
✅ <b>ПУТЕВОЙ ЛИСТ #{waybill_id} СОХРАНЕН</b>
━━━━━━━━━━━━━━━━━━━━━

🚗 <b>Автомобиль:</b> {data['vehicle_number']}
📅 <b>Дата:</b> {datetime.now().strftime('%Y-%m-%d')}

<b>📋 ВВЕДЕННЫЕ ДАННЫЕ:</b>
🕒 Время выезда: {data['start_time']}
🕓 Время возвращения: {data['end_time']}
⏱ Всего в наряде: {data['hours']} ч
🛣 Одометр начало: {data['odo_start']:.0f} км
🛣 Одометр конец: {data['odo_end']:.0f} км
⛽ Топливо начало: {data['fuel_start']:.2f} л
📈 Перерасход: {data['overuse']:.2f} л
📉 Экономия: {data['economy']:.2f} л

<b>📊 РАСЧЕТНЫЕ ПОКАЗАТЕЛИ:</b>
📏 Пробег за день: {data['distance']:.0f} км
📈 Расход по норме: {fuel_norm:.2f} л
📉 Фактический расход: {fuel_actual:.2f} л
⛽ Остаток топлива: {fuel_end:.2f} л
━━━━━━━━━━━━━━━━━━━━━

✅ Данные успешно сохранены!
        """
        
        await message.answer(report, reply_markup=get_main_keyboard())
        logger.info(f"Пользователь {data['user_id']} сохранил путевой лист #{waybill_id}")
    else:
        await message.answer(
            "❌ Ошибка сохранения данных. Попробуйте еще раз.",
            reply_markup=get_main_keyboard()
        )
        logger.error(f"Ошибка сохранения путевого листа пользователем {data['user_id']}")
    
    await state.clear()

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК БОТА
# ════════════════════════════════════════════════════════════════════════════

async def main():
    """Основная функция запуска бота"""
    logger.info("🚀 Бот запускается...")
    
    # Инициализация базы данных
    init_database()
    
    # Удаление вебхука (если есть)
    await bot.delete_webhook(drop_pending_updates=True)
    
    # Запуск поллинга
    logger.info("✅ Бот запущен и готов к работе!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("🛑 Бот остановлен пользователем")
    except Exception as e:
        logger.error(f"💥 Критическая ошибка: {e}")
