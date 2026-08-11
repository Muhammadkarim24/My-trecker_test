from aiogram import Router, F
from aiogram.types import Message
from aiogram.filters import Command
import json
from api_token import ADMIN_ID


admin_router = Router()

MENU_FILE  = "menu.json"

def load_menu():
    try:
        with open (MENU_FILE, "r") as f:
            return json.load(f)
    except json.decoder.JSONDecodeError:
        return[]

def save_menu(menu: list):
    with open(MENU_FILE, "w") as f:
        json.dump(menu , f, indent = 2) 


@admin_router.message(Command('dobavlenie'))
async def dobavlenie(message: Message):
    if message.from_user.id != ADMIN_ID:    
        return
    parts = message.text.split(" ", 2)
    if len(parts) < 3:
        await message.answer("Using: /dobavlenie <name> and <narkh>")
        return

    name = parts[1]
    price = parts[2]
    menu = load_menu()
    menu.append({"name": name, "price": price})
    save_menu(menu)

    await message.answer(f"Dobaleno:{name} - {price}somoni")

@admin_router.message(Command('udalenie'))
async def udalenie(message: Message):
    if message.from_user.user.id != ADMIN_ID:
        return

    name = message.text.split(" ", 1)[1]
    menu = load_menu()
    menu = [item for item in menu if item['name'] != name]
    save_menu(menu)
    await message.answer(f"Avqoti {name} udaleno!")

# @admin_router.message(Command('menu'))
# async def menu(message: Message):
#     if message.from_user.id != ADMIN_ID:
#         return
#     menu = load_menu()
#     if not menu:
#         await message.answer('Menu pust')
#         return

#     text = ''
#     for item in menu:
#         text += f"{item['imya']} - {item['price']} somoni"
#         await message.answer(text)