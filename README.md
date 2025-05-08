# Minecraft AI Agent

This project is a Minecraft agent that connects to a Java Edition server, listens to in-game chat commands, and will use an LLM (OpenAI, etc.) to act as a true AI agent with persistent memory.

## Features
- Connects to a Minecraft Java server as a player
- Listens to chat messages
- Modular LLM integration (OpenAI, o3, o4-mini, etc.)
- Persistent memory (SQLite)
- Extensible for new commands and behaviors
- **Web dashboard for easy management**

## Setup

### 1. Clone the repository
```
git clone <repo-url>
cd minecraft-agent-v1
```

### 2. Install dependencies
```
pip install -r requirements.txt
```

### 3. Start the web dashboard
```
chmod +x run.sh
./run.sh
```

Then visit [http://localhost:8501](http://localhost:8501) in your browser to configure and manage your agent.

### 4. (Optional) Manual CLI usage
You can still set environment variables and run the agent directly if you prefer:
```
export OPENAI_API_KEY="sk-..."
export MINECRAFT_PASSWORD="your_mc_password"  # Only if needed
python agent.py
```

## Next Steps
- Integrate LLM for command interpretation
- Add persistent memory and learning
- Implement in-game actions

---

**Note:** This is an early scaffold. More features and documentation coming soon! 