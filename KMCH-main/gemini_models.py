"""
🔍 Gemini Model Checker & Tester
Run this to find and test which Gemini models work with your API key
"""

import os
import sys
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

print("=" * 70)
print("🔍 GEMINI MODEL CHECKER & TESTER")
print("=" * 70)

# Step 1: Check if API key exists
api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    print("\n❌ ERROR: GEMINI_API_KEY not found!")
    print("Please add it to your .env file:")
    print("   GEMINI_API_KEY=your_api_key_here")
    sys.exit(1)

print(f"\n✅ API Key found: {api_key[:15]}...{api_key[-5:]}")

# Step 2: Import and configure
try:
    import google.generativeai as genai
    print("✅ google.generativeai module imported successfully")
except ImportError:
    print("\n❌ ERROR: google-generativeai not installed!")
    print("Install it with: pip install google-generativeai")
    sys.exit(1)

genai.configure(api_key=api_key)
print("✅ Gemini configured with API key")

# Step 3: List all available models
print("\n" + "=" * 70)
print("📋 AVAILABLE MODELS (that support generateContent)")
print("=" * 70)

available_models = []
try:
    for model in genai.list_models():
        if 'generateContent' in model.supported_generation_methods:
            available_models.append(model.name)
            print(f"\n✅ Model: {model.name}")
            print(f"   Display Name: {model.display_name}")
            print(f"   Description: {model.description[:80]}...")
except Exception as e:
    print(f"\n❌ Error listing models: {e}")
    print("\nTrying common model names anyway...")
    available_models = [
        'models/gemini-1.5-flash-latest',
        'models/gemini-1.5-pro-latest',
        'models/gemini-pro',
        'gemini-1.5-flash-latest',
        'gemini-1.5-pro-latest',
        'gemini-pro'
    ]

# Step 4: Test each model with a simple prompt
print("\n" + "=" * 70)
print("🧪 TESTING MODELS WITH SAMPLE MEDICAL TRANSCRIPT")
print("=" * 70)

test_transcript = """
Patient presents with fever of 102°F, sore throat, and body aches for 3 days.
Physical examination shows red throat with white patches.
Diagnosis: Probable streptococcal pharyngitis.
Treatment: Antibiotics prescribed, throat culture ordered.
Follow-up in 1 week if symptoms persist.
"""

test_prompt = f"""
Extract the medical condition from this transcript in JSON format:
{test_transcript}

Return only JSON like: {{"medical_condition": "condition name"}}
"""

working_models = []

for model_name in available_models:
    print(f"\n🔄 Testing: {model_name}")
    try:
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(test_prompt)
        
        if response and response.text:
            print(f"   ✅ SUCCESS! Response received:")
            print(f"   {response.text[:100]}...")
            working_models.append(model_name)
        else:
            print(f"   ⚠️ Model responded but no text returned")
    except Exception as e:
        print(f"   ❌ FAILED: {str(e)[:80]}")

# Step 5: Summary and recommendations
print("\n" + "=" * 70)
print("📊 SUMMARY")
print("=" * 70)

if working_models:
    print(f"\n✅ {len(working_models)} working model(s) found:")
    for idx, model_name in enumerate(working_models, 1):
        print(f"   {idx}. {model_name}")
    
    print("\n🎯 RECOMMENDED MODEL TO USE:")
    recommended = working_models[0]
    print(f"   {recommended}")
    
    print("\n📝 Update your gemini_service.py with:")
    print("-" * 70)
    print(f"self.model = genai.GenerativeModel('{recommended}')")
    print("-" * 70)
    
else:
    print("\n❌ No working models found!")
    print("\nPossible issues:")
    print("   1. API key might be invalid")
    print("   2. API key might not have access to Gemini API")
    print("   3. Network/firewall issues")
    print("\nTry:")
    print("   1. Generate a new API key at: https://aistudio.google.com/app/apikey")
    print("   2. Make sure Gemini API is enabled for your project")

print("\n" + "=" * 70)
print("✅ Test complete!")
print("=" * 70)