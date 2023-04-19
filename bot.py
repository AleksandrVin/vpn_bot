# telegram bot for vpn access
# using aiogram python3 library
# data is stored in sqlite3 database. 2 tables: users and vpn_profiles (1 user can have multiple vpn profiles)
# users table: user_id, telegram_id
# vpn_profiles table: id, user_id, name
# methods /start /add /list /delete /help

# get telegram bot token from environment variable TELEGRAM_BOT_TOKEN
import sys
import signal
import sqlite3
from aiogram.utils.markdown import text, escape_md
from aiogram.utils import executor
from aiogram.types import ParseMode
from aiogram.contrib.middlewares.logging import LoggingMiddleware
from aiogram import Bot, Dispatcher, types
from aiogram import executor
import logging
import os
import yaml

# check if TELEGRAM_BOT_TOKEN is set
API_TOKEN = os.environ.get('TELEGRAM_BOT_TOKEN')
if API_TOKEN is None:
    print("Please set TELEGRAM_BOT_TOKEN environment variable")
    sys.exit(1)

logging.basicConfig(level=logging.INFO)

bot = Bot(token=API_TOKEN)
dp = Dispatcher(bot)
dp.middleware.setup(LoggingMiddleware())

# Initialize the database
conn = sqlite3.connect("vpn_profiles.db")
cursor = conn.cursor()

cursor.execute("""CREATE TABLE IF NOT EXISTS users (
                    user_id INTEGER PRIMARY KEY,
                    telegram_id INTEGER UNIQUE,
                    token TEXT)""")
cursor.execute("""CREATE TABLE IF NOT EXISTS vpn_profiles (
                    id INTEGER PRIMARY KEY,
                    user_id INTEGER,
                    name TEXT,
                    creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id))""")
cursor.execute("""CREATE TABLE IF NOT EXISTS users_tokens (
                    id INTEGER PRIMARY KEY,
                    token TEXT UNIQUE,
                    creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    balance INTEGER)""")
conn.commit()


async def on_start(message: types.Message):
    user_id = message.from_user.id
    cursor.execute(
        "INSERT OR IGNORE INTO users (telegram_id) VALUES (?)", (user_id,))
    conn.commit()
    await message.reply("Welcome to the VPN Access Bot! Use /help for available commands.")


async def on_help(message: types.Message):
    help_text = (
        "/start - Initialize user in the system\n"
        "/add - Add a new VPN profile\n"
        "/list - List all VPN profiles\n"
        "/delete - Delete a VPN profile\n"
        "/help - Show this help message\n"
        "/get - Get .conf file and qr code for wireguard client application for existing peer\n"
    )
    await message.reply(help_text)


async def send_config(message: types.Message, name_for_wg, profile_name):
    # send the profile to the user form ~/wg_config/ directory. Each profile is a file with name user_id + profile_name \
    # e.g. 1234567890profile1 and stored in folder ~/wg_config/peer_1234567890profile1/peer_1234567890profile1.conf
    file_path = f"~/wg_config/peer_{name_for_wg}/peer_{name_for_wg}.conf"
    qr_code_path = f"~/wg_config/peer_{name_for_wg}/peer_{name_for_wg}.png"

    expanded_file_path = os.path.expanduser(file_path)
    # reply document but replace name for user
    await message.reply_document(open(expanded_file_path, "rb"), caption=f"{profile_name}.conf")
    # also send png image with qr code
    expanded_file_path = os.path.expanduser(qr_code_path)
    await message.reply_photo(open(expanded_file_path, "rb"), caption=f"{profile_name}.png")


async def on_add(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[5:].strip()

    if not profile_name:
        await message.reply("Please provide a profile name after the /add command.")
        return
    
    # check if user have token with balance > 0
    cursor.execute(
        "SELECT token, balance FROM users_tokens WHERE balance > 0")

    # Check if the profile already exists for this user_id
    cursor.execute(
        "SELECT * FROM vpn_profiles WHERE user_id = ? AND name = ?", (user_id, profile_name))
    profile_exists = cursor.fetchone()

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + profile_name

    if profile_exists:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' already exists.", parse_mode=ParseMode.MARKDOWN)
        await send_config(message, name_for_wg, profile_name)
        return

    cursor.execute(
        "INSERT INTO vpn_profiles (user_id, name) VALUES (?, ?)", (user_id, profile_name))

    # run command inside docker container
    os.system(f"docker exec -it wireguard /app/manage-peer add {name_for_wg}")
    conn.commit()
    await message.reply(f"VPN profile '{escape_md(profile_name)}' added successfully. \n Your .conf file and qr code for wireguard client application", parse_mode=ParseMode.MARKDOWN)
    await send_config(message, name_for_wg, profile_name)


async def on_list(message: types.Message):
    user_id = message.from_user.id
    cursor.execute(
        "SELECT name, creation_time FROM vpn_profiles WHERE user_id = ?", (user_id,))
    profiles = cursor.fetchall()

    if not profiles:
        await message.reply("You have no VPN profiles.")
        return

    profile_list = text("Your VPN profiles:")
    for profile in profiles:
        profile_list += text("\n- ", escape_md(profile[0])) + text(" created: ", escape_md(profile[1]), "\n")

    await message.reply(profile_list, parse_mode=ParseMode.MARKDOWN)

# send config file to user when he send /get command
async def on_get(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[5:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to get after the /get command.")
        return

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + profile_name
    await send_config(message, name_for_wg, profile_name)


async def on_delete(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[8:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to delete after the /delete command.")
        return

    cursor.execute(
        "DELETE FROM vpn_profiles WHERE user_id = ? AND name = ?", (user_id, profile_name))
    conn.commit()

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + profile_name
    # run command inside docker container
    os.system(
        f"docker exec -it wireguard /app/manage-peer remove {name_for_wg}")

    if cursor.rowcount:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' deleted successfully.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)

# register user access token
async def on_register(message: types.Message):
    user_id = message.from_user.id
    token = message.text[10:].strip()

    if not token:
        await message.reply("Please provide the token you want to register after the /register command.")
        return


dp.register_message_handler(on_start, commands=['start'])
dp.register_message_handler(on_help, commands=['help'])
dp.register_message_handler(on_add, commands=['add'])
dp.register_message_handler(on_list, commands=['list'])
dp.register_message_handler(on_delete, commands=['delete'])
dp.register_message_handler(on_get, commands=['get'])

# handler for SIGINT and SIGTERM signals


def signal_handler(sig, frame):
    print('You pressed Ctrl+C!')
    # stop docker container using docker compose
    if os.system("docker compose down") == 0:
        print("Docker container stopped")
    else:
        print("Failed to stop docker container")

    import re
    file_path = f"~/wg_config/.donoteditthisfile"
    expanded_file_path = os.path.expanduser(file_path)

    # Read the file
    with open(expanded_file_path, "r") as file:
        file_contents = file.read()

        # Find the value of ORIG_PEERS using a regular expression
        orig_peers_match = re.search(r"ORIG_PEERS=\"(.+?)\"", file_contents)
        orig_peers = orig_peers_match.group(1) if orig_peers_match else None

    # Print the value of ORIG_PEERS
    if orig_peers:
        print("ORIG_PEERS:", orig_peers)
    else:
        print("ORIG_PEERS not found")

    # open docker-compose.yml using yaml library and update PEERS variable
    with open("docker-compose.yml", "r") as f:
        data = yaml.safe_load(f)

        data['services']['wireguard']['environment'] = [
            env_var if 'PEERS' not in env_var else f'PEERS={orig_peers}'
            for env_var in data['services']['wireguard']['environment']
        ]

    # save updated docker-compose.yml file
    with open("docker-compose.yml", "w") as f:
        yaml.safe_dump(data, f)

    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

if __name__ == '__main__':
    # start docker container in the background using docker compose
    if os.system("docker compose up -d") == 0:
        print("Docker container started")
    else:
        print("Failed to start docker container")
        exit(1)

    executor.start_polling(dp, skip_updates=True)
