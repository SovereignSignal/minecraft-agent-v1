import streamlit as st
import yaml
import os
import subprocess
import signal
import time
import openai
import socket
import json
import hashlib
from mcstatus import JavaServer
import re
from pathlib import Path
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

CONFIG_PATH = "config.yaml"
SECRETS_PATH = ".agent_secrets.enc"
AGENT_PROCESS = None
LOG_PATH = "agent.log"
SALT = b'minecraft_agent_salt'  # Not truly secure but better than plaintext

# Helper to load config
def load_config():
    with open(CONFIG_PATH, 'r') as f:
        return yaml.safe_load(f)

def save_config(config):
    with open(CONFIG_PATH, 'w') as f:
        yaml.safe_dump(config, f)
        
# Helper functions for secure credential storage
def get_encryption_key(password):
    """Generate an encryption key from password"""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=SALT,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key

def save_secrets(data, password):
    """Encrypt and save secrets"""
    try:
        key = get_encryption_key(password)
        f = Fernet(key)
        encrypted_data = f.encrypt(json.dumps(data).encode())
        with open(SECRETS_PATH, 'wb') as file:
            file.write(encrypted_data)
        return True
    except Exception as e:
        st.error(f"Failed to save secrets: {e}")
        return False

def load_secrets(password):
    """Load and decrypt secrets"""
    try:
        if not Path(SECRETS_PATH).exists():
            return {}
        
        key = get_encryption_key(password)
        f = Fernet(key)
        with open(SECRETS_PATH, 'rb') as file:
            encrypted_data = file.read()
        decrypted_data = f.decrypt(encrypted_data)
        return json.loads(decrypted_data)
    except Exception as e:
        # Could be wrong password or corrupted file
        return {}

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
    
    # Use securely stored credentials
    if st.session_state.get("authenticated") and st.session_state.get("api_key"):
        env["OPENAI_API_KEY"] = st.session_state["api_key"]
    if st.session_state.get("authenticated") and st.session_state.get("mc_password"):
        env["MINECRAFT_PASSWORD"] = st.session_state["mc_password"]
        
    # Start agent.py and append output to log (using 'a' instead of 'w' to preserve history)
    return subprocess.Popen([
        "python", "agent.py"
    ], env=env, stdout=open(LOG_PATH, "a"), stderr=subprocess.STDOUT)

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

# UI Setup and Authentication
st.title("Minecraft Agent Manager")

# Initialize session state
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "admin_password" not in st.session_state:
    st.session_state["admin_password"] = ""
if "secrets" not in st.session_state:
    st.session_state["secrets"] = {}
if "api_key" not in st.session_state:
    st.session_state["api_key"] = ""
if "mc_password" not in st.session_state:
    st.session_state["mc_password"] = ""

# Load configuration
config = load_config()

# Authentication section
if not st.session_state["authenticated"]:
    st.info("Enter the admin password to change settings or '123456' if this is your first time")
    
    admin_pwd = st.text_input("Admin Password", type="password")
    if st.button("Login"):
        # For first time setup, allow default password
        if admin_pwd == "123456" and not Path(SECRETS_PATH).exists():
            st.session_state["authenticated"] = True
            st.session_state["admin_password"] = admin_pwd
            st.session_state["secrets"] = {}
            st.success("First-time login successful! Please change the default password.")
            st.rerun()
        else:
            # Try to decrypt with provided password
            secrets = load_secrets(admin_pwd)
            if secrets:
                st.session_state["authenticated"] = True
                st.session_state["admin_password"] = admin_pwd
                st.session_state["secrets"] = secrets
                
                # Load secrets into session
                st.session_state["api_key"] = secrets.get("openai_api_key", "")
                st.session_state["mc_password"] = secrets.get("minecraft_password", "")
                st.success("Login successful!")
                st.rerun()
            else:
                st.error("Invalid password or no stored secrets found.")
else:
    # Admin controls - only show when authenticated
    with st.expander("Admin Controls", expanded=False):
        # Change admin password
        st.subheader("Change Admin Password")
        new_pwd = st.text_input("New Admin Password", type="password")
        confirm_pwd = st.text_input("Confirm New Password", type="password")
        
        if st.button("Update Admin Password"):
            if new_pwd != confirm_pwd:
                st.error("Passwords do not match!")
            elif not new_pwd:
                st.error("Password cannot be empty")
            else:
                # Save secrets with new password
                if save_secrets(st.session_state["secrets"], new_pwd):
                    st.session_state["admin_password"] = new_pwd
                    st.success("Admin password updated successfully!")
        
        if st.button("Logout", type="primary"):
            st.session_state["authenticated"] = False
            st.session_state["admin_password"] = ""
            st.rerun()
    
    # Configuration section - only show when authenticated
    st.markdown("---")
    st.subheader("Agent Configuration")
    
    # Fetch models for dropdown using stored API key
    api_key_for_models = st.session_state["api_key"] or os.getenv("OPENAI_API_KEY", "")
    model_options = get_openai_models(api_key_for_models)
    
    # Configuration form
    with st.form("config_form"):
        api_key = st.text_input("OpenAI API Key", 
                               value=st.session_state["api_key"], 
                               type="password")
        test_api = st.form_submit_button("Test API Key", use_container_width=True)
        if test_api:
            ok, msg = test_openai_api_key(api_key)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
                
        model = st.selectbox("OpenAI Model", 
                           options=model_options, 
                           index=model_options.index(config['openai']['model']) 
                                 if config['openai']['model'] in model_options else 0)
        
        server_host = st.text_input("Minecraft Server Host", 
                                  value=config['minecraft']['server_host'])
        server_port = st.number_input("Minecraft Server Port", 
                                    value=config['minecraft']['server_port'], 
                                    step=1)
        username = st.text_input("Agent Username", 
                              value=config['minecraft']['username'])
        mc_password = st.text_input("Minecraft Password (if needed)", 
                                 value=st.session_state["mc_password"], 
                                 type="password")
        
        test_server = st.form_submit_button("Test Server Connection", use_container_width=True)
        if test_server:
            ok, msg = test_minecraft_server(server_host, server_port, username, mc_password)
            if ok:
                st.success(msg)
            else:
                st.error(msg)
                
        submitted = st.form_submit_button("Save Configuration")
        if submitted and st.session_state["authenticated"]:
            # Update configuration file
            config['openai']['api_key'] = "${OPENAI_API_KEY}"  # Placeholder in config file
            config['openai']['model'] = model
            config['minecraft']['server_host'] = server_host
            config['minecraft']['server_port'] = int(server_port)
            config['minecraft']['username'] = username
            config['minecraft']['password'] = "${MINECRAFT_PASSWORD}"  # Placeholder in config file
            save_config(config)
            
            # Store actual secrets securely
            st.session_state["secrets"]["openai_api_key"] = api_key
            st.session_state["secrets"]["minecraft_password"] = mc_password
            
            # Save to encrypted storage
            if save_secrets(st.session_state["secrets"], st.session_state["admin_password"]):
                # Update session state
                st.session_state["api_key"] = api_key
                st.session_state["mc_password"] = mc_password
                st.success("Configuration saved securely!")
            else:
                st.error("Failed to save secrets securely. Settings not updated.")

# Agent controls
if "agent_proc" not in st.session_state:
    st.session_state["agent_proc"] = None

st.markdown("---")
st.subheader("Agent Controls")

col1, col2 = st.columns(2)
with col1:
    if st.session_state["agent_proc"] is None or st.session_state["agent_proc"].poll() is not None:
        if st.button("Start Agent", type="primary"):
            # Set environment variables from secure storage
            env = os.environ.copy()
            if st.session_state.get("api_key"):
                env["OPENAI_API_KEY"] = st.session_state["api_key"]
            if st.session_state.get("mc_password"):
                env["MINECRAFT_PASSWORD"] = st.session_state["mc_password"]
                
            # Start the agent with the secured credentials
            st.session_state["agent_proc"] = subprocess.Popen([
                "python", "agent.py"
            ], env=env, stdout=open(LOG_PATH, "a"), stderr=subprocess.STDOUT)
            
            st.success("Agent started!")
    else:
        st.info("Agent is running")
with col2:
    if st.session_state["agent_proc"] is not None and st.session_state["agent_proc"].poll() is None:
        if st.button("Stop Agent", type="secondary"):
            stop_agent(st.session_state["agent_proc"])
            st.session_state["agent_proc"] = None
            st.success("Agent stopped")

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