# ════════════════════════════════════════════════════════════════════════════
# 🚗 ОБРАБОТЧИКИ СОСТОЯНИЙ С ОТМЕНОЙ
# ════════════════════════════════════════════════════════════════════════════

# Обработчик отмены для всех состояний FSM
@router.message(F.text.in_(["❌ Отмена", "/cancel"]))
async def cancel_in_state(message: Message, state: FSMContext):
    """Отмена в любом состоянии FSM"""
    current_state = await state.get_state()
    
    if current_state is not None:
        await state.clear()
        logger.info(f"❌ Пользователь {message.from_user.id} отменил действие в состоянии {current_state}")
        
        # Определяем, в каком меню был пользователь
        if "AddVehicleStates" in current_state or "SearchVehicleStates" in current_state or "DeleteVehicleStates" in current_state:
            await message.answer(
                "✅ Действие отменено",
                reply_markup=get_vehicles_keyboard()
            )
        elif "WaybillStates" in current_state:
            await message.answer(
                "✅ Создание путевого листа отменено",
                reply_markup=get_main_keyboard()
            )
        else:
            await message.answer(
                "✅ Действие отменено",
                reply_markup=get_main_keyboard()
            )
    else:
        await message.answer(
            "✅ Действие отменено",
            reply_markup=get_main_keyboard()
        )

# ════════════════════════════════════════════════════════════════════════════
# 📝 ОБРАБОТЧИКИ ПУТЕВОГО ЛИСТА (ПРОДОЛЖЕНИЕ)
# ════════════════════════════════════════════════════════════════════════════

# Добавьте эти обработчики для состояний путевого листа:

@router.message(WaybillStates.vehicle_selected)
async def waybill_vehicle_selected_wrong(message: Message, state: FSMContext):
    """Обработка неправильного ввода при выборе автомобиля"""
    await message.answer(
        "❌ Пожалуйста, выберите автомобиль из списка выше или нажмите ❌ Отмена",
        reply_markup=get_vehicles_list_keyboard((await state.get_data()).get('vehicles', []))
    )

@router.message(WaybillStates.initial_data_choice)
async def waybill_initial_data_wrong(message: Message, state: FSMContext):
    """Обработка неправильного ввода при выборе начальных данных"""
    await message.answer(
        "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
        reply_markup=get_initial_data_keyboard()
    )

@router.message(WaybillStates.start_time)
async def waybill_start_time_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата времени"""
    await message.answer(
        "❌ Неверный формат времени. Введите время в формате ЧЧ:ММ (например, 08:30) или нажмите ❌ Отмена",
        reply_markup=get_cancel_keyboard()
    )

@router.message(WaybillStates.odo_start)
async def waybill_odo_start_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата одометра"""
    await message.answer(
        "❌ Неверный формат числа. Введите показания одометра (например, 123456) или нажмите ❌ Отмена",
        reply_markup=get_cancel_keyboard()
    )

@router.message(WaybillStates.fuel_start)
async def waybill_fuel_start_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата топлива"""
    await message.answer(
        "❌ Неверный формат числа. Введите количество топлива (например, 45.5) или нажмите ❌ Отмена",
        reply_markup=get_cancel_keyboard()
    )

@router.message(WaybillStates.end_time)
async def waybill_end_time_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата времени возвращения"""
    await message.answer(
        "❌ Неверный формат времени. Введите время в формате ЧЧ:ММ (например, 17:45) или нажмите ❌ Отмена",
        reply_markup=get_cancel_keyboard()
    )

@router.message(WaybillStates.odo_end)
async def waybill_odo_end_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата одометра"""
    await message.answer(
        "❌ Неверный формат числа. Введите показания одометра (например, 123500) или нажмите ❌ Отмена",
        reply_markup=get_cancel_keyboard()
    )

@router.message(WaybillStates.overuse_choice)
async def waybill_overuse_choice_wrong(message: Message, state: FSMContext):
    """Обработка неправильного выбора перерасхода"""
    await message.answer(
        "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
        reply_markup=get_overuse_choice_keyboard()
    )

@router.message(WaybillStates.overuse_hours)
async def waybill_overuse_hours_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата часов простоя"""
    if message.text == "⏭ Пропустить":
        await state.update_data(overuse_hours=0)
        await message.answer(
            "✅ Перерасход по простому не учитывается\n\n"
            "📊 Теперь введите экономию топлива (л):\n"
            "<i>Если экономии нет, введите 0</i>",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.economy)
    elif not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество часов простоя (например, 2.5) или нажмите ⏭ Пропустить",
            reply_markup=get_skip_keyboard()
        )
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
        
        await message.answer(
            f"✅ Перерасход по простому: {overuse_hours} ч × {idle_rate} л/ч = <b>{overuse:.2f} л</b>\n\n"
            "📊 Теперь введите экономию топлива (л):\n"
            "<i>Если экономии нет, введите 0</i>",
            reply_markup=get_skip_keyboard()
        )
        await state.set_state(WaybillStates.economy)

@router.message(WaybillStates.economy)
async def waybill_economy_wrong(message: Message, state: FSMContext):
    """Обработка неправильного формата экономии"""
    if message.text == "⏭ Пропустить":
        await state.update_data(economy=0)
        
        data = await state.get_data()
        await message.answer(
            f"🚗 <b>Автомобиль:</b> {data.get('vehicle_number')}\n\n"
            "⛽ <b>Как ввести остаток топлива на конец дня?</b>",
            reply_markup=get_fuel_end_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_choice)
    elif not validate_number(message.text):
        await message.answer(
            "❌ Неверный формат числа. Введите количество экономии топлива (например, 2.5) или нажмите ⏭ Пропустить",
            reply_markup=get_skip_keyboard()
        )
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
            "⛽ <b>Как ввести остаток топлива на конец дня?</b>",
            reply_markup=get_fuel_end_keyboard()
        )
        await state.set_state(WaybillStates.fuel_end_choice)

@router.message(WaybillStates.fuel_end_choice)
async def waybill_fuel_end_choice_wrong(message: Message, state: FSMContext):
    """Обработка неправильного выбора способа ввода остатка топлива"""
    await message.answer(
        "❌ Пожалуйста, выберите один из вариантов выше или нажмите ❌ Отмена",
        reply_markup=get_fuel_end_keyboard()
    )

# ════════════════════════════════════════════════════════════════════════════
# 📊 ОБРАБОТКА НЕИЗВЕСТНЫХ КОМАНД
# ════════════════════════════════════════════════════════════════════════════

@router.message()
async def unknown_command(message: Message):
    """Обработка неизвестных команд"""
    logger.info(f"❓ Неизвестная команда от {message.from_user.id}: {message.text}")
    
    # Проверяем, не является ли это числом (возможно, пользователь пытается ввести данные)
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
