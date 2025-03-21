import os
import sqlite3
import random
import string
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta

class Database:
    def __init__(self):
        self.db_path = os.path.join(os.path.dirname(__file__), "echomind.sqlite")
        self._ensure_db_exists()
        
    def _ensure_db_exists(self):
        """Create database and tables if they don't exist"""
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        
        conn = self.get_connection()
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
        conn.close()


    def get_connection(self):
        """Get SQLite database connection with row factory"""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn
    
class UserDB:
    def __init__(self):
        self.db = Database()

    def add_user(self, user_data):
        """Add a new user to the database"""
        # Ensure email is lowercase
        if "email" in user_data:
            user_data["email"] = user_data["email"].lower()
        if "doctor_email" in user_data and user_data["doctor_email"]:
            user_data["doctor_email"] = user_data["doctor_email"].lower()

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Begin transaction
            conn.execute("BEGIN")
            
            # Extract name parts
            full_name = f"{user_data.get('first_name')} {user_data.get('last_name')}".strip()
            
            # Get current timestamp for created_at
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # Insert into User table - now includes telegram fields
            cursor.execute(
                """
                INSERT INTO User (Name, Email, Password, Role, created_at, telegram_id, is_first_login)
                VALUES (?, ?, ?, ?, ?, ?, 1)
                """,
                (
                    full_name,
                    user_data.get('email'),
                    user_data.get('password'),
                    'Patient' if user_data.get('user_type') == 'patient' else 'Doctor',
                    current_timestamp,
                    user_data.get('telegram_id')
                )
            )

            user_id = cursor.lastrowid

            # Insert into appropriate table based on Patient/Doctor Role
            if user_data.get('user_type') == 'patient':
                cursor.execute(
                    """
                    INSERT INTO Patient (Patient_ID, condition, timezone, chat_time)
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id, 
                        user_data.get('condition'),
                        user_data.get('timezone', 'UTC'),
                        user_data.get('chat_time')
                    )
                )

                if user_data.get('doctor_email'):
                    doctor = self.get_user_by_email(user_data.get('doctor_email'))
                    if doctor and doctor.get('Role') == 'Doctor':
                        cursor.execute(
                            "INSERT INTO Doctor_Patient (Doctor_ID, Patient_ID) VALUES (?, ?)",
                            (doctor.get('User_ID'), user_id)
                        )
            else:  # Doctor role
                cursor.execute(
                    """
                    INSERT INTO Doctor_Nurse (Doctor_ID, Specialty, License_Number, Institution) 
                    VALUES (?, ?, ?, ?)
                    """,
                    (
                        user_id, 
                        user_data.get('specialty'), 
                        user_data.get('license_number'), 
                        user_data.get('institution')
                    )
                )

            conn.commit()
            return user_id
        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()

    def update_first_login(self, user_id, is_first_login):
        """Update the is_first_login status for a user"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                UPDATE User
                SET is_first_login = ?
                WHERE User_ID = ?
                """,
                (1 if is_first_login else 0, user_id)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating first login status: {e}")
            return False
        finally:
            conn.close()

    def generate_verification_code(self, user_id):
        """Generate a unique verification code for Telegram bot connection"""
        import random
        import string
        
        # Generate a random 6-character code
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
        
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Store the code with the user
            cursor.execute(
                """
                UPDATE User
                SET telegram_verification_code = ?
                WHERE User_ID = ?
                """,
                (code, user_id)
            )
            conn.commit()
            return code
        except Exception as e:
            print(f"Error generating verification code: {e}")
            return None
        finally:
            conn.close()

    def verify_telegram_code(self, code, chat_id):
        """Verify a Telegram verification code and update the user's chat ID"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Find the user with this verification code
            cursor.execute(
                """
                SELECT User_ID, Name, Email, Role
                FROM User
                WHERE telegram_verification_code = ?
                """,
                (code,)
            )
            
            result = cursor.fetchone()
            if result:
                user = dict(result)
                
                # Update the user's Telegram chat ID
                cursor.execute(
                    """
                    UPDATE User
                    SET chat_id = ?, telegram_verification_code = NULL, is_first_login = 0
                    WHERE User_ID = ?
                    """,
                    (chat_id, user["User_ID"])
                )
                
                conn.commit()
                return user
            
            return None
        except Exception as e:
            print(f"Error verifying Telegram code: {e}")
            conn.rollback()
            return None
        finally:
            conn.close()

    def get_patient_preferences(self, user_id):
        """Get a patient's preferences"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT timezone, chat_time
                FROM Patient
                WHERE Patient_ID = ?
                """,
                (user_id,)
            )
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    "timezone": result['timezone'],
                    "chat_time": result['chat_time']
                }
            else:
                return None
        except Exception as e:
            print(f"Error getting patient preferences: {e}")
            return None

    def check_verification_code(self, user_id, verification_code):
        """Check if a verification code is valid for a user"""
        try:
            conn = self.db.get_connection()
            cursor = conn.cursor()
            
            cursor.execute(
                """
                SELECT telegram_verification_code
                FROM User
                WHERE User_ID = ? AND telegram_verification_code = ?
                """,
                (user_id, verification_code)
            )
            
            result = cursor.fetchone()
            conn.close()
            
            return result is not None
        except Exception as e:
            print(f"Error checking verification code: {e}")
            return False

    def get_user_by_chat_id(self, chat_id):
        """Get user by Telegram chat ID"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT * FROM User
                WHERE chat_id = ?
                """,
                (chat_id,)
            )
            
            user = cursor.fetchone()
            if not user:
                return None
                
            user_dict = dict(user)
            
            # Get role specific data
            if user_dict['Role'] == 'Patient':
                cursor.execute(
                    """
                    SELECT * FROM Patient
                    WHERE Patient_ID = ?
                    """,
                    (user_dict["User_ID"],)
                )
                patient_data = cursor.fetchone()
                if patient_data:
                    user_dict.update(dict(patient_data))
                    
            elif user_dict['Role'] in ('Doctor', 'Nurse'):
                cursor.execute(
                    """
                    SELECT * FROM Doctor_Nurse
                    WHERE Doctor_ID = ?
                    """,
                    (user_dict["User_ID"],)
                )
                doctor_data = cursor.fetchone()
                if doctor_data:
                    user_dict.update(dict(doctor_data))
                    
            return user_dict
        finally:
            conn.close()

    def update_patient_chat_time(self, patient_id, chat_time):
        """Update a patient's preferred chat time"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                UPDATE Patient
                SET chat_time = ?
                WHERE Patient_ID = ?
                """,
                (chat_time, patient_id)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"Error updating chat time: {e}")
            conn.rollback()
            return False
        finally:
            conn.close()

    def get_patient_chat_time(self, patient_id):
        """Get a patient's preferred chat time"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT chat_time
                FROM Patient
                WHERE Patient_ID = ?
                """,
                (patient_id,)
            )
            
            result = cursor.fetchone()
            if result and result['chat_time']:
                return result['chat_time']
            return None
        except Exception as e:
            print(f"Error getting chat time: {e}")
            return None
        finally:
            conn.close()

    def get_patient_last_checkin(self, patient_id):
        """Get the timestamp of the patient's last check-in"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT datetime(Timestamp) as last_checkin
                FROM Messages
                WHERE Patient_ID = ?
                ORDER BY Timestamp DESC
                LIMIT 1
                """,
                (patient_id,)
            )
            result = cursor.fetchone()
            
            if result:
                last_checkin_str = dict(result).get("last_checkin")
                # Convert string to datetime object
                last_checkin = datetime.strptime(last_checkin_str, "%Y-%m-%d %H:%M:%S")
                return {"last_checkin": last_checkin}
            
            return {"last_checkin": None}
        finally:
            conn.close()

    def get_user_by_email(self, email):
        """Retrieves user by email"""
        # Ensure email is lowercase for comparison
        email = email.lower() if email else ""

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Use LOWER() function to make the query case-insensitive
            cursor.execute(
                """
                SELECT * FROM User
                WHERE LOWER(Email) = LOWER(?)
                """, 
                (email,)
            )
            user = cursor.fetchone()

            if user:
                user_dict = dict(user)  # Convert row to dictionary
                
                # Get role specific data
                if user_dict['Role'] == 'Patient':
                    cursor.execute(
                        "SELECT * FROM Patient WHERE Patient_ID = ?",
                        (user_dict["User_ID"],)
                    )
                    patient_data = cursor.fetchone()
                    if patient_data:
                        user_dict.update(dict(patient_data))
                        
                elif user_dict['Role'] in ('Doctor', 'Nurse'):
                    cursor.execute(
                        "SELECT * FROM Doctor_Nurse WHERE Doctor_ID = ?",
                        (user_dict["User_ID"],)
                    )
                    doctor_data = cursor.fetchone()
                    if doctor_data:
                        user_dict.update(dict(doctor_data))

                return user_dict
            return None
        finally:
            conn.close()

    def authenticate_user(self, email, password, verify_password_fn):
        """Authenticate a user with email and password"""
        # Ensure email is lowercase for comparison
        email = email.lower() if email else ""

        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Debug info
            print(f"DB: Authenticating {email}")
            
            cursor.execute("SELECT * FROM User WHERE Email = ?", (email,))
            user = cursor.fetchone()

            if not user:
                print(f"DB: No user found with email {email}")
                return False
            
            user_dict = dict(user)
            print(f"DB: User found: {user_dict['Name']}, Role: {user_dict['Role']}")
            
            # Verify password hash
            password_check = verify_password_fn(password, user_dict['Password'])
            print(f"DB: Password check result: {password_check}")

            if not password_check:
                return False
            
            # Get role specific data
            if user_dict['Role'] == 'Patient':
                cursor.execute(
                    "SELECT * FROM Patient WHERE Patient_ID = ?",
                    (user_dict["User_ID"],)
                )
                patient_data = cursor.fetchone()
                if patient_data:
                    user_dict.update(dict(patient_data))
                    print(f"DB: Added patient data")
                    
            elif user_dict['Role'] in ('Doctor', 'Nurse'):
                cursor.execute(
                    "SELECT * FROM Doctor_Nurse WHERE Doctor_ID = ?",
                    (user_dict["User_ID"],)
                )
                doctor_data = cursor.fetchone()
                if doctor_data:
                    user_dict.update(dict(doctor_data))
                    print(f"DB: Added doctor data")

            return user_dict
        except Exception as e:
            print(f"DB Authentication error: {str(e)}")
            return False
        finally:
            conn.close()

    def get_patients_for_doctor(self, doctor_id):
        """Get all patients for a doctor"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # JOIN User and Patient tables through Doctor_Patient Relationship
            cursor.execute(
                """
                SELECT u.User_ID, u.Name, u.Email, u.chat_id, u.telegram_id,
                    p.Cumulative_Score, p.Day_On_Day_Score, p.ThreeDay_Day_On_Day_Score, p.condition
                FROM User u
                JOIN Patient p ON u.User_ID = p.Patient_ID
                JOIN Doctor_Patient dp ON p.Patient_ID = dp.Patient_ID
                WHERE dp.Doctor_ID = ?
                """,
                (doctor_id,)
            )

            patients = []
            for row in cursor.fetchall():
                patient = dict(row)
                name_parts = patient['Name'].split()
                patient['first_name'] = name_parts[0]
                patient['last_name'] = name_parts[1] if len(name_parts) > 1 else ''
                
                patient['patient_id'] = patient['User_ID']

                # Get latest sentiment data for patient to show on doctor patient list
                cursor.execute(
                    """
                    SELECT Sentiment_Score, datetime(Timestamp) as Timestamp
                    FROM Messages
                    WHERE Patient_ID = ?
                    ORDER BY Message_ID DESC
                    LIMIT 1
                    """,
                    (patient['User_ID'],)
                )
                latest_sentiment = cursor.fetchone()

                if latest_sentiment:
                    latest_dict = dict(latest_sentiment)
                    patient['latest_score'] = int(float(latest_dict['Sentiment_Score']) * 100)
                    patient['last_checkin'] = latest_dict['Timestamp']
                else:
                    patient['latest_score'] = 0
                    patient['last_checkin'] = 'No data'

                # Calculate 7-day average score for frontend
                cursor.execute(
                    """
                    SELECT AVG(Sentiment_Score) as avg_score
                    FROM Session_Scores
                    WHERE User_ID = ? AND Date >= date('now', '-7 days')
                    """,
                    (patient['User_ID'],)
                )
                avg_result = cursor.fetchone()
                if avg_result and avg_result['avg_score'] is not None:
                    patient['avg_score'] = int(float(avg_result['avg_score']) * 100)
                else:
                    patient['avg_score'] = 0

                # Get trend data for mini chart
                cursor.execute(
                    """
                    SELECT Sentiment_Score
                    FROM Session_Scores
                    WHERE User_ID = ?
                    ORDER BY Date DESC
                    LIMIT 7
                    """,
                    (patient['User_ID'],)
                )
                trend_data = []
                for trend_row in cursor.fetchall():
                    trend_data.append(str(int(float(dict(trend_row)['Sentiment_Score']) * 100)))
                
                patient['trend_data'] = ','.join(trend_data)
                patients.append(patient)

            return patients
        finally:
            conn.close()

    def get_patient_by_id(self, patient_id):
        """Get detailed information about a single patient"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                SELECT u.*, p.*
                FROM User u
                JOIN Patient p ON u.User_ID = p.Patient_ID
                WHERE u.User_ID = ? AND u.Role = 'Patient'
                """,
                (patient_id,)
            )
            
            patient_row = cursor.fetchone()
            
            if patient_row:
                patient = dict(patient_row)
                
                # Format the name
                name_parts = patient['Name'].split(' ', 1)
                patient['first_name'] = name_parts[0]
                patient['last_name'] = name_parts[1] if len(name_parts) > 1 else ""
                patient['telegram_id'] = patient.get('chat_id') or patient.get('telegram_id')
                
                # Get doctor information
                cursor.execute(
                    """
                    SELECT u.User_ID as doctor_id, u.Name as doctor_name
                    FROM User u
                    JOIN Doctor_Patient dp ON u.User_ID = dp.Doctor_ID
                    WHERE dp.Patient_ID = ?
                    """,
                    (patient_id,)
                )
                doctor_row = cursor.fetchone()
                if doctor_row:
                    doctor_dict = dict(doctor_row)
                    patient['doctor_id'] = doctor_dict['doctor_id']
                    patient['doctor_name'] = doctor_dict['doctor_name']
                
                return patient
            
            return None
            
        finally:
            conn.close()

    def get_patient_sentiment_data(self, patient_id):
        """Get sentiment history for a patient"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get sentiment scores from Session_Scores table
            cursor.execute(
                """
                SELECT Date, Sentiment_Score
                FROM Session_Scores
                WHERE User_ID = ?
                ORDER BY Date ASC
                """,
                (patient_id,)
            )
            
            sentiment_data = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                sentiment_data.append({
                    'date': row_dict['Date'],
                    'score': int(float(row_dict['Sentiment_Score']) * 100),  # Convert to 0-100 scale
                })
            
            # Get chat history/conversations
            cursor.execute(
                """
                SELECT Message_ID, Question, Response, Sentiment_Score, 
                       date(Timestamp) as chat_date
                FROM Messages
                WHERE Patient_ID = ?
                ORDER BY Message_ID DESC
                LIMIT 10
                """,
                (patient_id,)
            )
            
            conversations = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                conversations.append({
                    'id': row_dict['Message_ID'],
                    'date': row_dict['chat_date'],
                    'question': row_dict['Question'],
                    'response': row_dict['Response'],
                    'score': int(float(row_dict['Sentiment_Score']) * 100)
                })

            # Check if we have data and return appropriate structure
            if not sentiment_data:
                # Return empty lists to avoid errors in template
                return {
                    'sentiment_data': [],
                    'conversations': []
                }
                
            return {
                'sentiment_data': sentiment_data,
                'conversations': conversations
            }
            
        except Exception as e:
            print(f"Database error in get_patient_sentiment_data: {str(e)}")
            # Return empty data on error
            return {
                'sentiment_data': [],
                'conversations': []
            }
        finally:
            conn.close()
    
    def get_alerts_for_doctor(self, doctor_id):
        """Get active alerts for a doctor"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Get alerts from patients with low sentiment scores
            cursor.execute(
                """
                SELECT 
                    a.Alert_ID, 
                    a.Patient_ID,
                    u.Name as patient_name,
                    a.Alert_Type,
                    a.Message,
                    a.Created_At,
                    a.Status
                FROM Alerts a
                JOIN User u ON a.Patient_ID = u.User_ID
                JOIN Doctor_Patient dp ON dp.Patient_ID = a.Patient_ID
                WHERE dp.Doctor_ID = ? AND a.Status = 'pending'
                ORDER BY a.Created_At DESC
                """,
                (doctor_id,)
            )
            
            alerts = [dict(row) for row in cursor.fetchall()]
            
            # Also add alerts for patients with low sentiment scores
            cursor.execute(
                """
                SELECT 
                    u.User_ID as Patient_ID,
                    u.Name as patient_name,
                    s.Sentiment_Score,
                    s.Date
                FROM Session_Scores s
                JOIN User u ON s.User_ID = u.User_ID
                JOIN Doctor_Patient dp ON dp.Patient_ID = u.User_ID
                WHERE 
                    dp.Doctor_ID = ? AND 
                    s.Sentiment_Score < 0.3 AND
                    s.Date = date('now')
                """,
                (doctor_id,)
            )
            
            low_scores = cursor.fetchall()
            
            # Convert low scores to alert format
            for score in low_scores:
                # Check if there's already an alert for this patient today
                if not any(a['Patient_ID'] == score['Patient_ID'] and a['Alert_Type'] == 'low_sentiment' for a in alerts):
                    alerts.append({
                        'Alert_ID': None,
                        'Patient_ID': score['Patient_ID'],
                        'patient_name': score['patient_name'],
                        'Alert_Type': 'low_sentiment',
                        'Message': f"Low sentiment score detected: {int(score['Sentiment_Score'] * 100)}%",
                        'Created_At': score['Date'],
                        'Status': 'pending'
                    })
            
            return alerts
            
        except Exception as e:
            print(f"Error getting alerts for doctor: {e}")
            return []
        finally:
            conn.close()

    
    def resolve_alert(self, alert_id):
        """Mark an alert as resolved"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            cursor.execute(
                """
                UPDATE Alerts
                SET Status = 'resolved', Resolved_At = datetime('now', 'localtime')
                WHERE Alert_ID = ?
                """,
                (alert_id,)
            )
            conn.commit()
            return True
        except Exception as e:
            print(f"Error resolving alert: {e}")
            return False
        finally:
            conn.close()

class PatientData:
    def __init__(self):
        self.db = Database()

    def add_sentiment_entry(self, patient_id, score, question=None, response=None):
        """Add a new sentiment score entry for a patient"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Convert score from 0-100 scale to 0-1 scale for database
            normalized_score = float(score) / 100

            # Get current date in YYYY-MM-DD format for Session_Scores.Date
            today_date = datetime.now().strftime('%Y-%m-%d')
            current_timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            # Check if there's already a session for today
            cursor.execute(
                """
                SELECT Session_ID, Sentiment_Score
                FROM Session_Scores
                WHERE User_ID = ? AND Date = ?
                """,
                (patient_id, today_date)
            )

            existing_session = cursor.fetchone()

            # If existing session is found, update the session score, if not create a new one
            if existing_session:
                session_dict = dict(existing_session)
                session_id = session_dict["Session_ID"]

                # If question and response available, add to Messages table
                if question is not None and response is not None:
                    cursor.execute(
                        """
                        INSERT INTO Messages (Session_ID, Question, Response, Sentiment_Score, Patient_ID, Timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (session_id, question, response, normalized_score, patient_id, current_timestamp)
                    )

                # Update Session_Scores table with new average sentiment
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

            else:
                # No session today, create a new one
                cursor.execute(
                    """
                    INSERT INTO Session_Scores (User_ID, Date, Timestamp, Sentiment_Score)
                    VALUES (?, ?, ?, ?)
                    """,
                    (patient_id, today_date, current_timestamp, normalized_score)
                )

                session_id = cursor.lastrowid

                # If question and response available, add to Messages table
                if question is not None and response is not None:
                    cursor.execute(
                        """
                        INSERT INTO Messages (Session_ID, Question, Response, Sentiment_Score, Patient_ID, Timestamp)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (session_id, question, response, normalized_score, patient_id, current_timestamp)
                    )
                    
            # Update the cumulative scores in the Patient table
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
                (patient_id, patient_id)
            )

            # Calculate and update day-on-day score
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
                (patient_id, today_date, patient_id, today_date, patient_id)
            )

            # Calculate and update 3-day change
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
                (patient_id, today_date, patient_id, today_date, today_date, patient_id)
            )

            conn.commit()
            return session_id

        except Exception as e:
            conn.rollback()
            raise e
        finally:
            conn.close()
    
    def get_pending_responses(self, patient_id):
        """Get pending responses for a patient"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            cursor.execute(
                """
                SELECT Message_ID, Question
                FROM Messages
                WHERE Patient_ID = ? AND Response = 'Awaiting Response'
                ORDER BY Message_ID DESC
                """,
                (patient_id,)
            )

            messages = []
            for row in cursor.fetchall():
                message = dict(row)
                messages.append({
                    'id': message['Message_ID'],
                    'question': message['Question']
                })

            return messages
        finally:
            conn.close()

    def update_response(self, message_id, response, score):
        """Update a message with a response and sentiment score"""
        conn = self.db.get_connection()
        cursor = conn.cursor()

        try:
            # Begin transactoin
            conn.execute("BEGIN")

            # Update the message
            cursor.execute(
                """
                UPDATE Messages
                SET Response = ?, Sentiment_Score = ?
                WHERE Message_ID = ?
                """,
                (response, score, message_id)
            )

            # Get the patient_id and session_id for the message
            cursor.execute(
                """
                SELECT Patient_ID, Session_ID
                FROM Messages
                WHERE Message_ID = ?
                """,
                (message_id,)
            )

            message = cursor.fetchone()
            if not message:
                conn.rollback()
                return False
            
            patient_id = message['Patient_ID']
            session_id = message['Session_ID']

            # Update session score
            if session_id:
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
            today_date = datetime.now().strftime('%Y-%m-%d')

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
                (patient_id, patient_id)
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
                (patient_id, today_date, patient_id, today_date, patient_id)
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
                (patient_id, today_date, patient_id, today_date, today_date, patient_id)
            )

            conn.commit()
            return True
        except Exception as e:
            conn.rollback()
            print(f"Error updating response: {e}")
            return False
        finally:
            conn.close()
    
    def get_patients_with_declining_scores(self, days=3, threshold=-0.1):
        """Find patients with declining sentiment scores"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        try:
            # Find patients with negative 3-day score changes
            cursor.execute(
                """
                SELECT u.User_ID, u.Name, u.Email
                FROM User u
                JOIN Patient p ON u.User_ID = p.Patient_ID
                WHERE p.ThreeDay_Day_On_Day_Score < ?
                """,
                (threshold,)
            )
            
            patients = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                name_parts = row_dict['Name'].split(' ', 1)
                patients.append({
                    'id': row_dict['User_ID'],
                    'first_name': name_parts[0],
                    'last_name': name_parts[1] if len(name_parts) > 1 else "",
                    'email': row_dict['Email'],
                })
                
            return patients
            
        finally:
            conn.close()
    
    def get_patients_missing_checkins(self, days=1):
        """Find patients who missed their check-ins"""
        conn = self.db.get_connection()
        cursor = conn.cursor()
        
        today_date = datetime.now().strftime('%Y-%m-%d')
        
        try:
            cursor.execute(
                """
                SELECT u.User_ID, u.Name, u.Email
                FROM User u
                JOIN Patient p ON u.User_ID = p.Patient_ID
                WHERE u.User_ID NOT IN (
                    SELECT DISTINCT User_ID
                    FROM Session_Scores
                    WHERE Date >= date(?, ?)
                )
                """,
                (today_date, '-' + str(days) + ' days')
            )
            
            patients = []
            for row in cursor.fetchall():
                row_dict = dict(row)
                name_parts = row_dict['Name'].split(' ', 1)
                patients.append({
                    'id': row_dict['User_ID'],
                    'first_name': name_parts[0],
                    'last_name': name_parts[1] if len(name_parts) > 1 else "",
                    'email': row_dict['Email'],
                })
                
            return patients
            
        finally:
            conn.close()