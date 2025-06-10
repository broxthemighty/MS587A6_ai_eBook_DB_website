#generate_ai_ebooks.py

import os
import logging
from dotenv import load_dotenv
import google.generativeai as genai

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

# Load environment variables
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise EnvironmentError("GEMINI_API_KEY not found in environment.")

# Configure Gemini API client
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

# Constants
THEMES = [
    "Space Adventure",
    "Jungle Mystery",
    "Ancient Egypt",
    "Robot Rebellion",
    "Underwater City"
]
OUTPUT_DIR = "ebooks"
os.makedirs(OUTPUT_DIR, exist_ok=True)


def generate_unique_filename(base: str, extension: str, directory: str) -> str:
    """
    Generates a unique filename in the target directory to avoid overwrites.
    """
    counter = 0
    candidate = f"{base}.{extension}"
    while os.path.exists(os.path.join(directory, candidate)):
        counter += 1
        candidate = f"{base}_{counter}.{extension}"
    return candidate


def build_prompt(theme: str) -> str:
    """
    Constructs a prompt string for Gemini content generation.
    """
    return f"Write a creative short story (~500 words) titled '{theme}'. It should be imaginative and suitable for general audiences."


def generate_story(theme: str, index: int) -> str:
    """
    Handles the story generation and file writing for a given theme.
    """
    logging.info(f"[{index}] Generating story for theme: '{theme}'")
    prompt = build_prompt(theme)

    try:
        response = model.generate_content(prompt)
        story = response.text.strip()

        base_filename = f"book{index}_{theme.replace(' ', '_').lower()}"
        final_filename = generate_unique_filename(base_filename, "txt", OUTPUT_DIR)
        filepath = os.path.join(OUTPUT_DIR, final_filename)

        with open(filepath, "w", encoding="utf-8") as file:
            file.write(story)

        logging.info(f"✅ Story saved: {final_filename}")
        return final_filename

    except Exception as e:
        logging.error(f"❌ Error generating story for '{theme}': {e}")
        return ""


def main():
    logging.info("📘 Starting AI eBook generation...")
    for i, theme in enumerate(THEMES, start=1):
        generate_story(theme, i)
    logging.info(f"📚 All stories generated in '{OUTPUT_DIR}/'")


if __name__ == "__main__":
    main()
