import os
import time
import logging
import asyncio
import sqlite3
from datetime import datetime
from dotenv import load_dotenv
import requests
from telegram_bot import get_users_for_daily_checkin, curate_question

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_scheduler.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

# Get bot token from environment
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
if not BOT_TOKEN:
    logger.error("TELEGRAM_BOT_TOKEN not set in environment")
    raise ValueError("Bot token not found in environment variables")

def get_db_connection():
    """Get a connection to the SQLite database"""
    db_path = os.path.join("database", "echomind.sqlite")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn

def send_telegram_message(chat_id, text, reply_markup=None):
    """Send a message to a Telegram chat"""
    if not BOT_TOKEN:
        logger.error("Bot token not available")
        return {"ok": False, "error": "Bot token not available"}
    
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    
    if reply_markup:
        payload["reply_markup"] = reply_markup
    
    try:
        response = requests.post(url, json=payload)
        logger.info(f"Message sent to {chat_id}, status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Failed to send message: {response.text}")
            return {"ok": False, "error": response.text}
        
        # SAVE QUESTION TO MESSAGES DB WITH RESPONSE = "[Awaiting response]"
        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return {"ok": False, "error": str(e)}

def get_inline_keyboard(buttons):
    """Create an inline keyboard markup"""
    return {"inline_keyboard": buttons}

def create_session_for_user(user_id):
    """Create a new session for today's check-in"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if we already have a session for today
        today_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(
            "SELECT Session_ID FROM Session_Scores WHERE User_ID = ? AND Date = ?", 
            (user_id, today_date)
        )
        
        session = cursor.fetchone()
        if session:
            session_id = session['Session_ID']
            logger.info(f"Using existing session {session_id} for user {user_id}")
        else:
            # Create a new session for today
            cursor.execute(
                "INSERT INTO Session_Scores (User_ID, Date, Sentiment_Score) VALUES (?, ?, 0.5)", 
                (user_id, today_date)
            )
            session_id = cursor.lastrowid
            logger.info(f"Created new session {session_id} for user {user_id}")
        
        conn.commit()
        conn.close()
        return session_id
    except Exception as e:
        logger.error(f"Error creating session: {e}")
        return None

async def send_daily_check_ins():
    """Send daily check-ins to patients based on their preferred time"""
    # Get current time (UTC)
    now = datetime.now()
    current_hour = now.hour
    current_minute = now.minute
    
    # Round minute to the nearest 5 to reduce database queries
    # current_minute = (current_minute // 5) * 5
    
    logger.info(f"Checking for scheduled check-ins at {current_hour:02d}:{current_minute:02d}")
    
    # Get users who should receive check-ins now
    users = get_users_for_daily_checkin(current_hour, current_minute)
    
    if users:
        logger.info(f"Found {len(users)} users for check-in")
        
        for user in users:
            # Use the imported function from telegram_bot.py
            curate_question(
                chat_id=user['chat_id'],
                user_id=user['User_ID']
            )
            
            # Add a small delay between sends to avoid rate limiting
            await asyncio.sleep(0.5)
    else:
        logger.info("No users scheduled for check-in at this time")

async def main():
    """Main scheduler function"""
    logger.info("Starting EchoMind Telegram check-in scheduler")
    
    try:
        while True:
            await send_daily_check_ins()
            # Run every minute
            await asyncio.sleep(60)
    except KeyboardInterrupt:
        logger.info("Scheduler stopped by user")
    except Exception as e:
        logger.error(f"Error in scheduler: {str(e)}")
        raise

if __name__ == "__main__":
    asyncio.run(main())