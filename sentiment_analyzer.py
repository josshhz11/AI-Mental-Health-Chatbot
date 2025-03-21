import os
import requests
import json
import logging
from dotenv import load_dotenv

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()

def analyze_sentiment(text):
    """
    Analyze sentiment of text using OpenAI API
    Returns a score between 0-1 (0 being negative, 1 being positive)
    """
    try:
        # Get API key from environment
        api_key = os.environ.get("OPENAI_API_KEY")
        
        if not api_key:
            logger.error("OPENAI_API_KEY not set in environment variables")
            return 0.5  # Return neutral score if no API key
        
        # Prepare the request to OpenAI API
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}"
        }
        
        payload = {
            "model": "gpt-4o",  # You can use a different model if needed
            "messages": [
                {
                    "role": "system", 
                    "content": "You are a sentiment analysis system that returns scores between 0 and 1."
                },
                {
                    "role": "user", 
                    "content": f"Analyze the sentiment of the following text and return a score between 0 and 1, where 0 is extremely negative and 1 is extremely positive: '{text}'. Return only the numerical score without any explanation."
                }
            ],
            "max_tokens": 10
        }
        
        # Make the API call
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers=headers,
            json=payload
        )
        
        # Parse the response
        if response.status_code == 200:
            result = response.json()
            score_text = result['choices'][0]['message']['content'].strip()
            
            # Try to parse the score as a float
            try:
                score = float(score_text)
                # Ensure the score is within bounds
                score = max(0.0, min(1.0, score))
                return score
            except ValueError:
                logger.error(f"Failed to parse sentiment score: {score_text}")
                return 0.5
        else:
            logger.error(f"API request failed with status {response.status_code}: {response.text}")
            return 0.5
    
    except Exception as e:
        logger.error(f"Error in sentiment analysis: {e}")
        return 0.5  # Return neutral score on error

def save_sentiment_to_db(db_connection, user_id, question, response, sentiment_score):
    """Save a sentiment score to the database"""
    try:
        cursor = db_connection.cursor()
        
        # Get current date in YYYY-MM-DD format
        from datetime import datetime
        today_date = datetime.now().strftime('%Y-%m-%d')
        
        # Check if there's already a session for today
        cursor.execute(
            """
            SELECT Session_ID FROM Session_Scores
            WHERE User_ID = ? AND Date = ?
            """,
            (user_id, today_date)
        )
        
        existing_session = cursor.fetchone()
        
        if existing_session:
            # Use existing session
            session_id = existing_session['Session_ID']
        else:
            # Create new session
            cursor.execute(
                """
                INSERT INTO Session_Scores (User_ID, Date, Sentiment_Score)
                VALUES (?, ?, ?)
                """,
                (user_id, today_date, sentiment_score)
            )
            session_id = cursor.lastrowid
        
        # Save message with sentiment score
        cursor.execute(
            """
            INSERT INTO Messages (Session_ID, Question, Response, Sentiment_Score, Patient_ID)
            VALUES (?, ?, ?, ?, ?)
            """,
            (session_id, question, response, sentiment_score, user_id)
        )
        
        # Update session score with average
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
        
        # Update patient scores
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
        
        # Update day-on-day score
        cursor.execute(
            """
            UPDATE Patient
            SET Day_On_Day_Score = (
                SELECT (
                    (SELECT AVG(Sentiment_Score) FROM Session_Scores 
                    WHERE User_ID = ? AND Date = ?) -
                    (SELECT AVG(Sentiment_Score) FROM Session_Scores 
                    WHERE User_ID = ? AND Date = date(?, '-1 day'))
                )
            )
            WHERE Patient_ID = ?
            """,
            (user_id, today_date, user_id, today_date, user_id)
        )
        
        # Update 3-day score
        cursor.execute(
            """
            UPDATE Patient
            SET ThreeDay_Day_On_Day_Score = (
                SELECT (
                    (SELECT AVG(Sentiment_Score) FROM Session_Scores 
                    WHERE User_ID = ? AND Date >= date(?, '-3 days')) -
                    (SELECT AVG(Sentiment_Score) FROM Session_Scores 
                    WHERE User_ID = ? AND Date >= date(?, '-6 days')
                    AND Date < date(?, '-3 days'))
                )
            )
            WHERE Patient_ID = ?
            """,
            (user_id, today_date, user_id, today_date, today_date, user_id)
        )
        
        db_connection.commit()
        return True
    
    except Exception as e:
        logger.error(f"Error saving sentiment to database: {e}")
        db_connection.rollback()
        return False

# For testing
if __name__ == "__main__":
    test_texts = [
        "I'm feeling really great today!",
        "I'm okay, just a bit tired.",
        "I feel terrible, everything is going wrong.",
        "I don't know how I feel today."
    ]
    
    for text in test_texts:
        score = analyze_sentiment(text)
        print(f"Text: '{text}'")
        print(f"Sentiment score: {score:.2f}")
        print()