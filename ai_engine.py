import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from supabase import create_client, Client

# Credentials load from .env sitting next to this module. Never hardcode them here.
load_dotenv(Path(__file__).with_name(".env"))


def require_env(name: str) -> str:
    value = (os.getenv(name) or "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set. Add it to C:\\growmated-engine\\.env "
            f"or export it in your shell before running."
        )
    return value


NVIDIA_API_KEY = require_env("NVIDIA_API_KEY")
SUPABASE_URL = require_env("SUPABASE_URL")
SUPABASE_KEY = require_env("SUPABASE_KEY")

# Initialize NVIDIA OpenAI Client
nvidia_client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key=NVIDIA_API_KEY
)

# Initialize Supabase Client
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# Both meta/llama-3.3-70b-instruct and moonshotai/kimi-k2.6 are listed in the NVIDIA catalog but
# are NOT provisioned for this account (3.3 hangs until timeout; kimi returns 404). The models
# below are verified working. Override via env once the account is upgraded.
PRIMARY_MODEL = os.getenv("GROWMATED_MODEL", "meta/llama-3.1-70b-instruct")
FALLBACK_MODEL = os.getenv("GROWMATED_FALLBACK_MODEL", "meta/llama-3.1-8b-instruct")

GROW_MATED_VALUE_PROP = """
Growmated.com helps businesses scale their client acquisition through automated, high-converting outreach and organic lead funnels.
We focus on providing value first, addressing high-friction growth bottlenecks, and booking high-intent sales calls.
"""

def save_prospect_and_message(name, platform, raw_input, generated_msg, msg_type, company="Unknown", industry="Unknown"):
    prospect_data = {
        "prospect_name": name,
        "company_name": company,
        "platform": platform,
        "industry": industry,
        "status": "New"
    }
    prospect_res = supabase.table("prospects").insert(prospect_data).execute()
    prospect_id = prospect_res.data[0]["id"]

    msg_data = {
        "prospect_id": prospect_id,
        "message_type": msg_type,
        "raw_input_data": raw_input,
        "generated_content": generated_msg
    }
    supabase.table("outreach_messages").insert(msg_data).execute()
    return prospect_id

def generate_linkedin_outreach(prospect_name, profile_text, industry="General"):
    system_prompt = f"""
    You are Usman, a growth partner at Growmated.com.
    Company Context: {GROW_MATED_VALUE_PROP}
    Goal: Write a concise, non-salesy LinkedIn direct message (under 120 words).
    - Focus on a specific insight or gap based on their bio/profile text.
    - Offer a quick win or simple piece of advice.
    - End with a low-friction question.
    """
    
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Prospect Name: {prospect_name}\nProfile Data: {profile_text}"}
    ]

    print("[1/3] Contacting NVIDIA AI Model...")
    try:
        response = nvidia_client.chat.completions.create(
            model=PRIMARY_MODEL,
            messages=messages,
            temperature=0.7
        )
        output_message = response.choices[0].message.content
        print("[2/3] AI Response Generated successfully!")
    except Exception as e:
        print(f"\n[Warning] Primary model '{PRIMARY_MODEL}' failed: {e}")
        print(f"Switching to fallback model '{FALLBACK_MODEL}'...")
        response = nvidia_client.chat.completions.create(
            model=FALLBACK_MODEL,
            messages=messages,
            temperature=0.7
        )
        output_message = response.choices[0].message.content

    print("[3/3] Saving prospect & message to Supabase...")
    save_prospect_and_message(prospect_name, "linkedin", profile_text, output_message, "linkedin_pitch", industry=industry)
    print("[Success] Data stored in database!")
    return output_message

if __name__ == "__main__":
    print("--- Testing Growmated AI Engine ---")
    bio = "Founder of a B2B SaaS startup struggling to get qualified sales calls from cold email."
    result = generate_linkedin_outreach("Test Prospect", bio, "SaaS")
    print("\nGenerated Output:\n")
    print(result)