# this script can add, remove, update user token in database
# Path: manage_token.py

import sqlite3
import os
import sys

# Connect to the SQLite database file
conn = sqlite3.connect('vpn_profiles.db')

# Define a function to add balance to a token


def add_balance(token, amount):
    c = conn.cursor()
    c.execute(
        'UPDATE users_tokens SET balance = balance + ? WHERE token = ?', (amount, token))
    conn.commit()

# Define a function to remove balance from a token


def remove_balance(token, amount):
    c = conn.cursor()
    c.execute(
        'UPDATE users_tokens SET balance = balance - ? WHERE token = ?', (amount, token))
    conn.commit()

# Define a function to update the balance of a token


def update_balance(token, new_balance):
    c = conn.cursor()
    c.execute('UPDATE users_tokens SET balance = ? WHERE token = ?',
              (new_balance, token))
    conn.commit()

# Define a function to generate a new token with a balance of 0


def generate_token(balance):
    token = os.urandom(16).hex()
    c = conn.cursor()
    c.execute(
        'INSERT INTO users_tokens (token, balance) VALUES (?, ?)', (token, balance))
    conn.commit()
    return token

# Define a function to list all tokens


def list_tokens():
    c = conn.cursor()
    c.execute('SELECT * FROM users_tokens')
    for row in c:
        print(row)


USAGE = "Usage: manage_token.py [add|remove|update|generate|list] [token] [amount]"

if __name__ == '__main__':
    # if no arguments are passed, print usage
    if len(sys.argv) == 1:
        print(USAGE)
        sys.exit(1)

    # if the first argument is list, list all tokens
    elif sys.argv[1] == 'list':
        list_tokens()
        sys.exit(0)

    # if the first argument is generate, generate a new token
    elif sys.argv[1] == 'generate':
        balance = sys.argv[2]
        # check if balance is a number above 0
        if balance.isdigit() and int(balance) >= 0:
            balance = int(balance)
        else:
            print("Balance must be a number above 0")
            sys.exit(1)
        print(generate_token(balance))
        sys.exit(0)

    # if number of arguments is not 4, print usage
    if len(sys.argv) != 4:
        print(USAGE)
        sys.exit(1)

    balance = sys.argv[3]
    # check if balance is a number above 0
    if balance.isdigit() and int(balance) >= 0:
        balance = int(balance)
    else:
        print("Balance must be a number above 0")
        sys.exit(1)

    # if the first argument is add, add balance to the token
    if sys.argv[1] == 'add':
        add_balance(sys.argv[2], balance)
    # if the first argument is remove, remove balance from the token
    elif sys.argv[1] == 'remove':
        remove_balance(sys.argv[2], balance)
    # if the first argument is update, update the balance of the token
    elif sys.argv[1] == 'update':
        update_balance(sys.argv[2], balance)

    else:
        print(USAGE)
        sys.exit(1)
