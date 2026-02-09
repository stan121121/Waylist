@router.message(WaybillStates.overuse_hours)
async def waybill_overuse_hours(message: Message, state: FSMContext):
    """Обработка часов простоя"""
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
        
        await state.update_data(
            overuse_hours=overuse_hours,
            overuse_calculated=1,
            overuse=overuse
        )
    
    data = await state.get_data()
    overuse = data.get('overuse', 0)
    
    await message.answer(
        f"✅ Перерасход по простому: {overuse:.2f} л\n\n"
        "📊 Теперь введите экономию топлива (л):\n"
        "<i>Если экономии нет, введите 0</i>",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.overuse_manual)
async def waybill_overuse_manual(message: Message, state: FSMContext):
    """Обработка ручного ввода перерасхода"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество перерасхода (например, 2.5) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    overuse = float(message.text)
    if overuse < 0:
        await message.answer("❌ Перерасход не может быть отрицательным")
        return
    
    await state.update_data(
        overuse=overuse,
        overuse_hours=0,
        overuse_calculated=0
    )
    
    await message.answer(
        f"✅ Перерасход учтен: {overuse:.2f} л\n\n"
        "📊 Теперь введите экономию топлива (л):\n"
        "<i>Если экономии нет, введите 0</i>",
        reply_markup=get_skip_keyboard()
    )
    await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def waybill_economy(message: Message, state: FSMContext):
    """Обработка экономии топлива"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    
    if message.text == "⏭ Пропустить":
        economy = 0
    elif not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество экономии (например, 2.5) или нажмите ⏭ Пропустить",
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
    await message.answer(
        f"🚗 <b>Автомобиль:</b> {data.get('vehicle_number')}\n\n"
        "⛽ <b>Как ввести остаток топлива на конец дня?</b>\n"
        "• 📊 Рассчитать автоматически - из начального топлива вычесть расход\n"
        "• ✏️ Ввести остаток вручную\n"
        "• ⛽ Добавить заправку",
        reply_markup=get_fuel_end_keyboard()
    )
    await state.set_state(WaybillStates.fuel_end_choice)

@router.message(WaybillStates.fuel_end_choice)
async def waybill_fuel_end_choice(message: Message, state: FSMContext):
    """Обработка выбора способа ввода остатка топлива"""
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
        
        # Расчет фактического расхода
        fuel_actual = fuel_norm + overuse - economy
        
        # Расчет остатка
        fuel_end = fuel_start - fuel_actual
        
        await state.update_data(
            fuel_actual=fuel_actual,
            fuel_end=fuel_end,
            fuel_end_manual=0
        )
        
        await save_and_show_waybill(message, state)
        
    elif message.text == "✏️ Ввести остаток вручную":
        await message.answer(
            "⛽ Введите остаток топлива на конец дня (л):",
            reply_markup=get_cancel_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_manual)
        
    elif message.text == "⛽ Добавить заправку":
        await message.answer(
            "⛽ Введите количество заправленного топлива (л):",
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
    """Обработка заправки топлива"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество топлива (например, 20.0) или нажмите ❌ Отмена",
            reply_markup=get_cancel_keyboard()
        )
        return
    
    fuel_refuel = float(message.text)
    if fuel_refuel < 0:
        await message.answer("❌ Количество топлива не может быть отрицательным")
        return
    
    await state.update_data(fuel_refuel=fuel_refuel)
    
    await message.answer(
        "⛽ Введите остаток топлива на конец дня (л):",
        reply_markup=get_cancel_keyboard()
    )
    await state.set_state(WaybillStates.fuel_end_manual)

@router.message(WaybillStates.fuel_end_manual)
async def waybill_fuel_end_manual(message: Message, state: FSMContext):
    """Обработка ручного ввода остатка топлива"""
    if message.text == "❌ Отмена":
        await state.clear()
        await message.answer("✅ Действие отменено", reply_markup=get_main_keyboard())
        return
    
    if not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество топлива (например, 15.5) или нажмите ❌ Отмена",
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
    fuel_norm = data.get('fuel_norm', 0)
    overuse = data.get('overuse', 0)
    economy = data.get('economy', 0)
    
    # Расчет фактического расхода с учетом заправки
    fuel_actual = fuel_start + fuel_refuel - fuel_end
    
    await state.update_data(
        fuel_end=fuel_end,
        fuel_actual=fuel_actual,
        fuel_end_manual=1
    )
    
    await save_and_show_waybill(message, state)

async def save_and_show_waybill(message: Message, state: FSMContext):
    """Сохранение и отображение путевого листа"""
    data = await state.get_data()
    
    # Добавляем дату
    data['date'] = datetime.now().strftime('%Y-%m-%d')
    
    # Сохраняем путевой лист
    waybill_id = Database.save_waybill(data)
    
    if waybill_id:
        # Формируем сводку
        summary = f"""
<b>✅ ПУТЕВОЙ ЛИСТ СОХРАНЕН #{waybill_id}</b>

🚙 <b>Автомобиль:</b> {data.get('vehicle_number')}
📅 <b>Дата:</b> {data.get('date')}

<b>📊 РАСЧЕТЫ:</b>
🕒 <b>Время работы:</b> {data.get('start_time', '--:--')} - {data.get('end_time', '--:--')}
⏱ <b>Всего часов:</b> {data.get('hours', 0):.2f} ч
🛣 <b>Расстояние:</b> {data.get('distance', 0):.0f} км
⛽ <b>Норма расхода:</b> {data.get('fuel_norm', 0):.2f} л
📈 <b>Перерасход:</b> {data.get('overuse', 0):.2f} л
💚 <b>Экономия:</b> {data.get('economy', 0):.2f} л
⛽ <b>Фактический расход:</b> {data.get('fuel_actual', 0):.2f} л
⛽ <b>Заправка:</b> {data.get('fuel_refuel', 0):.2f} л
⛽ <b>Остаток:</b> {data.get('fuel_end', 0):.2f} л

<b>📈 ПОКАЗАТЕЛИ:</b>
🏭 <b>Удельный расход:</b> {data.get('fuel_actual', 0) / data.get('distance', 1) * 100 if data.get('distance', 0) > 0 else 0:.2f} л/100км
💰 <b>Эффективность:</b> {"Экономия" if data.get('economy', 0) > data.get('overuse', 0) else "Перерасход"}
"""
        
        await message.answer(summary, reply_markup=get_main_keyboard())
    else:
        await message.answer(
            "❌ Ошибка сохранения путевого листа!\n"
            "Попробуйте снова.",
            reply_markup=get_main_keyboard()
        )
    
    await state.clear()
