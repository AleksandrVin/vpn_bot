# telegram bot for vpn access
# using aiogram python3 library
# data is stored in sqlite3 database. 
# 2 tables: users and vpn_profiles (1 user can have multiple vpn profiles)
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
                    name TEXT DEFAULT 'active',
                    status TEXT,
                    creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (user_id) REFERENCES users (user_id))""")
cursor.execute("""CREATE TABLE IF NOT EXISTS users_tokens (
                    id INTEGER PRIMARY KEY,
                    token TEXT UNIQUE,
                    creation_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    balance FLOAT DEFAULT 0)""")
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
        "/register - Register new token\n"
        "/add - Add a new VPN profile\n"
        "/list - List all VPN profiles\n"
        "/delete - Delete a VPN profile\n"
        "/help - Show this help message\n"
        "/get - Get .conf file and qr code for wireguard client application for existing peer\n"
        "/unregister - Unregister token\n"
        "/info - Show info about your token\n"
        "/balance - Show balance of your token\n"
        "/suspend - Suspend VPN profile\n"
        "/resume - Resume VPN profile\n"
    )
    await message.reply(help_text)


async def send_config(message: types.Message, name_for_wg, profile_name):
    # send the profile to the user form ~/wg_config/ directory. 
    # Each profile is a file with name user_id + profile_name \
    # e.g. 1234567890profile1 and stored in folder 
    # ~/wg_config/peer_1234567890profile1/peer_1234567890profile1.conf
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

    # Check if the profile already exists for this user_id
    cursor.execute(
        "SELECT * FROM vpn_profiles WHERE user_id = ? AND name = ?", (user_id, profile_name))
    profile_exists = cursor.fetchone()

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + 'p' + profile_name

    if profile_exists:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' already exists.", 
                            parse_mode=ParseMode.MARKDOWN)
        await send_config(message, name_for_wg, profile_name)
        return

    cursor.execute(
        "INSERT INTO vpn_profiles (user_id, name) VALUES (?, ?)", (user_id, profile_name))

    # run command inside docker container
    os.system(f"docker exec -it wireguard /app/manage-peer add {name_for_wg}")
    conn.commit()
    await message.reply(f"VPN profile '{escape_md(profile_name)}' added successfully. \n \
                        Your .conf file and qr code for wireguard client application", parse_mode=ParseMode.MARKDOWN)
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
    name_for_wg = str(user_id) + 'p' + profile_name
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
    name_for_wg = str(user_id) + 'p' + profile_name
    # run command inside docker container
    os.system(
        f"docker exec -it wireguard /app/manage-peer remove {name_for_wg}")

    if cursor.rowcount:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' deleted successfully.", parse_mode=ParseMode.MARKDOWN)
    else:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)

# regitster token for user
async def on_register(message: types.Message):
    user_id = message.from_user.id
    token = message.text[10:].strip()

    if not token:
        await message.reply("Please provide the token you want to register after the /register command.")
        return
    
    # get token from users database and check if it exists
    cursor.execute( "SELECT token FROM users WHERE user_id=?", (user_id,))
    user_token = cursor.fetchone()

    if user_token:
        await message.reply(f"You already have token: {user_token[0]}")
        return
    
    # check if token is not NONE
    if token == "NONE":
        await message.reply(f"Token {token} not found.")
        return
    
    # check if token exists in tokens database
    cursor.execute( "SELECT token FROM users_tokens WHERE token=?", (token,))
    token_exists = cursor.fetchone()

    if not token_exists:
        await message.reply(f"Token {token} not found.")
        return
    
    # add token to users database
    cursor.execute( "INSERT INTO users (user_id, token) VALUES (?, ?)", (user_id, token))
    conn.commit()

    # get balance from tokens database
    cursor.execute( "SELECT balance FROM users_tokens WHERE token=?", (token,))
    balance = cursor.fetchone()


    await message.reply(f"Token {token} registered successfully.")
    await message.reply(f"Your balance is {balance[0]}")


# remove token from user
async def on_unregister(message: types.Message):
    user_id = message.from_user.id

    # get token from users database and check if it exists
    cursor.execute( "SELECT token FROM users WHERE user_id=?", (user_id,))
    user_token = cursor.fetchone()

    if not user_token:
        await message.reply("You don't have any token.")
        return
    
    # replace token with None in users database
    cursor.execute( "UPDATE users SET token = ? WHERE user_id = ?", (None, user_id))
    conn.commit()

    await message.reply(f"Token {user_token[0]} unregistered successfully.")

# get information about token and balance
async def on_info(message: types.Message):
    user_id = message.from_user.id

    # get token from users database and check if it exists
    cursor.execute( "SELECT token FROM users WHERE user_id=?", (user_id,))
    user_token = cursor.fetchone()

    if not user_token:
        await message.reply("You don't have any token.")
        return
    
    # get balance from tokens database
    cursor.execute( "SELECT balance FROM users_tokens WHERE token=?", (user_token[0],))
    balance = cursor.fetchone()

    await message.reply(f"Your token is {user_token[0]}")
    await message.reply(f"Your balance is {balance[0]}")

# suspend user vpn profile
async def on_suspend(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[9:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to suspend after the /suspend command.")
        return
    
    # check if this profile exists in vpn profiles database and status is active
    cursor.execute( "SELECT status FROM vpn_profiles WHERE user_id = ? AND name = ?", (user_id, profile_name))
    profile_status = cursor.fetchone()

    if not profile_status:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if profile_status[0] == "suspended":
        await message.reply(f"VPN profile '{escape_md(profile_name)}' already suspended.", parse_mode=ParseMode.MARKDOWN)
        return
    
    # update status in vpn profiles database
    cursor.execute( "UPDATE vpn_profiles SET status = ? WHERE user_id = ? AND name = ?", ("suspended", user_id, profile_name))
    conn.commit()

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + 'p' + profile_name

    # run command inside docker container
    os.system(
        f"docker exec -it wireguard /app/manage-peer suspend {name_for_wg}")

    await message.reply(f"VPN profile '{escape_md(profile_name)}' suspended successfully.", parse_mode=ParseMode.MARKDOWN)

# resume user vpn profile
async def on_resume(message: types.Message):
    user_id = message.from_user.id
    profile_name = message.text[8:].strip()

    if not profile_name:
        await message.reply("Please provide the profile name you want to resume after the /resume command.")
        return
    
    # check if this profile exists in vpn profiles database and status is suspended
    cursor.execute( "SELECT status FROM vpn_profiles WHERE user_id = ? AND name = ?", (user_id, profile_name))
    profile_status = cursor.fetchone()

    if not profile_status:
        await message.reply(f"VPN profile '{escape_md(profile_name)}' not found.", parse_mode=ParseMode.MARKDOWN)
        return
    
    if profile_status[0] == "active":
        await message.reply(f"VPN profile '{escape_md(profile_name)}' already active.", parse_mode=ParseMode.MARKDOWN)
        return
    
    # update status in vpn profiles database
    cursor.execute( "UPDATE vpn_profiles SET status = ? WHERE user_id = ? AND name = ?", ("active", user_id, profile_name))
    conn.commit()

    # name for wg is user_id + profile_name
    name_for_wg = str(user_id) + 'p' + profile_name

    # run command inside docker container
    os.system(f"docker exec -it wireguard /app/manage-peer add {name_for_wg}")

    await message.reply(f"VPN profile '{escape_md(profile_name)}' resumed successfully.", parse_mode=ParseMode.MARKDOWN)

dp.register_message_handler(on_start, commands=['start'])
dp.register_message_handler(on_help, commands=['help'])
dp.register_message_handler(on_add, commands=['add'])
dp.register_message_handler(on_list, commands=['list'])
dp.register_message_handler(on_delete, commands=['delete'])
dp.register_message_handler(on_get, commands=['get'])
dp.register_message_handler(on_register, commands=['register'])
dp.register_message_handler(on_unregister, commands=['unregister'])
dp.register_message_handler(on_info, commands=['info'])
dp.register_message_handler(on_info, commands=['balance'])
dp.register_message_handler(on_suspend, commands=['suspend'])
dp.register_message_handler(on_resume, commands=['resume'])

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
