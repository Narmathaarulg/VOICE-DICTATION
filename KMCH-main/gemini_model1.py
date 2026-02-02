import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()

# Configure API
api_key = os.getenv("GEMINI_API_KEY")

if not api_key:
    print("\n❌ ERROR: GEMINI_API_KEY not found in .env file!")
    print("💡 Add this to your .env file:")
    print("   GEMINI_API_KEY=your_api_key_here")
    print("\n   Get your key from: https://makersuite.google.com/app/apikey\n")
    exit(1)

genai.configure(api_key=api_key)

print("\n" + "="*60)
print("🔍 Checking Available Gemini Models")
print("="*60 + "\n")

# List all available models
try:
    models = genai.list_models()
    
    print("✅ Available models for your API key:\n")
    
    generative_models = []
    for model in models:
        # Only show generative models that support generateContent
        if 'generateContent' in model.supported_generation_methods:
            generative_models.append(model)
            print(f"   • {model.name}")
            print(f"     Description: {model.description[:80]}...")
            print(f"     Display Name: {model.display_name}")
            print()
    
    if not generative_models:
        print("⚠️  No generative models found for this API key.")
        print("💡 Make sure your API key is valid and has the correct permissions.\n")
    else:
        print("="*60)
        print(f"\n✅ Found {len(generative_models)} available model(s)")
        print("\n💡 RECOMMENDATION: Use this in your app:")
        print(f"   model = genai.GenerativeModel('{generative_models[0].name}')")
        print("\n   Copy the line above into your initialize_gemini() function\n")
    
except Exception as e:
    print(f"❌ Error: {e}")
    print("\n💡 Troubleshooting:")
    print("   1. Check your GEMINI_API_KEY is correct in .env file")
    print("   2. Get a new key from: https://makersuite.google.com/app/apikey")
    print("   3. Make sure there are no extra spaces or quotes in .env")
    print("\n   Your .env should look like:")
    print("   GEMINI_API_KEY=AIza...")
    print()