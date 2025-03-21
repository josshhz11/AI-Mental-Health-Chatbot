import requests
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

def register_webhook():
    """Register your webhook with Telegram"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    webhook_url = os.environ.get("WEBHOOK_URL")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set in environment variables")
        return False
        
    if not webhook_url:
        print("Error: WEBHOOK_URL not set in environment variables")
        print("Example: https://your-domain.com/telegram-webhook")
        return False
    
    # Set the webhook
    set_webhook_url = f"https://api.telegram.org/bot{bot_token}/setWebhook"
    
    payload = {
        "url": webhook_url,
        "allowed_updates": ["message"]
    }
    
    try:
        response = requests.post(set_webhook_url, json=payload)
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                print("Webhook registered successfully!")
                print(f"Description: {result.get('description')}")
                return True
            else:
                print(f"Failed to register webhook: {result.get('description')}")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(response.text)
        return False
    except Exception as e:
        print(f"Error registering webhook: {e}")
        return False

def get_webhook_info():
    """Get information about the current webhook"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set in environment variables")
        return False
        
    # Get webhook info
    info_url = f"https://api.telegram.org/bot{bot_token}/getWebhookInfo"
    
    try:
        response = requests.get(info_url)
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                info = result.get("result", {})
                print("\nCurrent Webhook Info:")
                print(f"URL: {info.get('url', 'Not set')}")
                print(f"Has custom certificate: {info.get('has_custom_certificate', False)}")
                print(f"Pending update count: {info.get('pending_update_count', 0)}")
                
                if "last_error_date" in info:
                    from datetime import datetime
                    error_time = datetime.fromtimestamp(info["last_error_date"])
                    print(f"Last error: {info.get('last_error_message', 'Unknown')} at {error_time}")
                
                print(f"Max connections: {info.get('max_connections', 'Unknown')}")
                return True
            else:
                print(f"Failed to get webhook info: {result.get('description')}")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(response.text)
        return False
    except Exception as e:
        print(f"Error getting webhook info: {e}")
        return False

def delete_webhook():
    """Delete the current webhook"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set in environment variables")
        return False
        
    # Delete webhook
    delete_url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook"
    
    try:
        response = requests.get(delete_url)
        if response.status_code == 200:
            result = response.json()
            if result.get("ok"):
                print("Webhook deleted successfully!")
                return True
            else:
                print(f"Failed to delete webhook: {result.get('description')}")
        else:
            print(f"Error: HTTP {response.status_code}")
            print(response.text)
        return False
    except Exception as e:
        print(f"Error deleting webhook: {e}")
        return False

if __name__ == "__main__":
    # Show options menu
    print("Telegram Webhook Setup")
    print("1. Register webhook")
    print("2. Get webhook info")
    print("3. Delete webhook")
    print("4. Exit")
    
    choice = input("Enter your choice (1-4): ")
    
    if choice == "1":
        # Ask for webhook URL if not in environment
        if not os.environ.get("WEBHOOK_URL"):
            webhook_url = input("Enter your webhook URL (e.g., https://your-domain.com/telegram-webhook): ")
            os.environ["WEBHOOK_URL"] = webhook_url
        
        register_webhook()
    elif choice == "2":
        get_webhook_info()
    elif choice == "3":
        delete_webhook()
    else:
        print("Exiting...")