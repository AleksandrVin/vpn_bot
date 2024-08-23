import os
import sys
import asyncio
import logging
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import ParseMode
from aiogram.utils import executor, markdown
from sqlmodel import Field, Session, SQLModel, create_engine, select

# Get the Telegram bot token from environment variable
API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if not API_TOKEN:
    print("Please set the TELEGRAM_BOT_TOKEN environment variable")
    sys.exit(1)

# Configure logging
logging.basicConfig(level=logging.INFO)

# Initialize the bot and dispatcher
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
dp.middleware.setup(LoggingMiddleware())

# Define database models using Sqlmodel
class User(SQLModel, table=True):
    user_id: int = Field(default=None, primary_key=True)
    telegram_id: int = Field(unique=True)
    token: str = Field(default=None)

class VPNProfile(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    user_id: int = Field(foreign_key="user.user_id")
    name: str = Field(default="active")
    status: str = Field(default="active")
    creation_time: str = Field(default=None, nullable=True)

class UserToken(SQLModel, table=True):
    id: int = Field(default=None, primary_key=True)
    token: str = Field(unique=True)
    creation_time: str = Field(default=None, nullable=True)
    balance: float = Field(default=0)

# Create database engine
engine = create_engine("sqlite:///vpn_profiles.db")
SQLModel.metadata.create_all(engine)

# Define FSM states
class Form(StatesGroup):
    profile_name = State()  # State to enter profile name

async def on_start(message: types.Message):
    user_id = message.from_user.id
    async with Session(engine) as session:
        user = User(telegram_id=user_id)
        session.add(user)
        await session.commit()
    await message.reply("Welcome to the VPN Access Bot! Use /help for available commands.")

async def on_help(message: types.Message):
    help_text = (
        "/start - Initialize user in the system\n"
        "/register - Register new token\n"
        "/add - Add a new VPN profile\n"
        "/list - List all VPN profiles\n"
        "/delete - Delete a VPN profile\n"
        "/help - Show this help message\n"
        "/get - Get .conf file and QR code for WireGuard client application for existing peer\n"
        "/unregister - Unregister token\n"
        "/info - Show info about your token\n"
        "/balance - Show balance of your token\n"
        "/suspend - Suspend VPN profile\n"
        "/resume - Resume VPN profile\n"
    )
    await message.reply(help_text)

async def send_config(message: types.Message, name_for_wg, profile_name):
    file_path = os.path.expanduser(f"~/wg_config/peer_{name_for_wg}/peer_{name_for_wg}.conf")
    qr_code_path = os.path.expanduser(f"~/wg_config/peer_{name_for_wg}/peer_{name_for_wg}.png")

    await message.reply_document(open(file_path, "rb"), caption=f"{profile_name}.conf")
    await message.reply_photo(open(qr_code_path, "rb"), caption=f"{profile_name}.png")

# Command handler to initiate the process of adding a profile
async def on_add(message: types.Message):
    await message.reply("Please enter the profile name:")
    await Form.profile_name.set()

# Handler to receive the profile name
@dp.message_handler(state=Form.profile_name)
async def process_profile_name(message: types.Message, state: FSMContext):
    profile_name = message.text.strip()
    user_id = message.from_user.id

    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if not user:
            await message.reply("User not found. Please use /start to initialize.")
            await state.finish()
            return

        profile_exists = await session.exec(select(VPNProfile).where(VPNProfile.user_id == user.user_id, VPNProfile.name == profile_name))
        profile_exists = profile_exists.one_or_none()

        if profile_exists:
            await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' already exists.", parse_mode=ParseMode.MARKDOWN)
            await send_config(message, user_id + 'p' + profile_name, profile_name)
            await state.finish()
            return

        user_token = await session.exec(select(UserToken).where(UserToken.token == user.token))
        user_token = user_token.one_or_none()

        if not user_token or user_token.balance <= 0:
            await message.reply("You don't have a valid token or your balance is zero. Please register a token or top up your balance.")
            await state.finish()
            return

        new_profile = VPNProfile(user_id=user.user_id, name=profile_name)
        session.add(new_profile)
        await session.commit()

        os.system(f"docker exec -it wireguard /app/manage-peer add {user_id + 'p' + profile_name}")
        await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' added successfully. \nYour .conf file and QR code for WireGuard client application.", parse_mode=ParseMode.MARKDOWN)
        await send_config(message, user_id + 'p' + profile_name, profile_name)
        await state.finish()

async def on_list(message: types.Message):
    user_id = message.from_user.id
    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if not user:
            await message.reply("User not found. Please use /start to initialize.")
            return

        profiles = await session.exec(select(VPNProfile).where(VPNProfile.user_id == user.user_id))
        profiles = profiles.all()

        if not profiles:
            await message.reply("You have no VPN profiles.")
            return

        profile_list = "Your VPN profiles:\n"
        for profile in profiles:
            profile_list += f"- {markdown.escape_md(profile.name)} created: {profile.creation_time}\n"

        await message.reply(profile_list, parse_mode=ParseMode.MARKDOWN)

async def on_get(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[5:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to get after the /get command.")
        return

    name_for_wg = str(user_id) + 'p' + profile_name
    await send_config(message, name_for_wg, profile_name)

async def on_delete(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[8:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to delete after the /delete command.")
        return

    async with Session(engine) as session:
        profile = await session.exec(select(VPNProfile).where(VPNProfile.user_id == user_id, VPNProfile.name == profile_name))
        profile = profile.one_or_none()

        if not profile:
            await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)
            return

        session.delete(profile)
        await session.commit()

        os.system(f"docker exec -it wireguard /app/manage-peer remove {user_id + 'p' + profile_name}")
        await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' deleted successfully.", parse_mode=ParseMode.MARKDOWN)

async def on_register(message: types.Message):
    user_id = message.from_user.id
    token = message.text[10:].strip()

    if not token:
        await message.reply("Please provide the token you want to register after the /register command.")
        return

    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if user and user.token:
            await message.reply(f"You already have a token: {user.token}")
            return

        user_token = await session.exec(select(UserToken).where(UserToken.token == token))
        user_token = user_token.one_or_none()

        if not user_token:
            await message.reply(f"Token {token} not found.")
            return

        if not user:
            user = User(telegram_id=user_id, token=token)
        else:
            user.token = token

        session.add(user)
        await session.commit()

        await message.reply(f"Token {token} registered successfully. Your balance is {user_token.balance}")

async def on_unregister(message: types.Message):
    user_id = message.from_user.id

    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if not user or not user.token:
            await message.reply("You don't have any token.")
            return

        user.token = None
        await session.commit()

        await message.reply("Token unregistered successfully.")

async def on_info(message: types.Message):
    user_id = message.from_user.id

    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if not user or not user.token:
            await message.reply("You don't have any token.")
            return

        user_token = await session.exec(select(UserToken).where(UserToken.token == user.token))
        user_token = user_token.one_or_none()

        if not user_token:
            await message.reply(f"Token not found.")
            return

        await message.reply(f"Token: {user.token}\nBalance: {user_token.balance}")

async def on_balance(message: types.Message):
    user_id = message.from_user.id

    async with Session(engine) as session:
        user = await session.exec(select(User).where(User.telegram_id == user_id))
        user = user.one_or_none()

        if not user or not user.token:
            await message.reply("You don't have any token.")
            return

        user_token = await session.exec(select(UserToken).where(UserToken.token == user.token))
        user_token = user_token.one_or_none()

        if not user_token:
            await message.reply(f"Token not found.")
            return

        await message.reply(f"Balance: {user_token.balance}")

# Command handler to initiate the process of suspending a profile
async def on_suspend(message: types.Message):
    await message.reply("Please enter the profile name to suspend:")
    await Form.profile_name.set()

# Handler to receive the profile name for suspension
@dp.message_handler(state=Form.profile_name)
async def process_suspend_profile(message: types.Message, state: FSMContext):
    profile_name = message.text.strip()
    user_id = message.from_user.id

    async with Session(engine) as session:
        profile = await session.exec(select(VPNProfile).where(VPNProfile.user_id == user_id, VPNProfile.name == profile_name))
        profile = profile.one_or_none()

        if not profile:
            await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)
            await state.finish()
            return

        profile.status = 'suspended'
        await session.commit()

        os.system(f"docker exec -it wireguard /app/manage-peer suspend {user_id + 'p' + profile_name}")
        await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' suspended successfully.", parse_mode=ParseMode.MARKDOWN)
        await state.finish()

# Command handler to initiate the process of resuming a profile
async def on_resume(message: types.Message):
    await message.reply("Please enter the profile name to resume:")
    await Form.profile_name.set()

# Handler to receive the profile name for resumption
@dp.message_handler(state=Form.profile_name)
async def process_resume_profile(message: types.Message, state: FSMContext):
    profile_name = message.text.strip()
    user_id = message.from_user.id

    async with Session(engine) as session:
        profile = await session.exec(select(VPNProfile).where(VPNProfile.user_id == user_id, VPNProfile.name == profile_name))
        profile = profile.one_or_none()

        if not profile:
            await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)
            await state.finish()
            return

        profile.status = 'active'
        await session.commit()

        os.system(f"docker exec -it wireguard /app/manage-peer resume {user_id + 'p' + profile_name}")
        await message.reply(f"VPN profile '{markdown.escape_md(profile_name)}' resumed successfully.", parse_mode=ParseMode.MARKDOWN)
        await state.finish()

# Register message handlers
dp.register_message_handler(on_start, commands=["start"])
dp.register_message_handler(on_help, commands=["help"])
dp.register_message_handler(on_add, commands=["add"], state="*")
dp.register_message_handler(on_list, commands=["list"])
dp.register_message_handler(on_get, commands=["get"])
dp.register_message_handler(on_delete, commands=["delete"])
dp.register_message_handler(on_register, commands=["register"])
dp.register_message_handler(on_unregister, commands=["unregister"])
dp.register_message_handler(on_info, commands=["info"])
dp.register_message_handler(on_balance, commands=["balance"])
dp.register_message_handler(on_suspend, commands=["suspend"], state="*")
dp.register_message_handler(on_resume, commands=["resume"], state="*")

if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
