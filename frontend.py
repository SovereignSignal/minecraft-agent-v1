import streamlit as st
import yaml
import os
import subprocess
import signal
import time
import openai
import socket
from mcstatus import JavaServer
import re

CONFIG_PATH = "config.yaml"
AGENT_PROCESS = None
LOG_PATH = "agent.log"

# Helper to load config
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        yaml.safe_dump(config, f)

# Fetch recent OpenAI models
def get_openai_models(api_key):
    try:
        openai.api_key = api_key
        models = openai.models.list()
        sorted_models = sorted(models.data, key=lambda m: getattr(m, 'created', 0), reverse=True)
        model_ids = [m.id for m in sorted_models if 'gpt' in m.id or 'o' in m.id]
        return model_ids[:10]
    except Exception as e:
        return ["gpt-4o", "gpt-4", "gpt-3.5-turbo", "o4-mini", "o3"]

# Test OpenAI API Key
def test_openai_api_key(api_key):
    try:
        openai.api_key = api_key
        openai.models.list()
        return True, "API key is valid!"
    except Exception as e:
        return False, f"API key test failed: {e}"

# Test Minecraft server connection (detailed ping)
def test_minecraft_server(host, port, username, password):
    try:
        server = JavaServer.lookup(f"{host}:{port}")
        status = server.status()
        info = f"Server is online!\nVersion: {status.version.name}\nMOTD: {status.description}\nPlayers: {status.players.online}/{status.players.max}"
        return True, info
    except Exception as e:
        return False, f"Server connection failed: {e}"

# Helper to start/stop agent
def start_agent():
    env = os.environ.copy()
    config = load_config()
    env["OPENAI_API_KEY"] = st.session_state.get("api_key", "")
    if st.session_state.get("password"):
        env["MINECRAFT_PASSWORD"] = st.session_state["password"]
    # Start agent.py and redirect output to log
    return subprocess.Popen([
        "python", "agent.py"
    ], env=env, stdout=open(LOG_PATH, "w"), stderr=subprocess.STDOUT)

def stop_agent(proc):
    if proc and proc.poll() is None:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()

def extract_players_from_log(log_lines):
    # Find the most recent "Online players:" line
    for line in reversed(log_lines):
        if "Online players:" in line:
            players = line.split("Online players:", 1)[1].strip()
            if players == "[none]":
                return []
            return [p.strip() for p in players.split(",") if p.strip()]
    return []

# UI
st.title("Minecraft Agent Manager")

config = load_config()

# Fetch models for dropdown
api_key_for_models = os.getenv("OPENAI_API_KEY", config['openai']['api_key'])
model_options = get_openai_models(api_key_for_models)

# Always use config.yaml as the source of truth for form defaults
with st.form("config_form"):
    st.subheader("Agent Configuration")
    api_key = st.text_input("OpenAI API Key", value=os.getenv("OPENAI_API_KEY", config['openai']['api_key']), type="password")
    test_api = st.form_submit_button("Test API Key", use_container_width=True)
    if test_api:
        ok, msg = test_openai_api_key(api_key)
        if ok:
            st.success(msg)
        else:
            st.error(msg)
    model = st.selectbox("OpenAI Model", options=model_options, index=model_options.index(config['openai']['model']) if config['openai']['model'] in model_options else 0)
    server_host = st.text_input("Minecraft Server Host", value=config['minecraft']['server_host'])
    server_port = st.number_input("Minecraft Server Port", value=config['minecraft']['server_port'], step=1)
    username = st.text_input("Agent Username", value=config['minecraft']['username'])
    password = st.text_input("Minecraft Password (if needed)", value=os.getenv("MINECRAFT_PASSWORD", config['minecraft']['password']), type="password")
    test_server = st.form_submit_button("Test Server Connection", use_container_width=True)
    if test_server:
        ok, msg = test_minecraft_server(server_host, server_port, username, password)
        if ok:
            st.success(msg)
        else:
            st.error(msg)
    submitted = st.form_submit_button("Save Configuration")
    if submitted:
        config['openai']['api_key'] = "${OPENAI_API_KEY}"
        config['openai']['model'] = model
        config['minecraft']['server_host'] = server_host
        config['minecraft']['server_port'] = int(server_port)
        config['minecraft']['username'] = username
        config['minecraft']['password'] = "${MINECRAFT_PASSWORD}"
        save_config(config)
        st.session_state["api_key"] = api_key
        st.session_state["password"] = password
        st.success("Configuration saved! (API key and password are kept in memory only)")

# Agent controls
if "agent_proc" not in st.session_state:
    st.session_state["agent_proc"] = None

col1, col2 = st.columns(2)
with col1:
    if st.session_state["agent_proc"] is None or st.session_state["agent_proc"].poll() is not None:
        if st.button("Start Agent"):
            st.session_state["agent_proc"] = start_agent()
            st.success("Agent started!")
    else:
        st.write("Agent is running.")
with col2:
    if st.session_state["agent_proc"] is not None and st.session_state["agent_proc"].poll() is None:
        if st.button("Stop Agent"):
            stop_agent(st.session_state["agent_proc"])
            st.session_state["agent_proc"] = None
            st.success("Agent stopped.")

# Show agent logs and live player list
st.subheader("Agent Log & Online Players")

# Auto-refresh every 3 seconds
st_autorefresh = st.empty()
log_box = st.empty()
player_box = st.empty()

while True:
    if os.path.exists(LOG_PATH):
        with open(LOG_PATH, "r") as f:
            log_lines = f.readlines()[-100:]
        # Show log
        log_box.text("".join(log_lines))
        # Show player list
        players = extract_players_from_log(log_lines)
        player_box.markdown(f"**Online Players:** {', '.join(players) if players else '[none]'}")
    else:
        log_box.info("No log file yet.")
        player_box.markdown("**Online Players:** [none]")
    # Auto-refresh every 3 seconds
    time.sleep(3)
    st_autorefresh.empty() 