import sqlite3
import os
import requests
from dotenv import load_dotenv
from datetime import datetime
import time

# Load environment variables
load_dotenv()

def get_db_connection():
    """Connect to the database"""
    conn = sqlite3.connect(os.path.join("database", "echomind.sqlite"))
    conn.row_factory = sqlite3.Row
    return conn

def send_test_message(chat_id, message):
    """Send a test message to a chat"""
    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not bot_token:
        print("Error: TELEGRAM_BOT_TOKEN not set")
        return False
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    
    try:
        response = requests.post(url, json=payload)
        if response.status_code == 200:
            print(f"Message sent successfully to chat_id {chat_id}")
            return True
        else:
            print(f"Error sending message: {response.text}")
            return False
    except Exception as e:
        print(f"Error: {e}")
        return False

def test_scheduler_logic():
    """Test the scheduler's logic for finding users with matching chat times"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get all patients with chat times
        cursor.execute("""
            SELECT u.User_ID, u.Name, u.chat_id, p.timezone, p.chat_time
            FROM User u
            JOIN Patient p ON u.User_ID = p.Patient_ID
            WHERE p.chat_time IS NOT NULL
        """)
        
        patients = cursor.fetchall()
        
        if not patients:
            print("No patients with chat times found")
            return
        
        for patient in patients:
            print(f"Patient: {patient['Name']}")
            print(f"  chat_id: {patient['chat_id']}")
            print(f"  timezone: {patient['timezone']}")
            print(f"  chat_time: {patient['chat_time']}")
            
            # Show next check-in time
            if patient['chat_time']:
                try:
                    chat_hour, chat_minute = map(int, patient['chat_time'].split(':'))
                    current_hour = datetime.now().hour
                    current_minute = datetime.now().minute
                    
                    next_check_time = f"Today at {patient['chat_time']}" if (
                        chat_hour > current_hour or 
                        (chat_hour == current_hour and chat_minute > current_minute)
                    ) else f"Tomorrow at {patient['chat_time']}"
                    
                    print(f"  Next scheduled check-in: {next_check_time}")
                except:
                    print(f"  Invalid chat time format: {patient['chat_time']}")
            print()
    
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def send_test_messages_to_patients():
    """Send test messages to all patients with chat_id"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.User_ID, u.Name, u.chat_id
            FROM User u
            JOIN Patient p ON u.User_ID = p.Patient_ID
            WHERE u.chat_id IS NOT NULL
        """)
        
        patients = cursor.fetchall()
        
        if not patients:
            print("No patients with chat_id found")
            return
        
        message = input("Enter message to send to all patients: ")
        
        for patient in patients:
            print(f"Sending to {patient['Name']} (chat_id: {patient['chat_id']})...")
            success = send_test_message(patient['chat_id'], message)
            
            if success:
                print(f"✓ Message sent to {patient['Name']}")
            else:
                print(f"✗ Failed to send message to {patient['Name']}")
                
            # Sleep briefly to prevent rate limiting
            time.sleep(0.5)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def send_test_alerts_to_doctors():
    """Send test alert messages to all doctors with chat_id"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT u.User_ID, u.Name, u.chat_id
            FROM User u
            WHERE u.Role = 'Doctor' AND u.chat_id IS NOT NULL
        """)
        
        doctors = cursor.fetchall()
        
        if not doctors:
            print("No doctors with chat_id found")
            return
        
        patient_name = input("Enter patient name for test alert: ")
        score = input("Enter sentiment score (0-100): ")
        
        for doctor in doctors:
            alert_message = f"🚨 *PATIENT ALERT*\n\nPatient: *{patient_name}*\nSentiment Score: *{score}*\n\n_This is a test alert._"
            
            print(f"Sending to Dr. {doctor['Name']} (chat_id: {doctor['chat_id']})...")
            success = send_test_message(doctor['chat_id'], alert_message)
            
            if success:
                print(f"✓ Alert sent to Dr. {doctor['Name']}")
            else:
                print(f"✗ Failed to send alert to Dr. {doctor['Name']}")
                
            # Sleep briefly to prevent rate limiting
            time.sleep(0.5)
        
    except Exception as e:
        print(f"Error: {e}")
    finally:
        if 'conn' in locals():
            conn.close()

def main():
    """Main test function"""
    print("EchoMind Telegram Bot Test Script")
    print("--------------------------------")
    
    # Menu
    print("1. Test scheduler logic")
    print("2. Send test message to a specific chat_id")
    print("3. Send test messages to all connected patients")
    print("4. Send test alert to all connected doctors")
    print("5. Exit")
    
    choice = input("Enter choice (1-5): ")
    
    if choice == "1":
        test_scheduler_logic()
    
    elif choice == "2":
        chat_id = input("Enter chat_id: ")
        message = input("Enter message: ")
        send_test_message(chat_id, message)
    
    elif choice == "3":
        send_test_messages_to_patients()
    
    elif choice == "4":
        send_test_alerts_to_doctors()
    
    elif choice == "5":
        print("Exiting...")
        return
    
    input("\nPress Enter to continue...")
    main()  # Return to menu

if __name__ == "__main__":
    main()