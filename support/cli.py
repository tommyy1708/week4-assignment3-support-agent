"""Bare CLI for stage 3: log in, then chat with the support agent. Stage 4 replaces the loop
body with the pipeline's event stream."""

import asyncio
import getpass

from dotenv import load_dotenv
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.genai import types
from toolbox_core import ToolboxClient

from support.agent import TOOLBOX_URL, build_agent, login

APP_NAME = "support_desk"


async def main() -> None:
    load_dotenv()
    async with ToolboxClient(TOOLBOX_URL) as client:
        email = input("Email: ").strip()
        customer = await login(client, email, getpass.getpass("Password: "))
        if customer is None:
            print("Invalid email or password.")
            return
        print(f"Logged in as {customer['full_name']}. Type quit to leave.")

        agent = await build_agent(client, customer)
        sessions = InMemorySessionService()
        session = await sessions.create_session(app_name=APP_NAME, user_id=customer["email"])
        runner = Runner(app_name=APP_NAME, agent=agent, session_service=sessions)

        while True:
            message = input("You: ").strip()
            if message.lower() in {"quit", "exit", "q"}:
                break
            if not message:
                continue
            content = types.Content(role="user", parts=[types.Part(text=message)])
            try:
                async for event in runner.run_async(
                    user_id=customer["email"], session_id=session.id, new_message=content
                ):
                    if event.is_final_response() and event.content and event.content.parts:
                        print("Agent:", "".join(p.text or "" for p in event.content.parts))
            except Exception as e:  # say what failed and keep the session; never pretend to answer
                print(f"Error: {type(e).__name__}: {e}")


if __name__ == "__main__":
    asyncio.run(main())
