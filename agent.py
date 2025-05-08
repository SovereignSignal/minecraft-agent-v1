import yaml
import sys
import os
import openai
from minecraft.networking.connection import Connection
from minecraft.networking.packets import ChatMessagePacket, Packet
import json

# Load config
def load_config(path="config.yaml"):
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

conn = Connection(server_host, server_port, username=username, password=password)

# Helper to send a chat message to the server
def send_chat(msg):
    packet = ChatMessagePacket()
    packet.message = msg
    conn.write_packet(packet)

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
    print(f"[CHAT] {msg_text}")
    # Only respond to messages that mention the agent
    if username.lower() in msg_text.lower() or 'agentbot' in msg_text.lower():
        prompt = f"You are a helpful Minecraft agent. The user said: {msg_text}. Reply as the agent in Minecraft chat."
        try:
            response = openai.ChatCompletion.create(
                model=openai_model,
                messages=[{"role": "system", "content": "You are a helpful Minecraft agent."},
                          {"role": "user", "content": msg_text}]
            )
            reply = response.choices[0].message['content'].strip()
            send_chat(reply[:256])  # Minecraft chat limit
        except Exception as e:
            print(f"[OpenAI Error] {e}")
            send_chat("[Agent Error] Could not process your request.")

conn.register_packet_listener(handle_chat, ChatMessagePacket)

try:
    print(f"Connecting to {server_host}:{server_port} as {username}...")
    conn.connect()
except Exception as e:
    print(f"Failed to connect: {e}")
    sys.exit(1)

# Keep the script running
try:
    while True:
        pass
except KeyboardInterrupt:
    print("Disconnecting...")
    conn.disconnect() 