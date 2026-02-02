from pymongo import MongoClient
import os
from dotenv import load_dotenv

load_dotenv()

mongo_uri = os.getenv("MONGO_URI")
db_name = os.getenv("DB_NAME")

client = MongoClient(mongo_uri)
db = client[db_name]

print("Connected DB Name:", db.name)
print("Databases:", client.list_database_names())
