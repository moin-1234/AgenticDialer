from dotenv import load_dotenv

from livekit import agents
from livekit.agents import AgentSession, Agent, RoomInputOptions
from livekit.plugins import (
    noise_cancellation,
)
from livekit.plugins import google
from prompts import ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS, SESSION_INSTRUCTION
import importlib
import sys
import csv
import os
import logging
from typing import Optional, Tuple, List, Dict
import subprocess
load_dotenv()

# Global logging: keep terminal clean
logging.basicConfig(level=logging.WARNING, format="%(message)s")

# Reduce noise from common modules
for noisy in [
    "livekit.agents",
    "livekit.rtc",
    "livekit",
    "google_genai",
    "google_genai.live",
    "asyncio",
    "opentelemetry",
    "httpx",
    "httpcore",
]:
    logging.getLogger(noisy).setLevel(logging.ERROR)

# Suppress unsupported option warning (truncate) from Google Realtime API
logging.getLogger("livekit.plugins.google").setLevel(logging.ERROR)


CAMPAIGNS = {
    # name: (module, agent_attr, session_attr)
    "Default (prompts)": ("prompts", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
    "SplashBI (prompts2)": ("prompts2", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
    "KonfHub (prompts3)": ("prompts3", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
    "Zoom Phone (prompts4)": ("prompts4", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS", "SESSION_INSTRUCTION"),
}

CAMPAIGN_OVERRIDE: tuple[str, str, str] | None = None


# ------------------------------
# Console styling (ANSI)
# ------------------------------
try:
    # Optional: helps colors render on Windows terminals
    from colorama import init as _colorama_init  # type: ignore
    _colorama_init(autoreset=True)
except Exception:
    pass

RESET = "\x1b[0m"
BOLD = "\x1b[1m"
DIM = "\x1b[2m"
CYAN = "\x1b[36m"
GREEN = "\x1b[32m"
YELLOW = "\x1b[33m"
MAGENTA = "\x1b[35m"
BLUE = "\x1b[34m"
GRAY = "\x1b[90m"

def _s(text: str, *styles: str) -> str:
    return f"{''.join(styles)}{text}{RESET}"


def _campaign_display_name(name: str) -> str:
    """Return a cleaned campaign name without parenthetical suffixes like ' (prompts2)'."""
    try:
        return name.split(" (")[0].strip()
    except Exception:
        return name


def _load_campaign_prompts(module_name: str | None = None,
                           agent_attr: str | None = None,
                           session_attr: str | None = None):
    """
    Load campaign-specific prompts from environment variables if provided.
    Env vars:
      - CAMPAIGN_PROMPT_MODULE: python module path (default: 'prompts')
      - CAMPAIGN_AGENT_NAME: constant name for agent instructions (default: 'ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS')
      - CAMPAIGN_SESSION_NAME: constant name for session instructions (default: 'SESSION_INSTRUCTION')

    Returns: (agent_instructions: str, session_instructions: str)
    """
    module_name = module_name or os.getenv("CAMPAIGN_PROMPT_MODULE", "prompts")
    agent_attr = agent_attr or os.getenv("CAMPAIGN_AGENT_NAME", "ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS")
    session_attr = session_attr or os.getenv("CAMPAIGN_SESSION_NAME", "SESSION_INSTRUCTION")

    agent_text = ENHANCED_DEMANDIFY_CALLER_INSTRUCTIONS
    session_text = SESSION_INSTRUCTION

    try:
        mod = importlib.import_module(module_name)
        agent_text = getattr(mod, agent_attr, agent_text)
        session_text = getattr(mod, session_attr, session_text)
    except Exception:
        # Fallback to defaults silently
        pass

    return agent_text, session_text


def _select_campaign_from_console() -> tuple[str, str, str] | None:
    """Present a simple console menu to select a campaign. Returns (module, agent_attr, session_attr)
    or None if user chooses to keep env defaults.
    """
    try:
        print()
        print(_s("┌──────────────────────────────────────────────┐", CYAN))
        print(_s("│ Select Campaign (press Enter for .env)       │", CYAN))
        print(_s("└──────────────────────────────────────────────┘", CYAN))
        for idx, name in enumerate(CAMPAIGNS.keys(), start=1):
            clean = _campaign_display_name(name)
            print(f"  {_s(f'[{idx}]', CYAN)} {_s(clean, BOLD)}")
        choice = input(_s("Enter number (or press Enter to skip): ", GREEN)).strip()
        if not choice:
            return None
        idx = int(choice)
        if idx < 1 or idx > len(CAMPAIGNS):
            print(_s("Invalid choice. Using .env settings.", YELLOW))
            return None
        name = list(CAMPAIGNS.keys())[idx - 1]
        return CAMPAIGNS[name]
    except Exception:
        # On any error, fall back to env
        return None


def _read_leads(leads_csv: str) -> List[Dict[str, str]]:
    """Read all leads from the CSV as a list of dicts. Returns empty list on error."""
    leads: List[Dict[str, str]] = []
    try:
        with open(leads_csv, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Normalize keys to expected set and ensure presence
                leads.append({
                    "prospect_name": row.get("prospect_name", "").strip(),
                    "resource_name": row.get("resource_name", "").strip(),
                    "job_title": row.get("job_title", "").strip(),
                    "company_name": row.get("company_name", "").strip(),
                    "email": row.get("email", "").strip(),
                    "phone": row.get("phone", "").strip(),
                    "timezone": row.get("timezone", "").strip(),
                })
    except Exception:
        pass
    return leads


def _select_prospect_from_console(leads: List[Dict[str, str]]) -> Optional[Dict[str, str]]:
    """Console menu to select a single prospect from the list. Returns the selected lead
    or None to use defaults/env.
    """
    if not leads:
        return None
    try:
        print()
        print(_s("┌─────────────────────────────────────────────────────────────┐", CYAN))
        print(_s("│ Select Prospect (Enter = use .env index or first row)       │", CYAN))
        print(_s("└─────────────────────────────────────────────────────────────┘", CYAN))
        for idx, ld in enumerate(leads, start=1):
            name = ld.get("prospect_name", "")
            comp = ld.get("company_name", "")
            print(f"  {_s(f'[{idx:02d}]', CYAN)} {_s(name, BOLD)} {_s('—', GRAY)} {comp}")
        choice = input(_s("Enter number (or press Enter to skip): ", GREEN)).strip()
        if not choice:
            return None
        i = int(choice)
        if i < 1 or i > len(leads):
            print(_s("Invalid choice. Using defaults.", YELLOW))
            return None
        return leads[i - 1]
    except Exception:
        return None


class Assistant(Agent):
    def __init__(self, instructions_text: str) -> None:
        super().__init__(
            instructions=instructions_text,
            llm=google.beta.realtime.RealtimeModel(
                voice="Leda",
                temperature=0.2,
            ),
            tools=[],
        )


async def entrypoint(ctx: agents.JobContext):
    session = AgentSession(
        
    )

    # Load leads from CSV and determine which prospect to use
    leads_csv = os.getenv("LEADS_CSV_PATH", os.path.join(os.path.dirname(__file__), "leads.csv"))
    all_leads = _read_leads(leads_csv)
    lead: Optional[Dict[str, str]] = None

    # Priority: env index > console selection > first row
    # Use environment variable LEAD_INDEX (1-based) if provided
    try:
        env_idx = os.getenv("LEAD_INDEX")
        if env_idx:
            i = int(env_idx) - 1
            if 0 <= i < len(all_leads):
                lead = all_leads[i]
    except Exception:
        pass
    # If no env index provided or invalid, offer console selection
    if lead is None:
        sel_lead = _select_prospect_from_console(all_leads)
        if sel_lead is not None:
            lead = sel_lead
    # Fallback to first row if still None
    if lead is None and all_leads:
        lead = all_leads[0]

    # Campaign selection:
    # - In child single-call runs, DO NOT prompt; rely on environment set by parent
    # - In parent interactive run, allow console campaign selection
    if os.getenv("RUN_SINGLE_CALL") == "1":
        selection = CAMPAIGN_OVERRIDE  # use env/defaults
    else:
        selection = CAMPAIGN_OVERRIDE or _select_campaign_from_console()
    if selection:
        mod_name, agent_attr, session_attr = selection
        agent_instructions_text, session_instructions_text = _load_campaign_prompts(
            module_name=mod_name,
            agent_attr=agent_attr,
            session_attr=session_attr,
        )
    else:
        # Use environment variables or defaults
        agent_instructions_text, session_instructions_text = _load_campaign_prompts()

    await session.start(
        room=ctx.room,
        agent=Assistant(agent_instructions_text),
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            video_enabled=False,
            noise_cancellation=noise_cancellation.BVCTelephony(),
        ),
    )

    await ctx.connect()

    # Prepare session instructions with lead details (campaign-specific)
    instructions = session_instructions_text
    if lead:
        # Replace bracket placeholders in the script when present
        def repl(text, placeholder, value):
            return text.replace(placeholder, value) if value else text

        instructions = repl(instructions, "[Prospect Name]", lead.get("prospect_name", "there"))
        instructions = repl(instructions, "[Resource Name]", lead.get("resource_name", "our team"))
        instructions = repl(instructions, "[Job Title]", lead.get("job_title", "your role"))
        instructions = repl(instructions, "[Company Name]", lead.get("company_name", "your company"))
        instructions = repl(instructions, "[____@abc.com]", lead.get("email", "email@domain.com"))

        # Also provide a structured preface the LLM can reference
        instructions = (
            f"Lead Context:\n"
            f"- Prospect Name: {lead.get('prospect_name','')}\n"
            f"- Job Title: {lead.get('job_title','')}\n"
            f"- Company: {lead.get('company_name','')}\n"
            f"- Email: {lead.get('email','')}\n"
            f"- Phone: {lead.get('phone','')}\n"
            f"- Timezone: {lead.get('timezone','')}\n"
            f"- Caller (Resource Name): {lead.get('resource_name','')}\n\n"
        ) + instructions

    await session.generate_reply(
        instructions=instructions,
    )


if __name__ == "__main__":
    # If invoked as a child single-call run, execute one session and exit
    if os.getenv("RUN_SINGLE_CALL") == "1":
        agents.cli.run_app(agents.WorkerOptions(entrypoint_fnc=entrypoint))
        sys.exit(0)

    # Parent controller loop (console-only): choose campaign once, then repeatedly choose prospects
    # Determine and set campaign env for child calls
    sel = CAMPAIGN_OVERRIDE or _select_campaign_from_console()
    campaign_env: dict[str, str] = {}
    if sel:
        mod_name, agent_attr, session_attr = sel
        campaign_env = {
            "CAMPAIGN_PROMPT_MODULE": mod_name,
            "CAMPAIGN_AGENT_NAME": agent_attr,
            "CAMPAIGN_SESSION_NAME": session_attr,
        }

    leads_csv_path = os.getenv("LEADS_CSV_PATH", os.path.join(os.path.dirname(__file__), "leads.csv"))
    leads_list = _read_leads(leads_csv_path)
    if not leads_list:
        print("No leads found. Please check leads.csv or LEADS_CSV_PATH.")
        sys.exit(1)

    pointer = 0  # default next index for Enter-to-next behavior
    page_size = 8
    current_page = 0

    # Determine selected campaign label for badge from selection/env
    selected_campaign_label = ""
    if sel:
        # Find the original key name that maps to sel to display a clean label
        for key, val in CAMPAIGNS.items():
            if val == sel:
                selected_campaign_label = _campaign_display_name(key)
                break

    while True:
        # Print menu
        print()
        # Selected campaign badge
        if selected_campaign_label:
            print(_s(f"[{selected_campaign_label}]", BOLD, BLUE))

        total_pages = max(1, (len(leads_list) + page_size - 1) // page_size)
        current_page = max(0, min(current_page, total_pages - 1))
        start = current_page * page_size
        end = min(start + page_size, len(leads_list))

        print(_s(f"╔════════════════════════ Prospect Selection (Page {current_page+1}/{total_pages}) ════════════════════════╗", CYAN))
        for idx_global in range(start, end):
            ld = leads_list[idx_global]
            name = ld.get("prospect_name", "")
            comp = ld.get("company_name", "")
            idx_display = (idx_global - start) + 1
            marker = _s("← next", GREEN) if idx_global == pointer else ""
            print(f"  {_s(f'[{idx_display:02d}]', CYAN)} {_s(name, BOLD)} {_s('—', GRAY)} {comp} {marker}")
        print(_s("╚══════════════════════════════════════════════════════════════════════════════════════════════════════════╝", CYAN))
        print(_s("Enter = NEXT • Number = select on this page • N = next page • P = prev page • 'q' = quit", DIM))
        choice = input(_s("Your choice: ", GREEN)).strip().lower()

        if choice == "q":
            print(_s("Exiting.", YELLOW))
            break

        # Pagination controls
        if choice == "n":
            if current_page < total_pages - 1:
                current_page += 1
            continue
        if choice == "p":
            if current_page > 0:
                current_page -= 1
            continue

        if choice == "":
            call_index = pointer
        else:
            try:
                num = int(choice)
                # Map page-local number to global index
                if 1 <= num <= (end - start):
                    call_index = start + (num - 1)
                else:
                    print(_s("Invalid number. Try again.", YELLOW))
                    continue
            except ValueError:
                print(_s("Invalid input. Try again.", YELLOW))
                continue

        # Prepare env and run child single-call process
        child_env = os.environ.copy()
        child_env.update(campaign_env)
        child_env["LEAD_INDEX"] = str(call_index + 1)
        child_env["RUN_SINGLE_CALL"] = "1"

        print(_s(f"\n▶ Starting call for lead #{call_index + 1}... (returning to menu when finished)\n", MAGENTA))
        # Use 'console' subcommand so audio I/O (Ctrl+B to toggle Audio/Text) is available
        try:
            subprocess.run([sys.executable, __file__, "console"], env=child_env, check=False)
        except KeyboardInterrupt:
            print(_s("\nCall interrupted. Returning to menu...\n", YELLOW))

        # Advance pointer when using Enter (next) or when the called index equals pointer
        if call_index == pointer:
            pointer = min(pointer + 1, len(leads_list) - 1)
        # If pointer moved out of current page, advance page automatically
        if not (start <= pointer < end):
            if pointer >= end and current_page < total_pages - 1:
                current_page += 1

    sys.exit(0)