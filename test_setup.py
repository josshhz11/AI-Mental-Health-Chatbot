import os
import subprocess
import time
import sys

def check_environment():
    """Check if environment is properly set up"""
    print("\n=== Checking Environment ===")
    
    # Check .env file exists
    env_file = os.path.join(os.getcwd(), ".env")
    if not os.path.exists(env_file):
        print("❌ .env file not found. Creating template...")
        with open(env_file, "w") as f:
            f.write("SECRET_KEY=generate_a_secure_key_here\n")
            f.write("TELEGRAM_BOT_TOKEN=your_bot_token_here\n")
            f.write("WEBHOOK_URL=https://your-domain.com/telegram-webhook\n")
            f.write("OPENAI_API_KEY=your_openai_api_key_here\n")
        print("✅ .env template created. Please fill in the required values.")
    else:
        print("✅ .env file found")
        
        # Check required environment variables
        with open(env_file, "r") as f:
            env_contents = f.read()
            
        required_vars = ["SECRET_KEY", "TELEGRAM_BOT_TOKEN", "WEBHOOK_URL"]
        for var in required_vars:
            if var not in env_contents or f"{var}=your_{var.lower()}_here" in env_contents:
                print(f"❌ {var} not properly configured in .env file")
            else:
                print(f"✅ {var} configured")
    
    # Check database directory
    db_dir = os.path.join(os.getcwd(), "database")
    if not os.path.exists(db_dir):
        print("❌ database directory not found")
    else:
        print("✅ database directory found")
        
        # Check database file
        db_file = os.path.join(db_dir, "echomind.sqlite")
        if not os.path.exists(db_file):
            print("ℹ️ Database file not found. It will be created on first run.")
        else:
            print("✅ Database file found")
    
    # Check templates directory
    templates_dir = os.path.join(os.getcwd(), "templates")
    if not os.path.exists(templates_dir):
        print("❌ templates directory not found")
    else:
        print("✅ templates directory found")
    
    # Check static directory
    static_dir = os.path.join(os.getcwd(), "static")
    if not os.path.exists(static_dir):
        print("❌ static directory not found")
    else:
        print("✅ static directory found")
    
    print("\nEnvironment check complete.")

def check_dependencies():
    """Check if all required dependencies are installed"""
    print("\n=== Checking Dependencies ===")
    
    try:
        # Check if requirements.txt exists
        requirements_file = os.path.join(os.getcwd(), "requirements.txt")
        if not os.path.exists(requirements_file):
            print("❌ requirements.txt not found")
            return
            
        print("✅ requirements.txt found")
        
        # Try to import key libraries
        dependencies = [
            "fastapi", "uvicorn", "jinja2", "requests", "python-dotenv", 
            "pyjwt", "passlib", "schedule", "cryptography", "sqlite3"
        ]
        
        missing = []
        for dep in dependencies:
            try:
                if dep == "sqlite3":
                    import sqlite3
                else:
                    __import__(dep)
                print(f"✅ {dep} installed")
            except ImportError:
                missing.append(dep)
                print(f"❌ {dep} not installed")
        
        if missing:
            print(f"\nMissing dependencies: {', '.join(missing)}")
            install = input("Do you want to install missing dependencies? (y/n): ")
            if install.lower() == "y":
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
                print("\nDependencies installed.")
            else:
                print("\nPlease install the missing dependencies manually.")
        else:
            print("\nAll dependencies are installed.")
    except Exception as e:
        print(f"Error checking dependencies: {e}")

def test_components():
    """Test core components of the application"""
    print("\n=== Testing Components ===")
    
    # Test database connection
    print("\nTesting database connection...")
    try:
        from database.db import Database
        db = Database()
        conn = db.get_connection()
        if conn:
            print("✅ Database connection successful")
            conn.close()
        else:
            print("❌ Database connection failed")
    except Exception as e:
        print(f"❌ Database test failed: {e}")
    
    # Test telegram bot token
    print("\nTesting Telegram bot token...")
    try:
        import requests
        from dotenv import load_dotenv
        load_dotenv()
        
        bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
        if not bot_token:
            print("❌ TELEGRAM_BOT_TOKEN not found in environment")
        else:
            url = f"https://api.telegram.org/bot{bot_token}/getMe"
            response = requests.get(url)
            
            if response.status_code == 200:
                result = response.json()
                if result.get("ok"):
                    bot_info = result.get("result", {})
                    print(f"✅ Telegram bot token valid. Bot name: {bot_info.get('first_name')}")
                else:
                    print(f"❌ Telegram bot token invalid: {result.get('description')}")
            else:
                print(f"❌ Telegram API request failed: {response.status_code}")
    except Exception as e:
        print(f"❌ Telegram bot test failed: {e}")
    
    # Test webhook URL
    print("\nTesting webhook URL...")
    try:
        from dotenv import load_dotenv
        import requests
        load_dotenv()
        
        webhook_url = os.environ.get("WEBHOOK_URL")
        if not webhook_url:
            print("❌ WEBHOOK_URL not found in environment")
        else:
            print(f"Webhook URL: {webhook_url}")
            
            # Check if URL is reachable
            try:
                response = requests.head(webhook_url, timeout=5)
                print(f"ℹ️ Webhook URL status: {response.status_code}")
                if response.status_code == 404:
                    print("This is normal if the server isn't running yet.")
            except requests.exceptions.ConnectionError:
                print("ℹ️ Webhook URL not reachable. This is normal if using ngrok and it's not running.")
            except Exception as e:
                print(f"ℹ️ Webhook test: {str(e)}")
    except Exception as e:
        print(f"❌ Webhook URL test failed: {e}")

def main():
    print("EchoMind Setup and Test Utility")
    print("===============================")
    
    # Check environment
    check_environment()
    
    # Check dependencies
    check_dependencies()
    
    # Test components
    test_components()
    
    print("\n=== Setup Instructions ===")
    print("1. Fill in all required values in the .env file")
    print("2. Start your FastAPI application: python main.py")
    print("3. In a separate terminal, start ngrok: ngrok http 8000 --region ap")
    print("4. Update WEBHOOK_URL in .env with the ngrok URL")
    print("5. Set up your webhook: python webhook_setup.py")
    print("6. Start the scheduler: python telegram_scheduler.py")
    print("   (Or use python run.py to start both components)")
    print("\n=== Happy Testing! ===")

if __name__ == "__main__":
    main()