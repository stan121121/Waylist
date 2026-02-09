import asyncio
import logging
import os
import sqlite3
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import (
    Message, ReplyKeyboardMarkup, KeyboardButton,
    ReplyKeyboardRemove, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
)
from aiogram.filters import Command, CommandStart, CommandObject
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
# 💾 БАЗА ДАННЫХ С VOLUME ПОДДЕРЖКОЙ
# ════════════════════════════════════════════════════════════════════════════

def get_db_path() -> str:
    """Определяет путь к базе данных с учетом Volume"""
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
    """Создание подключения к SQLite"""
    db_path = get_db_path()
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    # Включаем foreign keys и оптимизируем
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn

def init_database():
    """Инициализация базы данных"""
    try:
        db_path = get_db_path()
        logger.info(f"🔄 Инициализация БД: {db_path}")
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Таблица автомобилей
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS vehicles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                number TEXT UNIQUE NOT NULL,
                fuel_rate REAL NOT NULL CHECK(fuel_rate > 0 AND fuel_rate <= 5),
                idle_rate REAL DEFAULT 2.0 CHECK(idle_rate > 0 AND idle_rate <= 10),
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
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
        
        # Триггер для обновления updated_at
        cursor.execute('''
            CREATE TRIGGER IF NOT EXISTS update_vehicles_timestamp 
            AFTER UPDATE ON vehicles 
            BEGIN
                UPDATE vehicles SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
            END
        ''')
        
        # Оптимизированные индексы
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_vehicles_number 
            ON vehicles(number)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_waybills_vehicle_user_date 
            ON waybills(vehicle_id, user_id, date DESC)
        ''')
        cursor.execute('''
            CREATE INDEX IF NOT EXISTS idx_waybills_date 
            ON waybills(date DESC)
        ''')
        
        conn.commit()
        conn.close()
        logger.info("✅ База данных инициализирована")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации БД: {e}")

# ════════════════════════════════════════════════════════════════════════════
# 📊 КЛАСС ДЛЯ РАБОТЫ С БАЗОЙ ДАННЫХ (ОПТИМИЗИРОВАННЫЙ)
# ════════════════════════════════════════════════════════════════════════════

class Database:
    # Кэш для часто запрашиваемых данных
    _vehicles_cache = {}
    _cache_timeout = 300  # 5 минут
    
    @staticmethod
    def _clear_cache():
        """Очистка кэша"""
        current_time = datetime.now().timestamp()
        for key in list(Database._vehicles_cache.keys()):
            if current_time - Database._vehicles_cache[key]['timestamp'] > Database._cache_timeout:
                del Database._vehicles_cache[key]
    
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
            
            # Очищаем кэш
            Database._vehicles_cache.clear()
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
        """Получение списка автомобилей с кэшированием"""
        cache_key = 'all_vehicles'
        
        # Проверяем кэш если не требуется обновление
        if not force_refresh and cache_key in Database._vehicles_cache:
            cache_data = Database._vehicles_cache[cache_key]
            if datetime.now().timestamp() - cache_data['timestamp'] < Database._cache_timeout:
                return cache_data['data']
        
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
            
            # Сохраняем в кэш
            Database._vehicles_cache[cache_key] = {
                'data': vehicles,
                'timestamp': datetime.now().timestamp()
            }
            
            return vehicles
        except Exception as e:
            logger.error(f"❌ Ошибка получения списка автомобилей: {e}")
            return []
    
    @staticmethod
    def get_vehicle(vehicle_id: int) -> Optional[Dict]:
        """Получение информации об автомобиле по ID"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate,
                       strftime('%Y-%m-%d %H:%M', created_at) as created_at,
                       strftime('%Y-%m-%d %H:%M', updated_at) as updated_at
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
                    'created_at': row['created_at'],
                    'updated_at': row['updated_at']
                }
            return None
        except Exception as e:
            logger.error(f"❌ Ошибка получения автомобиля: {e}")
            return None
    
    @staticmethod
    def search_vehicles(search_term: str) -> List[Dict]:
        """Поиск автомобилей по номеру"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT id, number, fuel_rate, idle_rate
                FROM vehicles 
                WHERE number LIKE ? 
                OR number LIKE ?
                ORDER BY number COLLATE NOCASE
            """, (f'%{search_term.upper()}%', f'%{search_term}%'))
            
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
        """Удаление автомобиля"""
        try:
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Получаем информацию перед удалением
            cursor.execute("SELECT number FROM vehicles WHERE id = ?", (vehicle_id,))
            vehicle = cursor.fetchone()
            
            if not vehicle:
                conn.close()
                return False
            
            # Удаляем автомобиль (путевые листы удалятся каскадно)
            cursor.execute("DELETE FROM vehicles WHERE id = ?", (vehicle_id,))
            conn.commit()
            conn.close()
            
            # Очищаем кэш
            Database._vehicles_cache.clear()
            logger.info(f"🗑️ Удален автомобиль {vehicle['number']}")
            return True
        except Exception as e:
            logger.error(f"❌ Ошибка удаления автомобиля: {e}")
            return False
    
    @staticmethod
    def get_last_waybill(vehicle_id: int, user_id: int) -> Optional[Dict]:
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
    def get_statistics(vehicle_id: int, user_id: int, days: int = 7) -> Optional[Dict]:
        """Получение статистики"""
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
            
            # Информация о последних действиях
            cursor.execute("SELECT MAX(created_at) as last_activity FROM waybills")
            last_activity = cursor.fetchone()[0]
            
            conn.close()
            
            return {
                'path': db_path,
                'exists': exists,
                'size': size,
                'vehicles_count': vehicles_count,
                'waybills_count': waybills_count,
                'last_activity': last_activity
            }
        except Exception as e:
            logger.error(f"❌ Ошибка получения информации о БД: {e}")
            return {}

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM (ОПТИМИЗИРОВАННЫЕ)
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
    fuel_end_choice = State()
    fuel_refuel = State()
    fuel_end_manual = State()

# ════════════════════════════════════════════════════════════════════════════
# ⌨️ КЛАВИАТУРЫ (ОПТИМИЗИРОВАННЫЕ)
# ════════════════════════════════════════════════════════════════════════════

def get_main_keyboard() -> ReplyKeyboardMarkup:
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

def get_vehicles_keyboard() -> ReplyKeyboardMarkup:
    """Меню автомобилей"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📋 Список автомобилей")],
            [KeyboardButton(text="🔍 Поиск автомобиля")],
            [KeyboardButton(text="🚗 Добавить автомобиль")],
            [KeyboardButton(text="🗑️ Удалить автомобиль")],
            [KeyboardButton(text="⬅️ Назад")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие..."
    )

def get_back_keyboard() -> ReplyKeyboardMarkup:
    """Клавиатура с кнопкой Назад"""
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="⬅️ Назад")]],
        resize_keyboard=True
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

def get_vehicles_list_keyboard(vehicles: List[Dict], with_cancel: bool = True) -> ReplyKeyboardMarkup:
    """Клавиатура списка автомобилей"""
    buttons = []
    for vehicle in vehicles:
        buttons.append([KeyboardButton(text=f"🚙 {vehicle['number']}")])
    
    if with_can
