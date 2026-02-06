import asyncio
from datetime import datetime
from aiogram import Bot, Dispatcher, F
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage

API_TOKEN = "YOUR_BOT_TOKEN"

bot = Bot(API_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------- Состояния --------
class Waybill(StatesGroup):
    start_time = State()
    odo_start = State()
    fuel_start = State()
    end_time = State()
    odo_end = State()
    overuse = State()
    economy = State()
    norm = State()

skip_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Пропустить")]],
    resize_keyboard=True
)

new_day_kb = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text="Новый день")]],
    resize_keyboard=True
)

# -------- Вспомогательные функции --------
def calc_hours(start, end):
    fmt = "%H:%M"
    s = datetime.strptime(start, fmt)
    e = datetime.strptime(end, fmt)
    return round((e - s).total_seconds() / 3600, 2)

# -------- Хендлеры --------
@dp.message(F.text == "/start")
async def start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("🕒 Время выпуска на линию (ЧЧ:ММ):")
    await state.set_state(Waybill.start_time)

@dp.message(Waybill.start_time)
async def start_time(message: Message, state: FSMContext):
    await state.update_data(start_time=message.text)
    await message.answer("🚗 Показания одометра на начало дня:")
    await state.set_state(Waybill.odo_start)

@dp.message(Waybill.odo_start)
async def odo_start(message: Message, state: FSMContext):
    await state.update_data(odo_start=float(message.text))
    await message.answer("⛽ Остаток топлива при выезде:")
    await state.set_state(Waybill.fuel_start)

@dp.message(Waybill.fuel_start)
async def fuel_start(message: Message, state: FSMContext):
    await state.update_data(fuel_start=float(message.text))
    await message.answer("🕓 Время возвращения с линии (ЧЧ:ММ):")
    await state.set_state(Waybill.end_time)

@dp.message(Waybill.end_time)
async def end_time(message: Message, state: FSMContext):
    data = await state.get_data()
    hours = calc_hours(data["start_time"], message.text)
    await state.update_data(end_time=message.text, hours=hours)

    await message.answer(
        f"⏱ Всего в наряде: {hours} ч\n\n"
        "🚗 Показания одометра на конец дня:"
    )
    await state.set_state(Waybill.odo_end)

@dp.message(Waybill.odo_end)
async def odo_end(message: Message, state: FSMContext):
    data = await state.get_data()
    odo_end = float(message.text)
    distance = odo_end - data["odo_start"]

    await state.update_data(odo_end=odo_end, distance=distance)
    await message.answer(
        f"📏 Пробег за день: {distance} км\n\n"
        "⚠️ Перерасход (л) или пропустить:",
        reply_markup=skip_kb
    )
    await state.set_state(Waybill.overuse)

@dp.message(Waybill.overuse)
async def overuse(message: Message, state: FSMContext):
    value = 0 if message.text == "Пропустить" else float(message.text)
    await state.update_data(overuse=value)

    await message.answer(
        "💚 Экономия (л) или пропустить:",
        reply_markup=skip_kb
    )
    await state.set_state(Waybill.economy)

@dp.message(Waybill.economy)
async def economy(message: Message, state: FSMContext):
    value = 0 if message.text == "Пропустить" else float(message.text)
    await state.update_data(economy=value)

    await message.answer("📊 Расход по норме (л/км):")
    await state.set_state(Waybill.norm)

@dp.message(Waybill.norm)
async def finish_day(message: Message, state: FSMContext):
    data = await state.get_data()
    norm = float(message.text)

    fuel_norm = data["distance"] * norm
    fact = fuel_norm - data["economy"] + data["overuse"]
    fuel_end = data["fuel_start"] - fact

    await message.answer(
        "📄 Итог дня:\n\n"
        f"⏱ Всего в наряде: {data['hours']} ч\n"
        f"🚗 Пробег: {data['distance']} км\n"
        f"📊 Расход по норме: {fuel_norm:.2f} л\n"
        f"⚠️ Перерасход: {data['overuse']} л\n"
        f"💚 Экономия: {data['economy']} л\n"
        f"⛽ Фактический расход: {fact:.2f} л\n"
        f"🧮 Остаток топлива: {fuel_end:.2f} л",
        reply_markup=new_day_kb
    )

    # сохраняем для следующего дня
    await state.update_data(
        odo_start=data["odo_end"],
        fuel_start=fuel_end
    )

@dp.message(F.text == "Новый день")
async def new_day(message: Message, state: FSMContext):
    await message.answer("🕒 Время выпуска на линию:")
    await state.set_state(Waybill.start_time)

# -------- Запуск --------
async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
