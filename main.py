import asyncio
import sqlite3
import os
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.filters import Command

# ════════════════════════════════════════════════════════════════════════════
# ⚙️  НАСТРОЙКА ТОКЕНА - ВЫБЕРИТЕ ОДИН ИЗ СПОСОБОВ:
# ════════════════════════════════════════════════════════════════════════════

# СПОСОБ 1: Вставьте токен прямо здесь (замените текст между кавычками)
API_TOKEN = "YOUR_BOT_TOKEN"

# СПОСОБ 2: Используйте переменную окружения (закомментируйте строку выше)
# API_TOKEN = os.getenv("BOT_TOKEN")

# ════════════════════════════════════════════════════════════════════════════

# Проверка токена
if not API_TOKEN or API_TOKEN == "YOUR_BOT_TOKEN":
    print("\n" + "="*70)
    print("❌ ОШИБКА: Токен бота не установлен!")
    print("="*70)
    print("\n📝 Инструкция:")
    print("\n1. Получите токен от @BotFather в Telegram:")
    print("   - Найдите @BotFather")
    print("   - Отправьте /newbot")
    print("   - Следуйте инструкциям")
    print("   - Скопируйте токен")
    print("\n2. Откройте этот файл (main.py) в блокноте")
    print("\n3. Найдите строку 16 и замените:")
    print('   API_TOKEN = "YOUR_BOT_TOKEN"')
    print("   на:")
    print('   API_TOKEN = "вставьте_сюда_ваш_токен"')
    print("\n4. Сохраните файл и запустите снова")
    print("\n" + "="*70 + "\n")
    input("Нажмите Enter для выхода...")
    exit(1)

bot = Bot(API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ════════════════════════════════════════════════════════════════════════════
# 💾 БАЗА ДАННЫХ
# ════════════════════════════════════════════════════════════════════════════

def init_db():
    """Инициализация базы данных"""
    conn = sqlite3.connect('waybills.db')
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS vehicles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        number TEXT UNIQUE NOT NULL,
        fuel_rate REAL NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )''')
    
    c.execute('''CREATE TABLE IF NOT EXISTS waybills (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        vehicle_id INTEGER,
        date DATE NOT NULL,
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
    )''')
    
    conn.commit()
    conn.close()

class Database:
    @staticmethod
    def add_vehicle(number: str, fuel_rate: float):
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        try:
            c.execute("INSERT INTO vehicles (number, fuel_rate) VALUES (?, ?)", (number, fuel_rate))
            conn.commit()
            vehicle_id = c.lastrowid
            conn.close()
            return vehicle_id
        except sqlite3.IntegrityError:
            conn.close()
            return None
    
    @staticmethod
    def get_vehicles():
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        c.execute("SELECT id, number, fuel_rate FROM vehicles ORDER BY number")
        vehicles = c.fetchall()
        conn.close()
        return vehicles
    
    @staticmethod
    def get_vehicle(vehicle_id: int):
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        c.execute("SELECT id, number, fuel_rate FROM vehicles WHERE id = ?", (vehicle_id,))
        vehicle = c.fetchone()
        conn.close()
        return vehicle
    
    @staticmethod
    def get_last_waybill(vehicle_id: int):
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        c.execute("""
            SELECT odo_end, fuel_end, date 
            FROM waybills 
            WHERE vehicle_id = ? 
            ORDER BY date DESC, id DESC 
            LIMIT 1
        """, (vehicle_id,))
        waybill = c.fetchone()
        conn.close()
        return waybill
    
    @staticmethod
    def save_waybill(data: dict):
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        c.execute("""
            INSERT INTO waybills 
            (vehicle_id, date, start_time, end_time, total_hours, 
             odo_start, odo_end, distance, fuel_start, fuel_end, 
             fuel_norm, fuel_actual, overuse, economy, fuel_rate)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            data.get('vehicle_id'),
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
        waybill_id = c.lastrowid
        conn.close()
        return waybill_id
    
    @staticmethod
    def get_statistics(vehicle_id: int, days: int = 7):
        conn = sqlite3.connect('waybills.db')
        c = conn.cursor()
        c.execute("""
            SELECT 
                COUNT(*) as trips,
                SUM(distance) as total_distance,
                SUM(fuel_actual) as total_fuel,
                AVG(fuel_actual/distance*100) as avg_consumption
            FROM waybills 
            WHERE vehicle_id = ? 
            AND date >= date('now', '-' || ? || ' days')
        """, (vehicle_id, days))
        stats = c.fetchone()
        conn.close()
        return stats

init_db()

# ════════════════════════════════════════════════════════════════════════════
# 📝 СОСТОЯНИЯ FSM
# ════════════════════════════════════════════════════════════════════════════

class AddVehicle(StatesGroup):
    number = State()
    fuel_rate = State()

class SelectVehicle(StatesGroup):
    choosing = State()

class Waybill(StatesGroup):
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

def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Новый путевой лист")],
            [KeyboardButton(text="🚗 Добавить автомобиль")],
            [KeyboardButton(text="📊 Мои автомобили")],
            [KeyboardButton(text="📈 Статистика")]
        ],
        resize_keyboard=True
    )

def get_skip_kb():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="0")],
            [KeyboardButton(text="⏭ Пропустить")]
        ],
        resize_keyboard=True
    )

def get_vehicles_kb(vehicles):
    buttons = []
    for v in vehicles:
        buttons.append([KeyboardButton(text=f"🚙 {v[1]} ({v[2]} л/км)")])
    buttons.append([KeyboardButton(text="❌ Отмена")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)

def get_confirm_kb(odo_value, fuel_value):
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

def calc_hours(start, end):
    try:
        fmt = "%H:%M"
        s = datetime.strptime(start, fmt)
        e = datetime.strptime(end, fmt)
        diff = (e - s).total_seconds() / 3600
        if diff < 0:
            diff += 24
        return round(diff, 2)
    except:
        return 0

def validate_time(time_str):
    try:
        datetime.strptime(time_str, "%H:%M")
        return True
    except:
        return False

# ════════════════════════════════════════════════════════════════════════════
# 📱 ОБРАБОТЧИКИ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "🚛 *Система учета путевых листов*\n\n"
        "Бот помогает вести учет путевых листов, "
        "контролировать расход топлива и пробег.\n\n"
        "Выберите действие:",
        reply_markup=get_main_menu(),
        parse_mode="Markdown"
    )

# ════════════════════════════════════════════════════════════════════════════
# 🚗 ДОБАВЛЕНИЕ АВТОМОБИЛЯ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "🚗 Добавить автомобиль")
async def add_vehicle_start(message: Message, state: FSMContext):
    await message.answer(
        "🚗 Введите государственный номер автомобиля:",
        reply_markup=ReplyKeyboardRemove()
    )
    await state.set_state(AddVehicle.number)

@dp.message(AddVehicle.number)
async def add_vehicle_number(message: Message, state: FSMContext):
    await state.update_data(number=message.text.strip().upper())
    await message.answer("⛽ Введите норму расхода топлива (л/км):\nНапример: 0.12")
    await state.set_state(AddVehicle.fuel_rate)

@dp.message(AddVehicle.fuel_rate)
async def add_vehicle_fuel_rate(message: Message, state: FSMContext):
    try:
        fuel_rate = float(message.text.strip())
        data = await state.get_data()
        
        vehicle_id = Database.add_vehicle(data['number'], fuel_rate)
        
        if vehicle_id:
            await message.answer(
                f"✅ Автомобиль *{data['number']}* добавлен!\n"
                f"⛽ Норма расхода: {fuel_rate} л/км",
                reply_markup=get_main_menu(),
                parse_mode="Markdown"
            )
        else:
            await message.answer(
                f"❌ Автомобиль {data['number']} уже существует!",
                reply_markup=get_main_menu()
            )
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число (например: 0.12)")

# ════════════════════════════════════════════════════════════════════════════
# 📊 СПИСОК АВТОМОБИЛЕЙ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "📊 Мои автомобили")
async def list_vehicles(message: Message):
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ У вас нет зарегистрированных автомобилей.\n"
            "Добавьте первый автомобиль!",
            reply_markup=get_main_menu()
        )
        return
    
    text = "🚗 *СПИСОК АВТОМОБИЛЕЙ*\n" + "━" * 30 + "\n\n"
    for v in vehicles:
        text += f"🚙 *{v[1]}*\n⛽ Расход: {v[2]} л/км\n\n"
    
    await message.answer(text, parse_mode="Markdown")

# ════════════════════════════════════════════════════════════════════════════
# 📈 СТАТИСТИКА
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "📈 Статистика")
async def show_statistics(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ Нет автомобилей для статистики",
            reply_markup=get_main_menu()
        )
        return
    
    await message.answer(
        "Выберите автомобиль:",
        reply_markup=get_vehicles_kb(vehicles)
    )
    await state.set_state(SelectVehicle.choosing)
    await state.update_data(action='stats')

# ════════════════════════════════════════════════════════════════════════════
# 📝 НОВЫЙ ПУТЕВОЙ ЛИСТ
# ════════════════════════════════════════════════════════════════════════════

@dp.message(F.text == "📝 Новый путевой лист")
async def new_waybill(message: Message, state: FSMContext):
    vehicles = Database.get_vehicles()
    
    if not vehicles:
        await message.answer(
            "❌ Сначала добавьте автомобиль!",
            reply_markup=get_main_menu()
        )
        return
    
    await message.answer(
        "🚗 Выберите автомобиль:",
        reply_markup=get_vehicles_kb(vehicles)
    )
    await state.set_state(SelectVehicle.choosing)
    await state.update_data(action='waybill')

@dp.message(SelectVehicle.choosing)
async def vehicle_selected(message: Message, state: FSMContext):
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено", reply_markup=get_main_menu())
        return
    
    data = await state.get_data()
    action = data.get('action')
    
    try:
        vehicle_number = message.text.split("🚙 ")[1].split(" (")[0]
    except:
        await message.answer("❌ Ошибка выбора. Попробуйте снова.")
        return
    
    vehicles = Database.get_vehicles()
    vehicle = next((v for v in vehicles if v[1] == vehicle_number), None)
    
    if not vehicle:
        await message.answer("❌ Автомобиль не найден")
        return
    
    if action == 'stats':
        stats = Database.get_statistics(vehicle[0], 7)
        
        if stats[0] == 0:
            await message.answer(
                f"📊 Статистика: *{vehicle[1]}*\n\n"
                f"Нет данных за последние 7 дней",
                reply_markup=get_main_menu(),
                parse_mode="Markdown"
            )
        else:
            avg_consumption = stats[3] if stats[3] else 0
            await message.answer(
                f"📊 *Статистика: {vehicle[1]}*\n"
                f"━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"📅 За последние 7 дней:\n"
                f"🚗 Поездок: {stats[0]}\n"
                f"📏 Пробег: {stats[1]:.0f} км\n"
                f"⛽ Топлива: {stats[2]:.2f} л\n"
                f"📊 Средний расход: {avg_consumption:.2f} л/100км",
                reply_markup=get_main_menu(),
                parse_mode="Markdown"
            )
        await state.clear()
    else:
        await state.update_data(
            vehicle_id=vehicle[0],
            vehicle_number=vehicle[1],
            fuel_rate=vehicle[2]
        )
        
        last = Database.get_last_waybill(vehicle[0])
        
        if last:
            await state.update_data(
                suggested_odo=last[0],
                suggested_fuel=last[1]
            )
            await message.answer(
                f"🚗 Автомобиль: *{vehicle[1]}*\n\n"
                f"📅 Последний путевой лист: {last[2]}\n"
                f"🛣 Одометр: {last[0]:.0f} км\n"
                f"⛽ Остаток топлива: {last[1]:.2f} л\n\n"
                f"Использовать эти значения?",
                reply_markup=get_confirm_kb(last[0], last[1]),
                parse_mode="Markdown"
            )
            await state.set_state(Waybill.vehicle_selected)
        else:
            await message.answer(
                f"🚗 Автомобиль: *{vehicle[1]}*\n\n"
                f"🕒 Введите время выпуска на линию (ЧЧ:ММ):",
                reply_markup=ReplyKeyboardRemove(),
                parse_mode="Markdown"
            )
            await state.set_state(Waybill.start_time)

@dp.message(Waybill.vehicle_selected)
async def handle_previous_data(message: Message, state: FSMContext):
    data = await state.get_data()
    
    if message.text.startswith("✅ Одометр"):
        await state.update_data(odo_start=data['suggested_odo'])
        await message.answer(
            f"✅ Одометр: {data['suggested_odo']:.0f} км\n\n"
            f"⛽ Остаток топлива при выезде:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Waybill.fuel_start)
    elif message.text.startswith("✅ Топливо"):
        await state.update_data(fuel_start=data['suggested_fuel'])
        await message.answer(
            f"✅ Топливо: {data['suggested_fuel']:.2f} л\n\n"
            f"🛣 Показания одометра на начало дня:",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Waybill.odo_start)
    else:
        await message.answer(
            "🕒 Введите время выпуска на линию (ЧЧ:ММ):",
            reply_markup=ReplyKeyboardRemove()
        )
        await state.set_state(Waybill.start_time)

@dp.message(Waybill.start_time)
async def start_time(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: 08:30)")
        return
    
    await state.update_data(start_time=message.text)
    data = await state.get_data()
    
    if 'odo_start' in data:
        await message.answer("⛽ Остаток топлива при выезде:")
        await state.set_state(Waybill.fuel_start)
    else:
        await message.answer("🚗 Показания одометра на начало дня:")
        await state.set_state(Waybill.odo_start)

@dp.message(Waybill.odo_start)
async def odo_start(message: Message, state: FSMContext):
    try:
        odo = float(message.text)
        await state.update_data(odo_start=odo)
        
        data = await state.get_data()
        if 'fuel_start' in data:
            await message.answer("🕓 Время возвращения с линии (ЧЧ:ММ):")
            await state.set_state(Waybill.end_time)
        else:
            await message.answer("⛽ Остаток топлива при выезде:")
            await state.set_state(Waybill.fuel_start)
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(Waybill.fuel_start)
async def fuel_start(message: Message, state: FSMContext):
    try:
        fuel = float(message.text)
        await state.update_data(fuel_start=fuel)
        
        data = await state.get_data()
        if 'start_time' not in data:
            await message.answer("🕒 Время выпуска на линию (ЧЧ:ММ):")
            await state.set_state(Waybill.start_time)
        else:
            await message.answer("🕓 Время возвращения с линии (ЧЧ:ММ):")
            await state.set_state(Waybill.end_time)
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(Waybill.end_time)
async def end_time(message: Message, state: FSMContext):
    if not validate_time(message.text):
        await message.answer("❌ Неверный формат! Введите время в формате ЧЧ:ММ (например: 17:30)")
        return
    
    data = await state.get_data()
    hours = calc_hours(data["start_time"], message.text)
    await state.update_data(end_time=message.text, hours=hours)

    await message.answer(
        f"⏱ Всего в наряде: *{hours} ч*\n\n"
        "🚗 Показания одометра на конец дня:",
        parse_mode="Markdown"
    )
    await state.set_state(Waybill.odo_end)

@dp.message(Waybill.odo_end)
async def odo_end(message: Message, state: FSMContext):
    try:
        data = await state.get_data()
        odo_end = float(message.text)
        distance = odo_end - data["odo_start"]

        if distance < 0:
            await message.answer("❌ Показания одометра не могут быть меньше начальных!")
            return

        await state.update_data(odo_end=odo_end, distance=distance)
        await message.answer(
            f"📏 Пробег за день: *{distance:.0f} км*\n\n"
            "⚠️ Перерасход топлива (л) или пропустить:",
            reply_markup=get_skip_kb(),
            parse_mode="Markdown"
        )
        await state.set_state(Waybill.overuse)
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(Waybill.overuse)
async def overuse(message: Message, state: FSMContext):
    try:
        value = 0 if message.text in ["⏭ Пропустить", "0"] else float(message.text)
        await state.update_data(overuse=value)

        await message.answer(
            "💚 Экономия топлива (л) или пропустить:",
            reply_markup=get_skip_kb()
        )
        await state.set_state(Waybill.economy)
    except ValueError:
        await message.answer("❌ Введите корректное число!")

@dp.message(Waybill.economy)
async def economy(message: Message, state: FSMContext):
    try:
        value = 0 if message.text in ["⏭ Пропустить", "0"] else float(message.text)
        await state.update_data(economy=value)

        data = await state.get_data()
        
        fuel_norm = data["distance"] * data["fuel_rate"]
        fuel_actual = fuel_norm - data["economy"] + data["overuse"]
        fuel_end = data["fuel_start"] - fuel_actual

        waybill_data = {
            'vehicle_id': data['vehicle_id'],
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
        
        Database.save_waybill(waybill_data)

        report = (
            "📄 *ПУТЕВОЙ ЛИСТ ЗАВЕРШЕН*\n"
            "━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🚗 Автомобиль: *{data['vehicle_number']}*\n"
            f"📅 Дата: {datetime.now().strftime('%d.%m.%Y')}\n\n"
            f"🕒 Выпуск: {data['start_time']}\n"
            f"🕓 Возвращение: {data['end_time']}\n"
            f"⏱ Всего в наряде: *{data['hours']} ч*\n\n"
            f"🛣 Одометр начало: {data['odo_start']:.0f} км\n"
            f"🛣 Одометр конец: {data['odo_end']:.0f} км\n"
            f"📏 Пробег: *{data['distance']:.0f} км*\n\n"
            f"⛽ Топливо при выезде: {data['fuel_start']:.2f} л\n"
            f"📊 Расход по норме: {fuel_norm:.2f} л\n"
            f"⚠️ Перерасход: {data['overuse']:.2f} л\n"
            f"💚 Экономия: {data['economy']:.2f} л\n"
            f"⛽ Фактический расход: *{fuel_actual:.2f} л*\n"
            f"🧮 Остаток топлива: *{fuel_end:.2f} л*"
        )

        await message.answer(
            report,
            reply_markup=get_main_menu(),
            parse_mode="Markdown"
        )
        
        await state.clear()
    except ValueError:
        await message.answer("❌ Введите корректное число!")

# ════════════════════════════════════════════════════════════════════════════
# 🚀 ЗАПУСК БОТА
# ════════════════════════════════════════════════════════════════════════════

async def main():
    print("\n" + "="*70)
    print("🚀 БОТ УСПЕШНО ЗАПУЩЕН!")
    print("="*70)
    try:
        me = await bot.get_me()
        print(f"✅ Подключение к Telegram успешно!")
        print(f"📱 Имя бота: {me.first_name}")
        print(f"🔗 Username: @{me.username}")
        print(f"🆔 ID: {me.id}")
    except Exception as e:
        print(f"❌ Ошибка подключения: {e}")
        print("\nПроверьте:")
        print("1. Правильность токена")
        print("2. Подключение к интернету")
        input("\nНажмите Enter для выхода...")
        return
    
    print(f"📅 Дата: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print(f"💾 База данных: waybills.db")
    print("="*70)
    print("🔄 Бот ожидает сообщений...")
    print("💡 Напишите боту /start в Telegram")
    print("="*70 + "\n")
    
    await dp.start_polling(bot)

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n✋ Бот остановлен пользователем")
    except Exception as e:
        print(f"\n\n❌ Критическая ошибка: {e}")
        input("\nНажмите Enter для выхода...")
