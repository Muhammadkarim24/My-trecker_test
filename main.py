# import asyncio
# from aiogram import Bot, Dispatcher
# from aiogram.filters import Command
# Token = ""
# bot = Bot(token= Token)
# disp = Dispatcher()

# @disp.message(Command('start'))
# async def start(message):
    
#     await message.answer("Assalomu aleikum.")

# async def main():
#         await disp.start_polling(bot)
#         print('Bot started')

# asyncio.run(main())        
import asyncio
from aiogram import Bot, Dispatcher
from aiogram.filters import Command
from aiogram.client.session.aiohttp import AiohttpSession
from admin import admin_router
from user import user_router
from api_token import Token
 # ваш токен



# @disp.message(Command('start'))
# async def start(message):
#     user = message.from_user.full_name
#     await message.answer(f"Assalomu aleikum {user}.")

# @disp.message()
# async def reply(message):
#     await message.answer("Созӣ, ҷигар!") 



async def main():
    session = AiohttpSession(proxy="socks5://127.0.0.1:10808")
    bot = Bot(token=Token, session=session)
    disp = Dispatcher()

    disp.include_router(admin_router)
    disp.include_router(user_router)

    await disp.start_polling(bot)



if __name__ == "__main__":

    print('Bot started')
    asyncio.run(main())