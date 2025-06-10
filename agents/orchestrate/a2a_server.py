# agents/orchestrate/server.py
import os
import logging
from dotenv import load_dotenv
import nest_asyncio

# Apply nest_asyncio early for compatibility with certain async environments
nest_asyncio.apply()

from common.server import A2AServer # Assuming common.server exists and defines A2AServer
from common.types import AgentCard, AgentCapabilities, AgentSkill
from common.task_manager import AgentTaskManager

# Import your HostAgent logic class
from orchestrate.host_agent import HostAgent

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- Environment Configuration for this Agent's A2A Server ---
# These should match what you put in docker-compose.yml for 'orchestrate' service
A2A_SERVER_HOST = os.environ.get("A2A_SERVER_HOST", "0.0.0.0")
A2A_SERVER_PORT = int(os.environ.get("A2A_SERVER_PORT", 10000)) # Assign a unique port, e.g., 10000
PUBLIC_URL = os.environ.get("PUBLIC_URL", f"http://localhost:{A2A_SERVER_PORT}")

# --- Remote Agent Addresses for HostAgent ---
REMOTE_AGENT_ADDRESSES_STR = os.getenv("REMOTE_AGENT_ADDRESSES", "")
REMOTE_AGENT_ADDRESSES = [addr.strip() for addr in REMOTE_AGENT_ADDRESSES_STR.split(',') if addr.strip()]
logger.info(f"Orchestrate Agent will connect to remote agents: {REMOTE_AGENT_ADDRESSES}")

def main():
    try:
        # Instantiate your HostAgent logic. This will connect to other agents.
        # You might add a TaskUpdateCallback here if you want orchestrate to
        # receive updates back from delegated tasks for real-time UI feedback etc.
        orchestrate_host_agent_logic = HostAgent(remote_agent_addresses=REMOTE_AGENT_ADDRESSES)

        # Create the ADK Agent instance that A2AServer will host
        orchestrate_adk_agent = orchestrate_host_agent_logic.create_agent()

        # Define the Agent Card for this Orchestrate Agent
        capabilities = AgentCapabilities(streaming=True) # Assuming it supports streaming
        skill = AgentSkill(
            id="orchestration_skill",
            name="Orchestration Skill",
            description="Orchestrates tasks across multiple specialized agents.",
            tags=["orchestration", "multi-agent"],
            examples=["Plan a night out and share it on social media.", "Find social insights and schedule an event."],
        )
        agent_card = AgentCard(
            name="Orchestrate Agent", # This name should be consistent across your system
            description="An agent that coordinates other specialized agents to fulfill complex user requests.",
            url=f"{PUBLIC_URL}",
            version="1.0.0",
            defaultInputModes=["text/plain"], # Adjust based on what it accepts
            defaultOutputModes=["text/plain"], # Adjust based on what it outputs
            capabilities=capabilities,
            skills=[skill],
        )

        # Create the A2AServer instance for the Orchestrate Agent
        server = A2AServer(
            agent_card=agent_card,
            task_manager=AgentTaskManager(agent=orchestrate_adk_agent),
            host=A2A_SERVER_HOST,
            port=A2A_SERVER_PORT,
        )

        logger.info(f"Attempting to start Orchestrate A2A server on {A2A_SERVER_HOST}:{A2A_SERVER_PORT} with Agent Card: {agent_card.name}")
        server.start()
    except Exception as e:
        logger.error(f"An error occurred during Orchestrate A2A server startup: {e}")
        exit(1)

if __name__ == "__main__":
    main()