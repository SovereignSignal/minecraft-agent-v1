import yaml
import sys
import os
import openai
from minecraft.networking.connection import Connection
from minecraft.networking.packets import ChatMessagePacket, Packet
from minecraft.networking.packets import clientbound
import json
import datetime
import sqlite3

LOG_PATH = "agent.log"
MEMORY_DB = "agent_memory.db"

# Logging
def log(msg):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a") as f:
        f.write(line + "\n")

# Persistent memory (SQLite)
def init_memory():
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            sender TEXT,
            message TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS facts (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)
    conn.commit()
    conn.close()

def save_chat(sender, message):
    conn = sqlite3.connect(MEMORY_DB)
    c = conn.cursor()
    c.execute("INSERT INTO chat_history (timestamp, sender, message) VALUES (?, ?, ?)",
              (datetime.datetime.now().isoformat(), sender, message))
    conn.commit()
    conn.close()

init_memory()

# Load config
def load_config(path="config.yaml"):
    log(f"Loading config from {path}")
    with open(path, 'r') as f:
        return yaml.safe_load(f)

config = load_config()

# Load sensitive info from environment variables if set
openai_api_key = os.getenv("OPENAI_API_KEY", config['openai']['api_key'])
openai_model = config['openai']['model']

server_host = config['minecraft']['server_host']
server_port = config['minecraft']['server_port']
username = config['minecraft']['username']
password = os.getenv("MINECRAFT_PASSWORD", config['minecraft']['password'])

db_path = config['memory']['db_path']

openai.api_key = openai_api_key

log(f"Agent starting with username '{username}' on {server_host}:{server_port} using model '{openai_model}'")

conn = Connection(server_host, server_port, username=username)

# Track online players
online_players = set()

def log_players():
    log(f"Online players: {', '.join(sorted(online_players)) if online_players else '[none]'}")

# Listen for player info packets
def handle_player_info(packet):
    # PlayerListItemPacket is called PlayerInfoPacket in pyCraft
    for action in packet.actions:
        if action.name == 'ADD_PLAYER':
            for info in packet.player_infos:
                online_players.add(info.name)
                log(f"Player joined: {info.name}")
        elif action.name == 'REMOVE_PLAYER':
            for info in packet.player_infos:
                if info.name in online_players:
                    online_players.remove(info.name)
                    log(f"Player left: {info.name}")
    log_players()

conn.register_packet_listener(handle_player_info, clientbound.play.PlayerInfoPacket)

# Helper to send a chat message to the server
def send_chat(msg):
    log(f"Sending chat: {msg}")
    packet = ChatMessagePacket()
    packet.message = msg
    conn.write_packet(packet)

# Command parser
def parse_command(msg_text):
    # Example: "AgentBot1, say hello!"
    if msg_text.lower().startswith(username.lower()):
        cmd = msg_text[len(username):].strip().lstrip(",: ")
        if cmd.lower().startswith("say "):
            return ("say", cmd[4:])
        elif cmd.lower().startswith("jump"):
            return ("jump", None)
        # Add more commands here
    return (None, None)

# Handle chat messages received from the server
def handle_chat(packet):
    try:
        # Minecraft 1.19+ uses JSON chat, older versions use plain text
        data = json.loads(packet.json_data)
        if 'extra' in data:
            msg_text = ''.join([part.get('text', '') for part in data['extra']])
        else:
            msg_text = data.get('text', '')
    except Exception:
        msg_text = getattr(packet, 'message', str(packet))
    log(f"[CHAT RECEIVED] {msg_text}")
    save_chat("player", msg_text)
    # Command parsing
    cmd, arg = parse_command(msg_text)
    if cmd == "say":
        send_chat(arg)
    elif cmd == "jump":
        send_chat("*jumps*")
    elif username.lower() in msg_text.lower() or 'agentbot' in msg_text.lower():
        prompt = f"You are a helpful Minecraft agent. The user said: {msg_text}. Reply as the agent in Minecraft chat."
        try:
            log(f"Sending message to OpenAI: {msg_text}")
            response = openai.ChatCompletion.create(
                model=openai_model,
                messages=[{"role": "system", "content": "You are a helpful Minecraft agent."},
                          {"role": "user", "content": msg_text}]
            )
            reply = response.choices[0].message['content'].strip()
            log(f"OpenAI reply: {reply}")
            send_chat(reply[:256])  # Minecraft chat limit
        except Exception as e:
            log(f"[OpenAI Error] {e}")
            send_chat("[Agent Error] Could not process your request.")

conn.register_packet_listener(handle_chat, ChatMessagePacket)

try:
    log(f"Connecting to {server_host}:{server_port} as {username}...")
    conn.connect()
    log("Successfully connected and joined the server.")
except Exception as e:
    log(f"Failed to connect: {e}")
    sys.exit(1)

# Keep the script running
try:
    while True:
        pass
except KeyboardInterrupt:
    log("Disconnecting...")
    conn.disconnect() 