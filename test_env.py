from pathlib import Path
from dotenv import load_dotenv
import os

load_dotenv(Path(__file__).resolve().parent / ".env", override=True)
print("DATA_DIR =", os.getenv("DATA_DIR"))
