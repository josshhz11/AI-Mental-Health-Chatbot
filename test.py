import sqlite3
import os
from telegram_bot import curate_question

def trigger_manual_checkin(user_id):
    """
    Manually trigger a check-in for a specific user
    """
    print(f"Triggering manual check-in for user ID {user_id}")
    
    # Get the user's chat_id
    db_path = os.path.join("database", "echomind.sqlite")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT User_ID, Name, chat_id FROM User WHERE User_ID = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user or not user['chat_id']:
        print(f"Error: User ID {user_id} not found or has no chat_id")
        return
    
    print(f"Sending check-in to {user['Name']} (chat_id: {user['chat_id']})")
    
    # Send the check-in
    result = curate_question(
        chat_id=user['chat_id'],
        user_id=user['User_ID']
    )
    
    print(f"Result: {result}")

if __name__ == "__main__":
    # Replace with actual user ID
    user_id = 2  # Update with your user's ID
    trigger_manual_checkin(user_id)