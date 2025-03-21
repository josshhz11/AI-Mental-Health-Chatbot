# Add these imports at the top of the file
import os
import sqlite3
import logging
import random
import string
import requests
import json
import time
import traceback
import importlib
from openai import OpenAI
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("telegram_bot.log"),
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

# Constants for mental health questions
DEFAULT_QUESTIONS = [
    "How are you feeling today?",
    "How would you rate your overall mood today on a scale of 1-10?",
    "Have you had any thoughts of self-harm or suicide?",
    "Have you been taking your medicine on time?"
]

def get_db_connection():
    """Get a connection to the SQLite database"""
    conn = sqlite3.connect(os.path.join("database", "echomind.sqlite"))
    conn.row_factory = sqlite3.Row
    return conn

def ensure_database_tables():
    """Make sure all required database tables exist"""
    conn = None
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Create User table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS User (
            User_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Name TEXT NOT NULL,
            Email TEXT UNIQUE NOT NULL,
            Password TEXT NOT NULL,
            Role TEXT NOT NULL CHECK(Role IN ('Patient', 'Doctor', 'Nurse')),
            chat_id INTEGER UNIQUE,
            telegram_id TEXT UNIQUE NOT NULL,
            telegram_verification_code TEXT,
            is_first_login BOOLEAN DEFAULT 1,
            created_at TIMESTAMP DEFAULT (datetime('now', 'localtime'))
        )
        """)

        # Create Patient table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Patient (
            Patient_ID INTEGER PRIMARY KEY,
            condition TEXT,
            timezone TEXT DEFAULT 'UTC',
            chat_time TEXT,
            Cumulative_Score REAL DEFAULT 0.00,
            Day_On_Day_Score REAL DEFAULT 0.00,
            ThreeDay_Day_On_Day_Score REAL DEFAULT 0.00,
            FOREIGN KEY (Patient_ID) REFERENCES User(User_ID) ON DELETE CASCADE
        )
        """)
        
        # Create Doctor_Nurse table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Doctor_Nurse (
            Doctor_ID INTEGER PRIMARY KEY,
            Specialty TEXT,
            License_Number TEXT NOT NULL,
            Institution TEXT NOT NULL,
            FOREIGN KEY (Doctor_ID) REFERENCES User(User_ID) ON DELETE CASCADE
        )
        """)
        
        # Create Session_Scores table with separate Date and Timestamp columns
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Session_Scores (
            Session_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            User_ID INTEGER,
            Date TEXT,  -- Separate date field (YYYY-MM-DD format)
            Timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            Sentiment_Score REAL,
            FOREIGN KEY (User_ID) REFERENCES Patient(Patient_ID) ON DELETE CASCADE
        )
        """)

        # Create Messages table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Messages (
            Message_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Session_ID INTEGER,
            Question TEXT NOT NULL,
            Response TEXT NOT NULL,
            Timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            Sentiment_Score REAL DEFAULT 0.50,
            Patient_ID INTEGER,
            FOREIGN KEY (Patient_ID) REFERENCES Patient(Patient_ID) ON DELETE CASCADE,
            FOREIGN KEY (Session_ID) REFERENCES Session_Scores(Session_ID) ON DELETE SET NULL
        )
        """)

        # Create Doctor_Patient table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Doctor_Patient (
            Doctor_ID INTEGER,
            Patient_ID INTEGER,
            Start_Date TEXT DEFAULT (date('now')),
            PRIMARY KEY (Doctor_ID, Patient_ID),
            FOREIGN KEY (Doctor_ID) REFERENCES Doctor_Nurse(Doctor_ID) ON DELETE CASCADE,
            FOREIGN KEY (Patient_ID) REFERENCES Patient(Patient_ID) ON DELETE CASCADE
        )
        """)

        # Create Alerts table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS Alerts (
            Alert_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Patient_ID INTEGER NOT NULL,
            Alert_Type TEXT NOT NULL,
            Message TEXT,
            Created_At TIMESTAMP DEFAULT (datetime('now', 'localtime')),
            Resolved_At TIMESTAMP,
            Status TEXT DEFAULT 'pending',
            FOREIGN KEY (Patient_ID) REFERENCES User(User_ID)
        )
        """)

        conn.commit()
        logger.info("Database tables verified/created successfully")
    except Exception as e:
        logger.error(f"Error ensuring database tables: {e}")
        traceback.print_exc()
    finally:
        if conn:
            conn.close()
        

# Update the send_telegram_message function to handle keyboards
def send_telegram_message(chat_id: int, text: str, reply_markup=None, keyboard=None) -> Dict[str, Any]:
    """Send a message to a Telegram chat with optional inline buttons or keyboard"""
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
    elif keyboard:
        payload["reply_markup"] = keyboard
    
    try:
        response = requests.post(url, json=payload)
        logger.info(f"Message sent to {chat_id}, status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Failed to send message: {response.text}")
            return {"ok": False, "error": response.text}
        
        try:
            conn = get_db_connection()
            cursor = conn.cursor()

            # Get Session ID and User ID from Chat ID
            cursor.execute(
                """
                SELECT s.Session_ID, u.User_ID 
                FROM Session_Scores s
                JOIN User u ON s.User_ID = u.User_ID
                WHERE u.chat_id = ? 
                ORDER BY s.Date DESC 
                LIMIT 1
                """,
                (chat_id,)
            )
            session_data = cursor.fetchone()
            if session_data:
                session_id = session_data['Session_ID']
                user_id = session_data['User_ID']
            else:
                # If no session found, create a default one
                logger.warning(f"No session found for chat_id {chat_id}, using default values")
                user_id = None
                session_id = None

            # Store the bot's question with a placeholder response
            # The actual response will be updated when the user replies
            cursor.execute(
                """
                INSERT INTO Messages (Session_ID, Question, Response, Patient_ID)
                VALUES (?, ?, ?, ?)
                """,
                (session_id, text, "Awaiting Response", user_id)
            )
            
            conn.commit()
            conn.close()
            
        except Exception as e:
            logger.error(f"Error storing bot question: {str(e)}")

        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return {"ok": False, "error": str(e)}
    
# Update the send_telegram_message function to handle keyboards
def send_without_storing_message(chat_id: int, text: str, reply_markup=None, keyboard=None) -> Dict[str, Any]:
    """Send a message to a Telegram chat with optional inline buttons or keyboard"""
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
    elif keyboard:
        payload["reply_markup"] = keyboard
    
    try:
        response = requests.post(url, json=payload)
        logger.info(f"Message sent to {chat_id}, status: {response.status_code}")
        
        if response.status_code != 200:
            logger.error(f"Failed to send message: {response.text}")
            return {"ok": False, "error": response.text}

        return response.json()
    except Exception as e:
        logger.error(f"Error sending message: {str(e)}")
        return {"ok": False, "error": str(e)}

def get_inline_keyboard(buttons: List[List[Dict[str, str]]]) -> Dict[str, List]:
    """Create an inline keyboard markup"""
    return {"inline_keyboard": buttons}

def get_professional_keyboard(context=None):
    # keyboard = [["Contact a professional"]]
    keyboard = {
        "keyboard": [["Contact a professional"]],
        "resize_keyboard": True,
        "one_time_keyboard": False,
        "persistent": True
    }

    # Add End Chat button if in AI chat mode
    # if context and context.user_data.get('ai_chat_mode'):
    #    keyboard.append(["End Chat"])

    # return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    return keyboard

# Function to handle the "Contact a professional" request
def handle_professional_help_request(user_id: int, chat_id: int) -> Dict[str, Any]:
    """Process a request for professional help and alert doctors"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get patient info
        cursor.execute(
            """
            SELECT u.Name FROM User u WHERE u.User_ID = ?
            """, 
            (user_id,)
        )
        patient = cursor.fetchone()
        if not patient:
            logger.error(f"Patient ID {user_id} not found")
            return {"success": False, "message": "Patient not found"}
        
        # Call the alert function to handle sending alerts to doctors
        alert_doctors_for_patient(user_id)
            
        conn.close()
        
        return {
            "success": True,
            "message": "Your request has been sent to healthcare professionals. Someone will contact you soon."
        }
        
    except Exception as e:
        logger.error(f"Error handling professional help request: {str(e)}")
        return {"success": False, "error": str(e)}

def curate_question(chat_id: int, user_id: int) -> None:
    """Send daily check-in message to a patient"""
    conn = None
    try:
        # Create a session for today
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Check if we already have a session for today
        today_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(
            """
            SELECT Session_ID FROM Session_Scores 
            WHERE User_ID = ? AND Date = ?
            """, 
            (user_id, today_date)
        )
        
        session = cursor.fetchone()
        if session:
            session_id = session['Session_ID']
            logger.info(f"Using existing session {session_id} for user {user_id}")
        else:
            # Create a new session for today
            cursor.execute(
                """
                INSERT INTO Session_Scores (User_ID, Date, Sentiment_Score)
                VALUES (?, ?, 0.5)
                """, 
                (user_id, today_date)
            )
            conn.commit()
            session_id = cursor.lastrowid
            logger.info(f"Created new session {session_id} for user {user_id}")

        # Find message count to determine if question comes from question bank or AI, and if it includes a greeting
        cursor.execute(
            """
            SELECT COUNT (*) AS number_of_rows
            FROM Messages
            WHERE Session_ID = ?
            """,
            (session_id,)
        )
        result = cursor.fetchone()
        message_count = result['number_of_rows'] if result else 0

        # Determine the message to send
        message = None
        if message_count < len(DEFAULT_QUESTIONS):
            if message_count == 0:
                # Get user's name from database
                cursor.execute(
                    """
                    SELECT Name FROM User
                    WHERE User_ID = ?
                    """,
                    (user_id,)
                )
                user = cursor.fetchone()
                name = user['Name'] if user else "there"
                first_name = name.split()[0]
                message = f"👋 Hey, {first_name}! It's time for your daily check-in. {DEFAULT_QUESTIONS[0]}"
            else:
                message = DEFAULT_QUESTIONS[message_count]
        else:
            message = get_ai_response(user_id, chat_id)

        # Create the keyboard with the professional help button
        keyboard = get_professional_keyboard()

        # Send the message
        result = send_telegram_message(chat_id, message, keyboard=keyboard)
        
        if conn:
            conn.close()
            conn = None
        
        return result
        
    except Exception as e:
        logger.error(f"Error sending daily check-in: {str(e)}")
        return None

# Add this function for OpenAI-powered conversations
def get_ai_response(user_id: int, chat_id: int = None) -> str:
    """
    Get an AI response based on conversation history with the user
    
    Args:
        user_id: The database user ID
        chat_id: Optional Telegram chat ID for logging
    
    Returns:
        AI generated response text
    """
    try:
        # Get OpenAI API key from environment
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            logger.error("OpenAI API key not found in environment")
            return "I'm sorry, but I'm unable to process your request at the moment."
            
        # Initialize OpenAI client
        client = OpenAI(api_key=api_key)
        
        # Get recent conversation history
        conn = get_db_connection()
        cursor = conn.cursor()
        
        try:
            # Get user's name and condition if available
            cursor.execute(
                """
                SELECT u.Name, p.condition 
                FROM User u
                LEFT JOIN Patient p ON u.User_ID = p.Patient_ID
                WHERE u.User_ID = ?
                """, 
                (user_id,)
            )
            user_info = cursor.fetchone()
            user_name = user_info['Name'] if user_info else "the patient"
            condition = user_info['condition'] if user_info and user_info['condition'] else "mental health concerns"

            # Get the 5 most recent exchanges
            cursor.execute(
                """
                SELECT Question, Response, Sentiment_Score 
                FROM Messages 
                WHERE Patient_ID = ? 
                ORDER BY Message_ID DESC LIMIT 5
                """, 
                (user_id,)
            )
            
            history = cursor.fetchall()
            conversation_history = []
            
            # Format conversation history for OpenAI
            for msg in reversed(history):
                # Add the bot's previous question
                conversation_history.append({
                    "role": "assistant", 
                    "content": msg['Question']
                })
                
                # Add the user's previous response
                conversation_history.append({
                    "role": "user", 
                    "content": msg['Response']
                })
                
                # Add sentiment as a system message (not as user content)
                conversation_history.append({
                    "role": "system", 
                    "content": f"The sentiment score for the previous response was {msg['Sentiment_Score']:.2f} (0=negative, 1=positive)"
                })
            
            # Set up the system message
            system_prompt = f"""You are a supportive mental health assistant helping {user_name}, who has {condition}.
            Be empathetic, thoughtful, and ask follow-up questions to better understand their concerns.
            Your task is to generate a new question for the patient based on their conversation history.
            Keep responses concise (2-3 sentences) and conversational.
            Don't diagnose or provide medical advice, but focus on supportive listening and asking good questions.
            If they express thoughts of self-harm or harm to others, suggest they contact emergency services or a crisis helpline."""
            
            # Build messages array
            messages = [{"role": "system", "content": system_prompt}] + conversation_history
            
            # Add conversation history
            if conversation_history:
                messages.extend(conversation_history)
                
            # Add a final prompt to generate a new question
            messages.append({
                "role": "user", 
                "content": "Based on our conversation so far, what's a good follow-up question you would ask me as my mental health assistant?"
            })
            
            # Make the API call
            completion = client.chat.completions.create(
                model="gpt-4o",  # Change as needed based on your requirements
                messages=messages,
                max_tokens=150,
                temperature=0.7
            )
            
            # Extract the response
            response = completion.choices[0].message.content.strip()
            
            # Log the interaction
            if chat_id:
                logger.info(f"AI response for user {user_id} (chat {chat_id}): {response[:50]}...")
            
            # Close connection before returning
            if conn:
                conn.close()
                conn = None
            
            return response
        
        except Exception as e:
            logger.error(f"Error getting AI response: {str(e)}")
            import traceback
            logger.error(traceback.format_exc())
            return "How are you feeling today? Is there anything specific you'd like to talk about?"
            
        finally:
            if conn:
                try:
                    conn.close()
                except:
                    pass
    except Exception as e:
        logger.error(f"Error getting AI response: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return "How are you feeling today? Is there anything specific you'd like to talk about?"


# Add this function to continue conversations after initial check-in
async def continue_conversation(user_id: int, chat_id: int, session_id: int) -> None:
    """
    Continue an AI-driven conversation with the user after initial check-in questions
    """
    try:
        # Get user's name for personalized greeting
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("SELECT Name FROM User WHERE User_ID = ?", (user_id,))
        user = cursor.fetchone()
        conn.close()
        
        if not user:
            return
            
        user_name = user['Name'].split()[0]  # Get first name
        
        # Initial message to transition to conversational mode
        initial_message = (
            f"Thank you for completing today's check-in, {user_name}. "
            f"Let's continue our conversation. How are you feeling right now, in this moment?"
        )
        
        # Store the initial question
        store_bot_question(user_id, chat_id, initial_message, session_id)
        
        # Send the message
        send_telegram_message(chat_id, initial_message)
        
    except Exception as e:
        logger.error(f"Error in continue_conversation: {str(e)}")

# Helper function to store bot questions for context
def store_bot_question(user_id: int, chat_id: int, question: str, session_id: int) -> None:
    """Store a bot-generated question in the database"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Store the bot's question with a placeholder response
        # The actual response will be updated when the user replies
        cursor.execute(
            """
            INSERT INTO Messages (Session_ID, Question, Response, Sentiment_Score, Patient_ID)
            VALUES (?, ?, ?, NULL, ?)
            """,
            (session_id, question, "Awaiting Response", user_id)
        )
        
        conn.commit()
        conn.close()
        
    except Exception as e:
        logger.error(f"Error storing bot question: {str(e)}")

def process_patient_response(user_id: int, chat_id: int, question: str, response: str) -> Dict[str, Any]:
    """Process a patient response and calculate sentiment score"""
    try:
        
        client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

        # Format input text
        text = f"Question: {question} Response: {response}"

        # Create prompt for sentiment analysis
        prompt = f"""
                Analyze the sentiment of the following text and return a score between 0 and 1, 
                where 0 is extremely negative and 1 is extremely positive.

                Text: {text}

                Return only the numerical score without any explanation.
                """
        
        # Call the OpenAI API
        completion = client.chat.completions.create(
            model="gpt-4o",  # You can use a different model if needed
            messages=[{"role": "system",
                       "content": "You are a sentiment analysis system that returns scores between 0 and 1."},
                      {"role": "user", "content": prompt}],
            max_tokens=10
        )

        # Extract the sentiment score from the response
        sentiment_score = float(completion.choices[0].message.content.strip())

        # Ensure the score is within the valid range
        sentiment_score = max(0.0, min(1.0, sentiment_score))
            
        # Round to 2 decimal places
        sentiment_score = round(sentiment_score, 2)
        
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get today's session for this user
        today_date = datetime.now().strftime('%Y-%m-%d')
        cursor.execute(
            """
            SELECT Session_ID FROM Session_Scores 
            WHERE User_ID = ? AND Date = ?
            """, 
            (user_id, today_date)
        )
        
        session_result = cursor.fetchone()
        if not session_result:
            # Create a new session if none exists
            cursor.execute(
                """
                INSERT INTO Session_Scores (User_ID, Date, Sentiment_Score)
                VALUES (?, ?, ?)
                """, 
                (user_id, today_date, sentiment_score)
            )
            session_id = cursor.lastrowid
        else:
            session_id = session_result['Session_ID']
            # Update existing session with new average
            cursor.execute(
                """
                UPDATE Session_Scores 
                SET Sentiment_Score = ?
                WHERE Session_ID = ?
                """, 
                (sentiment_score, session_id)
            )
        
        # Store the message
        cursor.execute(
            """
            UPDATE Messages
            SET Sentiment_Score = ?, Response = ?
            WHERE Response = 'Awaiting Response'
            """,
            (sentiment_score, response)
        )
        
        # Update cumulative scores in Patient table
        cursor.execute(
            """
            UPDATE Patient
            SET Cumulative_Score = (
                SELECT AVG(Sentiment_Score)
                FROM Session_Scores
                WHERE User_ID = ?
            )
            WHERE Patient_ID = ?
            """,
            (user_id, user_id)
        )

        # Calculate and update day-on-day score
        cursor.execute(
            """
            UPDATE Patient
            SET Day_On_Day_Score = (
                SELECT (
                    (SELECT Sentiment_Score FROM Session_Scores 
                     WHERE User_ID = ? AND Date = ?) -
                    COALESCE((SELECT Sentiment_Score FROM Session_Scores 
                     WHERE User_ID = ? AND Date < ?
                     ORDER BY Date DESC LIMIT 1), 0)
                )
            )
            WHERE Patient_ID = ?
            """,
            (user_id, today_date, user_id, today_date, user_id)
        )

        # Calculate and update 3-day change
        cursor.execute(
            """
            UPDATE Patient
            SET ThreeDay_Day_On_Day_Score = (
                SELECT (
                    (SELECT AVG(Sentiment_Score) FROM Session_Scores 
                     WHERE User_ID = ? AND Date >= date(?, '-3 days')) -
                    COALESCE((SELECT AVG(Sentiment_Score) FROM Session_Scores 
                     WHERE User_ID = ? AND Date >= date(?, '-6 days') AND Date < date(?, '-3 days')), 0)
                )
            )
            WHERE Patient_ID = ?
            """,
            (user_id, today_date, user_id, today_date, today_date, user_id)
        )
        
        # Update the sentiment score in Session_Scores to match the latest message
        cursor.execute(
            """
            UPDATE Session_Scores
            SET Sentiment_Score = (
                SELECT AVG(Sentiment_Score)
                FROM Messages
                WHERE Session_ID = ?
            )
            WHERE Session_ID = ?
            """,
            (session_id, session_id)
        )
        
        conn.commit()
        
        # Check if sentiment is very low and alert is needed
        # if sentiment_score < 0.3:
        #    alert_doctors_for_patient(user_id, sentiment_score)
        
        conn.close()

        curate_question(chat_id, user_id)
        
        return {
            "success": True,
            "sentiment_score": sentiment_score,
            "session_id": session_id
        }
        
    except Exception as e:
        logger.error(f"Error processing patient response: {str(e)}")
        return {"success": False, "error": str(e)}

def alert_doctors_for_patient(patient_id: int, message_type: str = "professional_help") -> None:
    """
    Send Telegram alerts to doctors when a patient needs assistance.
    
    This function should ONLY be used for patient-initiated contact requests,
    not for automatic low sentiment score alerts.
    
    Args:
        patient_id: The ID of the patient requesting help
        message_type: Type of alert ("professional_help" or "custom")
    """
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get patient info
        cursor.execute(
            """
            SELECT u.Name FROM User u WHERE u.User_ID = ?
            """, 
            (patient_id,)
        )
        patient = cursor.fetchone()
        if not patient:
            logger.error(f"Patient ID {patient_id} not found")
            return
        
        patient_name = patient['Name']
        
        # Get doctors assigned to this patient
        cursor.execute(
            """
            SELECT u.User_ID, u.Name, u.chat_id
            FROM User u
            JOIN Doctor_Nurse d ON u.User_ID = d.Doctor_ID
            JOIN Doctor_Patient dp ON dp.Doctor_ID = d.Doctor_ID
            WHERE dp.Patient_ID = ? AND u.chat_id IS NOT NULL
            """,
            (patient_id,)
        )
        
        doctors = cursor.fetchall()
        if not doctors:
            logger.info(f"No doctors with chat_id found for patient {patient_id}")
            return
        
        # Insert record into Alerts table
        cursor.execute(
            """
            INSERT INTO Alerts (Patient_ID, Alert_Type, Message, Created_At, Status)
            VALUES (?, ?, ?, datetime('now', 'localtime'), 'pending')
            """,
            (patient_id, "professional_help", f"Patient has requested professional assistance")
        )
        
        conn.commit()
        
        # Send alerts to each doctor
        for doctor in doctors:
            doctor_name = doctor['Name']
            chat_id = doctor['chat_id']
            
            message = (
                f"🔴 *URGENT: Professional Help Requested*\n\n"
                f"Patient: *{patient_name}*\n"
                f"Time: *{datetime.now().strftime('%Y-%m-%d %H:%M')}*\n\n"
                f"_This patient has explicitly requested to speak with a healthcare professional._\n\n"
                f"Please check their details and contact them as soon as possible:\n"
                f"[Patient Details](http://echomind.app/portal/patient/{patient_id})"
            )
            
            send_telegram_message(chat_id, message)
            logger.info(f"Professional help alert sent to Dr. {doctor_name} for patient {patient_name}")
        
        conn.close()
        
    except Exception as e:
        logger.error(f"Error sending doctor alerts: {str(e)}")

def get_users_for_daily_checkin(current_hour: int, current_minute: int) -> List[Dict[str, Any]]:
    """Get users who should receive check-ins at the current time"""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Format hour and minute with leading zeros
        time_pattern = f"{current_hour:02d}:{current_minute:02d}"
        
        # DEBUG: Print all chat times in the database
        cursor.execute("SELECT u.User_ID, u.Name, p.chat_time FROM User u JOIN Patient p ON u.User_ID = p.Patient_ID")
        all_times = cursor.fetchall()
        logger.info(f"All scheduled chat times: {[(row['Name'], row['chat_time']) for row in all_times]}")
        
        # FIXED: First, extract minutes from chat_time and compare directly
        cursor.execute(
            """
            SELECT u.User_ID, u.Name, u.chat_id, p.timezone, p.chat_time
            FROM User u
            JOIN Patient p ON u.User_ID = p.Patient_ID
            WHERE u.chat_id IS NOT NULL
            """
        )
        
        potential_users = cursor.fetchall()
        matching_users = []
        
        for user in potential_users:
            chat_time = user['chat_time']
            if not chat_time:
                continue
                
            try:
                # Parse the chat_time
                chat_hour, chat_minute = map(int, chat_time.split(':'))
                
                # Check if current time matches the scheduled time
                # Add a 1-minute window before and after to ensure we don't miss anyone
                if (current_hour == chat_hour and 
                   (current_minute == chat_minute or 
                    (current_minute == chat_minute - 1) or 
                    (current_minute == chat_minute + 1))):
                    matching_users.append(dict(user))
                    logger.info(f"Found matching user {user['Name']} with chat time {chat_time} for current time {time_pattern}")
            except ValueError:
                logger.warning(f"Invalid chat_time format for user {user['Name']}: {chat_time}")
                continue
        
        # Log the results for debugging
        if matching_users:
            logger.info(f"Found {len(matching_users)} users scheduled for check-in around {time_pattern}: {[u['Name'] for u in matching_users]}")
        else:
            logger.info(f"No users found scheduled for check-in around {time_pattern}")
        
        conn.close()
        return matching_users
        
    except Exception as e:
        logger.error(f"Error getting users for daily check-in: {str(e)}")
        import traceback
        logger.error(traceback.format_exc())
        return []

def process_callback_query(callback_data: str, chat_id: int, user_id: int) -> Dict[str, Any]:
    """Process callback query data from inline buttons"""
    try:
        # Parse the callback data
        parts = callback_data.split('_')
        action = parts[0]
        
        if action == "checkin":
            # Format: checkin_sessionId_questionIndex
            session_id = int(parts[1])
            question_index = int(parts[2])
            
            # Define the list of questions
            questions = [
                "How are you feeling today?",
                "Have you been able to relax in the past 24 hours?",
                "How was your sleep last night?",
                "How would you rate your stress level today (1-10)?",
                "Have you experienced any anxiety today?",
                "Is there anything in particular that's bothering you?"
            ]
            
            if question_index >= len(questions):
                # We've reached the end of questions
                return {
                    "success": True,
                    "message": "Thank you for completing your check-in today! Your responses have been recorded.",
                    "type": "completed"
                }
            
            # Get the next question
            question = questions[question_index]
            next_index = question_index + 1
            
            # Create response with next question
            return {
                "success": True,
                "message": f"Question {question_index + 1}/{len(questions)}: {question}",
                "type": "question",
                "next_callback": f"checkin_{session_id}_{next_index}"
            }
            
        elif action == "remind":
            # Format: remind_timeInHours
            hours = int(parts[1])
            
            # We'd implement the reminder logic here
            return {
                "success": True,
                "message": f"I'll remind you again in {hours} hour{'' if hours == 1 else 's'}.",
                "type": "reminder"
            }
            
        elif action == "skip":
            # User wants to skip today
            return {
                "success": True,
                "message": "No problem! I've noted that you're skipping today's check-in. I'll check in with you tomorrow.",
                "type": "skipped"
            }
        
        else:
            # Unknown action
            return {
                "success": False,
                "message": "Sorry, I didn't understand that action.",
                "type": "error"
            }
            
    except Exception as e:
        logger.error(f"Error processing callback: {str(e)}")
        return {
            "success": False,
            "message": "An error occurred processing your request",
            "type": "error"
        }