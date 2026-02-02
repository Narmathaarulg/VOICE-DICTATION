from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri = os.getenv("MONGO_URI")

client = MongoClient(mongo_uri)

# Force DB creation
db = client["casmed_db"]

# Force collection creation
collection = db["system_logs"]

collection.insert_one({
    "system": "CAS-Medical",
    "module": "Clinical Voice Dictation",
    "status": "MongoDB Connected Successfully",
    "created_by": "system",
    "env": "production"
})

print("✅ casmed_db created and data inserted")
