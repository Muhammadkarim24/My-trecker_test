from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
import json
from admin import ADMIN_ID

user_router = Router()
MENU_FILE = "menu.json"

def load_menu():
    try:
        with open (MENU_FILE, "r") as f:
            return json.load(f)
    except json.decoder.JSONDecodeError:
            return[]

class OrderState(StatesGroup):
     choosing = State()
     confirning = State()

@user_router.message(Command('start'))
async def start(message: Message):
     await  message.answer('Welcome to our restaurant_bot for show menu, tap /menu ')

@user_router.message(Command('menu'))
async def menu(message: Message, state: FSMContext):
    menu = load_menu()
    if not menu:
          await message.answer('Menu pust!')
          return

    buttons = [
         [InlineKeyboardButton(text = f"{item['name']} , {item['price']} somoni", callback_data = item['name'])]
         for item in menu

    ]

    markup = InlineKeyboardMarkup(inline_keyboard = buttons)
    await message.answer('This is our menu:' , reply_markup=markup)
    await state.set_state(OrderState.choosing)


@user_router.callback_query(OrderState.choosing)
async def choose(callback: CallbackQuery, state: FSMContext):
     await state.update_data(item = callback.data)
     await callback.message.answer(f"You chose {callback.data}! For confirning share /confirm !") 
     await state.set_state(OrderState.confirning)
     await callback.answer()    
@user_router.message(OrderState.confirning)
async def confirm(message: Message, state: FSMContext):
     data = await state.get_data()
     item = data.get('item')
     if not item:
          await message.answer('Snachala viberite iz menu!')
          return
     await message.answer(f"Vash zakaz: {item} odobren")
     await message.bot.send_message(ADMIN_ID, f"Noviy zakaz {item} ot {message.from_user.full_name} odobren!")
     await state.clear()

          
          