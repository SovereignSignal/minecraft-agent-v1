import yaml
import sys
import os
import openai
import time
import signal
import threading
from minecraft.networking.connection import Connection
from minecraft.networking.packets import ChatMessagePacket, Packet
from minecraft.networking.packets import clientbound
from minecraft.exceptions import YggdrasilError
import json
import datetime
import sqlite3

LOG_PATH = "agent.log"
MEMORY_DB = "agent_memory.db"

# Global control variables
running = True
connection_active = False

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

# Initialize connection but don't connect yet
conn = None

# Handler for clean shutdown
def handle_shutdown(signum=None, frame=None):
    global running
    log("Shutting down agent...")
    running = False
    if conn and conn.connected:
        conn.disconnect()
    log("Agent shutdown complete.")

# Register signal handlers for graceful shutdown
signal.signal(signal.SIGINT, handle_shutdown)
signal.signal(signal.SIGTERM, handle_shutdown)

# Track online players
online_players = set()

def log_players():
    log(f"Online players: {', '.join(sorted(online_players)) if online_players else '[none]'}")

# Listen for player info packets
def handle_player_info(packet):
    # In newer pyCraft versions, it's PlayerListItemPacket
    try:
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
    except Exception as e:
        log(f"Error processing player info packet: {e}")

def register_packet_listeners(connection):
    """Register all packet listeners on the connection"""
    # Try both potential packet names for player info
    try:
        # First try the newer PlayerListItemPacket (most versions)
        from minecraft.networking.packets.clientbound.play import PlayerListItemPacket
        connection.register_packet_listener(handle_player_info, PlayerListItemPacket)
        log("Registered PlayerListItemPacket listener")
    except (ImportError, AttributeError):
        try:
            # Fall back to older PlayerInfoPacket name
            connection.register_packet_listener(handle_player_info, clientbound.play.PlayerInfoPacket)
            log("Registered PlayerInfoPacket listener")
        except (ImportError, AttributeError):
            log("Warning: Could not register player info packet listener")

    connection.register_packet_listener(handle_chat, ChatMessagePacket)

    # Register disconnect handler
    connection.register_packet_listener(
        lambda packet: handle_disconnect(packet, connection),
        clientbound.play.DisconnectPacket
    )
    # Register keepalive handler to respond to server pings
    connection.register_packet_listener(
        lambda packet: handle_keepalive(packet, connection),
        clientbound.play.KeepAlivePacket
    )

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

# Add new event handlers
def handle_disconnect(packet, connection):
    """Handle server disconnect packet"""
    global connection_active
    connection_active = False
    reason = getattr(packet, 'json_data', None)
    if reason:
        try:
            reason_text = json.loads(reason).get('text', 'Unknown reason')
        except:
            reason_text = reason
    else:
        reason_text = "Unknown reason"
    log(f"Disconnected from server: {reason_text}")

def handle_keepalive(packet, connection):
    """Handle and respond to keepalive packets"""
    try:
        if hasattr(packet, 'keep_alive_id'):
            # Respond with the same ID to keep the connection alive
            from minecraft.networking.packets import serverbound
            response = serverbound.play.KeepAlivePacket()
            response.keep_alive_id = packet.keep_alive_id
            connection.write_packet(response)
    except Exception as e:
        log(f"Error responding to keepalive: {e}")

def connect_to_server():
    """Attempt to connect to the server with reconnection logic"""
    global conn, connection_active
    
    max_retries = 3
    retry_count = 0
    retry_delay = 5  # seconds
    
    while running and retry_count < max_retries:
        try:
            # Create a new connection object if needed
            if conn is None or not conn.connected:
                conn = Connection(server_host, server_port, username=username, auth_token=password if password else None)
                register_packet_listeners(conn)
            
            log(f"Connecting to {server_host}:{server_port} as {username}...")
            conn.connect()
            log("Successfully connected and joined the server.")
            connection_active = True
            return True
        except YggdrasilError as e:
            log(f"Authentication error: {e}")
            log("Check your Minecraft username and password")
            return False
        except Exception as e:
            log(f"Connection error: {e}")
            retry_count += 1
            if retry_count < max_retries:
                log(f"Retrying in {retry_delay} seconds... (Attempt {retry_count+1}/{max_retries})")
                time.sleep(retry_delay)
                retry_delay *= 2  # Exponential backoff
            else:
                log("Max retry attempts reached, giving up.")
                return False
        except Exception as e:
            log(f"Failed to connect: {e}")
            return False
    
    # If we reach here, max retries exceeded
    log("Could not establish connection after maximum retries.")
    return False

# Connection monitor thread
def connection_monitor():
    """Monitor the connection and attempt to reconnect if disconnected"""
    global running, connection_active
    
    reconnect_delay = 10  # seconds
    
    while running:
        if not connection_active and running:
            log("Connection lost. Attempting to reconnect...")
            if connect_to_server():
                log("Reconnection successful!")
            else:
                log(f"Reconnection failed. Will try again in {reconnect_delay} seconds.")
                time.sleep(reconnect_delay)
        time.sleep(5)  # Check connection status every 5 seconds

# Start the agent
try:
    # Initial connection
    if connect_to_server():
        # Start connection monitor in a separate thread
        monitor_thread = threading.Thread(target=connection_monitor, daemon=True)
        monitor_thread.start()
        
        # Main loop - keep the script running but don't block with empty loop
        while running:
            time.sleep(1)
    else:
        log("Failed to establish initial connection. Exiting.")
except KeyboardInterrupt:
    handle_shutdown()
finally:
    # Ensure clean shutdown
    handle_shutdown()