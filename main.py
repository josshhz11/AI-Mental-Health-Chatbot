import os
import requests
from fastapi import FastAPI, Request, Depends, HTTPException, status, Form, Body
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
import jwt
from passlib.context import CryptContext
from starlette.middleware.sessions import SessionMiddleware
import uvicorn
from dotenv import load_dotenv
import json
import base64
from cryptography.fernet import Fernet
from database.update_schema import update_database_schema
from sentiment_analyzer import analyze_sentiment, save_sentiment_to_db

import time
import traceback
from telegram_bot import process_patient_response, process_callback_query, get_professional_keyboard, handle_professional_help_request
import subprocess

# Initialize FastAPI app
app = FastAPI(title="EchoMind - Mental Health Assistant")

@app.on_event("startup")
async def startup_db_client():
    """Run database migrations and start scheduler on application startup."""
    print("Running database schema update...")
    update_database_schema()

    # No need to start scheduler here as it will be run as a separate process
    print("Note: Telegram scheduler should be started separately")
    print("Use: python telegram_scheduler.py or python run.py")

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

# Set up templates
templates = Jinja2Templates(directory="templates")

# Load environment variables
load_dotenv()

# Create a strong session key
SECRET_KEY = os.environ.get("SECRET_KEY", os.urandom(24).hex())
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24  # 24 hours

# Set up password hashing
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

# Set up OAuth2
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")

# Create a Fernet key for cookie encryption (derived from SECRET_KEY)
# Make sure this key is 32 bytes for Fernet
fernet_key = base64.urlsafe_b64encode(SECRET_KEY.encode()[:32].ljust(32, b'0'))
cipher_suite = Fernet(fernet_key)

from database.db import UserDB, PatientData, Database

# Initialize database
db = Database()
user_db = UserDB()
patient_data = PatientData()

# Models
class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"

class TokenData(BaseModel):
    email: Optional[str] = None
    role: Optional[str] = None

# Base user model
class UserinDB(BaseModel):
    User_ID: int
    Email: str
    Name: str
    Role: str
    is_active: bool = True

    # Utility method to convert to session format
    def to_session_dict(self):
        name_parts = self.Name.split(' ', 1)
        return {
            "id": self.User_ID,
            "email": self.Email,
            "name": self.Name,
            "first_name": name_parts[0],
            "last_name": name_parts[1] if len(name_parts) > 1 else "",
            "user_type": self.Role
        }

# Registration model - Extension of base user model
class UserRegister(BaseModel):
    email: EmailStr
    first_name: str
    last_name: str
    phone: str
    password: str
    user_type: str = "patient"

class DoctorRegister(UserRegister):
    user_type: str = "doctor"
    license_number: str
    institution: str

class PatientRegister(UserRegister):
    telegram_id: str
    doctor_email: EmailStr

# Helper functions for cookie handling
def encrypt_data(data):
    """Encrypt data for cookie storage"""
    json_data = json.dumps(data)
    encrypted = cipher_suite.encrypt(json_data.encode())
    return base64.urlsafe_b64encode(encrypted).decode()

def decrypt_data(encrypted_data):
    """Decrypt data from cookie storage"""
    try:
        decoded = base64.urlsafe_b64decode(encrypted_data)
        decrypted = cipher_suite.decrypt(decoded)
        return json.loads(decrypted)
    except:
        return None

# Helper functions

# Verifies password hashes
def verify_password(plain_password, hashed_password):
    return pwd_context.verify(plain_password, hashed_password)

# Creates secure password hashes
def get_password_hash(password):
    return pwd_context.hash(password)

# Generates JWT tokens for authentication
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=15))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)

async def get_token_data(token: str = Depends(oauth2_scheme)) -> TokenData:
    """Extract and validate data from a JWT token"""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        email: str = payload.get("sub")
        role: str = payload.get("type")
        
        if not email:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
            
        return TokenData(email=email, role=role)
    except jwt.PyJWTError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

# Authentication dependency for routes
async def get_current_user(request: Request):
    """Extract user info from cookies"""
    user_cookie = request.cookies.get("user_info")
    token_cookie = request.cookies.get("access_token")
    
    if not user_cookie or not token_cookie:
        return None
        
    try:
        # Decrypt user info from cookie
        user_data = decrypt_data(user_cookie)
        
        # Validate JWT token
        payload = jwt.decode(token_cookie, SECRET_KEY, algorithms=[ALGORITHM])
        email = payload.get("sub")
        role = payload.get("type")
        
        if not email or email != user_data.get("email"):
            return None
            
        return user_data
    except:
        return None

# Ensures a user is active before allowing access
async def get_current_active_user(current_user: dict = Depends(get_current_user)):
    if not current_user.get("is_active"):
        raise HTTPException(status_code=400, detail="Inactive user")
    return current_user
    
# Checks if user has the correct permissions
def is_doctor(user: dict):
    return user.get("user_type") == "doctor"

# Add this with the other helper functions at the top of the file
def normalize_email(email):
    """Normalize email to lowercase"""
    return email.lower() if email else None

# Routes/Endpoints

# Telegram webhook handler
@app.post("/telegram-webhook")
async def telegram_webhook(request: Request, payload: dict = Body(...)):
    """
    Webhook endpoint for receiving updates from the Telegram bot
    
    This is called by Telegram whenever there's a new message to your bot
    """
    try:
        print(f"Received webhook from Telegram: {payload}")
        
        # Extract message data
        if "message" in payload:
            message = payload["message"]
            chat_id = message["chat"]["id"]
            user_id = message["from"]["id"]
            username = message["from"].get("username", "")
            first_name = message["from"].get("first_name", "")
            last_name = message["from"].get("last_name", "")
            text = message.get("text", "")
            
            print(f"Message from user {username} ({user_id}): {text}")
            
            # Handle verification commands for linking users
            if text.startswith("/start"):
                parts = text.split(maxsplit=1)
                if len(parts) > 1:
                    # User provided a verification code
                    verification_code = parts[1].strip()
                    print(f"Processing verification code: {verification_code}")
                    
                    # Try to verify the code and link to a user
                    user = user_db.verify_telegram_code(verification_code, chat_id)
                    
                    if user:
                        # Successfully linked user
                        print(f"Successfully linked user {user['Name']} to Telegram chat {chat_id}")
                        
                        # Different welcome messages based on user role
                        if user['Role'] == 'Patient':
                            # Get their existing chat_time from database (if set via web form)
                            patient_chat_time = user_db.get_patient_chat_time(user['User_ID'])
                            
                            if patient_chat_time:
                                # They already set their chat time through the web form
                                await send_telegram_message(
                                    chat_id, 
                                    f"✅ You've been successfully connected to EchoMind!\n\n"
                                    f"Welcome, {user['Name']}. Your daily check-in time has been set to {patient_chat_time}.\n\n"
                                    f"I'll remind you each day around this time. You can change this "
                                    f"anytime by telling me a new time (e.g. '19:30')."
                                )
                            else:
                                # They haven't set their chat time yet
                                await send_telegram_message(
                                    chat_id, 
                                    f"✅ You've been successfully connected to EchoMind!\n\n"
                                    f"Welcome, {user['Name']}. Your healthcare provider can now "
                                    f"see your check-ins and sentiment scores.\n\n"
                                    f"To help with your daily check-ins, when would you prefer "
                                    f"to receive check-in reminders? Please reply with a time "
                                    f"in 24-hour format (e.g., '19:30' for 7:30 PM)."
                                )
                        else:
                            # Doctor welcome message
                            await send_telegram_message(
                                chat_id, 
                                f"✅ Welcome to EchoMind, Dr. {user['Name'].split()[-1]}!\n\n"
                                f"This bot will be used to alert you when patients indicate "
                                f"they need to speak with a medical professional.\n\n"
                                f"You'll receive notifications here when urgent patient "
                                f"matters require your attention."
                            )
                        
                        return {"status": "success", "message": "User verified"}
                    else:
                        # Invalid code
                        await send_telegram_message(
                            chat_id, 
                            "❌ Sorry, the verification code is invalid or has expired. "
                            "Please try again or generate a new code from the EchoMind portal."
                        )
                        return {"status": "error", "message": "Invalid verification code"}
                else:
                    # No code provided - improved message with clearer instructions
                    await send_telegram_message(
                        chat_id, 
                        "👋 Welcome to EchoMind!\n\n"
                        "To connect your account, you need to provide your verification code.\n\n"
                        "Please send a message in this format:\n"
                        "/start YOUR_CODE\n\n"
                        "You can find your verification code on the welcome page of the EchoMind portal."
                    )
                    return {"status": "error", "message": "No verification code provided"}
            
            # Handle "Contact a professional" button
            elif text == "Contact a professional":
                # Find user by chat_id
                user = user_db.get_user_by_chat_id(chat_id)
                if user and user['Role'] == 'Patient':
                    result = handle_professional_help_request(user['User_ID'], chat_id)
                    
                    if result.get("success"):
                        # Add the keyboard back to the response to ensure it remains available
                        keyboard = get_professional_keyboard()

                        await send_telegram_message(
                            chat_id,
                            result.get("message", "Your request has been sent to healthcare professionals."),
                            keyboard=keyboard
                        )
                    else:
                        # Even in error cases, maintain the keyboard
                        keyboard = get_professional_keyboard()
                        await send_telegram_message(
                            chat_id,
                            "Sorry, there was an error processing your request. Please try again later.",
                            keyboard=keyboard
                        )
                    return {"status": "success", "message": "Professional help requested"}
            
            # Handle time preference responses for patients
            elif text and ":" in text and len(text) <= 5:
                # Looks like a time format (e.g. "19:30")
                try:
                    # Find user by chat_id
                    user = user_db.get_user_by_chat_id(chat_id)
                    if user and user['Role'] == 'Patient':
                        # Update the chat time
                        user_db.update_patient_chat_time(user['User_ID'], text)
                        
                        await send_telegram_message(
                            chat_id,
                            f"✅ Great! Your daily check-in time has been set to {text}.\n\n"
                            f"I'll remind you each day around this time. You can change this "
                            f"anytime by telling me a new time."
                        )
                        return {"status": "success", "message": "Chat time updated"}
                except Exception as e:
                    print(f"Error updating chat time: {e}")
                    traceback.print_exc()
            
            # Handle regular messages from users
            elif chat_id:
                # Try to find user by chat_id
                user = user_db.get_user_by_chat_id(chat_id)
                
                if user:
                    if user['Role'] == 'Patient':
                        try:
                            # Process the message for sentiment analysis
                            conn = user_db.db.get_connection()
                            cursor = conn.cursor()
                            
                            cursor.execute(
                                """
                                SELECT Message_ID, Question
                                FROM Messages 
                                WHERE Patient_ID = ? AND Response = 'Awaiting Response'
                                ORDER BY Message_ID DESC LIMIT 1
                                """,
                                (user['User_ID'],)
                            )
                            pending_question = cursor.fetchone()
                            question = pending_question['Question'] if pending_question else "Chat message"
                            result = process_patient_response(user['User_ID'], chat_id, question, text)
                            
                            # At the end of the successful message processing for patients, 
                            # add the professional help button
                            if result.get("success"):
                                # Get the latest sentiment score from the database
                                cursor.execute(
                                    """
                                    SELECT Sentiment_Score
                                    FROM Messages
                                    WHERE Patient_ID = ?
                                    ORDER BY Message_ID DESC LIMIT 1
                                    """,
                                    (user['User_ID'],)
                                )
                                latest_score = cursor.fetchone()
                                
                                if latest_score:
                                    score_pct = int(float(latest_score['Sentiment_Score']) * 100)
                                else:
                                    score_pct = int(result.get("sentiment_score", 0.0) * 100)
                                
                                # Create the keyboard
                                keyboard = get_professional_keyboard()
                                
                            conn.close()
                            return {"status": "success", "message": "Message processed with keyboard"}
                        except Exception as e:
                            print(f"Error processing patient response: {e}")
                            traceback.print_exc()
                            await send_telegram_message(
                                chat_id,
                                "Sorry, there was an error processing your message. Please try again later."
                            )
                    else:
                        # Response for doctors
                        await send_telegram_message(
                            chat_id,
                            f"I received your message. As a healthcare provider, "
                            f"you'll receive notifications here when patients need attention."
                        )
                    return {"status": "success", "message": "Message processed"}
        
        # Handle callback queries (for buttons)
        elif "callback_query" in payload:
            callback_query = payload["callback_query"]
            chat_id = callback_query["message"]["chat"]["id"]
            user_id = callback_query["from"]["id"]
            callback_data = callback_query["data"]
            
            print(f"Received callback query: {callback_data} from user {user_id}")
            
            # Process the callback query
            user = user_db.get_user_by_chat_id(chat_id)
            if user:
                result = process_callback_query(callback_data, chat_id, user['User_ID'])
                
                if result.get("success"):
                    await send_telegram_message(
                        chat_id,
                        result.get("message", "Your request was processed successfully.")
                    )
                    
                    # If this is a question requiring a reply keyboard, add it
                    if result.get("type") == "question":
                        next_callback = result.get("next_callback")
                        keyboard = {
                            "inline_keyboard": [
                                [{"text": "Continue", "callback_data": next_callback}]
                            ]
                        }
                        
                        await send_telegram_message(
                            chat_id,
                            "Please respond to the question above, then click Continue.",
                            reply_markup=keyboard
                        )
                else:
                    await send_telegram_message(
                        chat_id,
                        result.get("message", "Sorry, there was an error processing your request.")
                    )
                    
                return {"status": "success", "message": "Callback processed"}
                    
        return {"status": "received", "message": "Webhook processed"}
        
    except Exception as e:
        print(f"Error in telegram webhook: {e}")
        traceback.print_exc()
        return {"status": "error", "message": str(e)}
    
# Helper function to send messages back to Telegram
async def send_telegram_message(chat_id, text, reply_markup=None, keyboard=None):
    """Async wrapper around telegram_bot's send_telegram_message function"""
    from telegram_bot import send_telegram_message as telegram_send
    return telegram_send(chat_id, text, reply_markup, keyboard)

# Helper function for debug messages back to Telegram
async def send_without_storing_message(chat_id, text, reply_markup=None, keyboard=None):
    """Async wrapper around telegram_bot's send_telegram_message function"""
    from telegram_bot import send_without_storing_message as send_without_storing
    return send_without_storing(chat_id, text, reply_markup, keyboard)

# Authentication and Registration
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    return templates.TemplateResponse("register.html", {"request": request})

@app.post("/register", response_class=HTMLResponse)
async def register(
        request: Request,
        user_type: str = Form(...),
        first_name: str = Form(...),
        last_name: str = Form(...),
        email: str = Form(...),
        phone: str = Form(...),
        password: str = Form(...),
        confirm_password: str = Form(...),
        terms: bool = Form(...),
        telegram_id: Optional[str] = Form(None),
        doctor_email: Optional[str] = Form(None),
        license_number: Optional[str] = Form(None),
        institution: Optional[str] = Form(None),
        condition: Optional[str] = Form(None),
):
        # Normalize email to lowercase
        email = normalize_email(email)
        doctor_email = normalize_email(doctor_email)

        # Validation checks
        if password != confirm_password:
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Passwords do not match."}
            )
        
        if not terms:
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "You must agree to the terms and conditions."}
            )
        
        # Check if user already exists
        existing_user = user_db.get_user_by_email(email)
        if existing_user:
            return templates.TemplateResponse(
                "register.html",
                {"request": request, "error": "Email already registered."}
            )
        
        # Once validation checks passed, create user based on type
        user_data = {
            "email": email,
            "first_name": first_name,
            "last_name": last_name,
            "phone": phone,
            "user_type": user_type,
            "password": get_password_hash(password),
            "telegram_id": telegram_id,
            "is_active": True
        }

        # Store additional information specific to role
        if user_type == "doctor":
            if not license_number or not institution:
                return templates.TemplateResponse(
                    "register.html",
                    {"request": request, "error": "License number and institution are required for healthcare providers."}
                )
            user_data["license_number"] = license_number
            user_data["institution"] = institution
        else:  # patient
            user_data["condition"] = condition  # Added condition field
            if doctor_email:
                # Verify if the doctor exists
                doctor = user_db.get_user_by_email(doctor_email)
                if not doctor or doctor.get("Role") != "Doctor":
                    return templates.TemplateResponse(
                        "register.html",
                        {"request": request, "error": "The specified doctor was not found in our system."}
                    )
                user_data["doctor_email"] = doctor_email

        user_id = user_db.add_user(user_data)

        # Redirect to login page
        return RedirectResponse(url="/login?registered=true", status_code=status.HTTP_303_SEE_OTHER)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, registered: bool = False):
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "registered": registered}
    )

@app.post("/login", response_class=HTMLResponse)
async def login(request: Request, email: str = Form(...), password: str = Form(...)):
    # Normalize email to lowercase
    email = normalize_email(email)

    # Authenticate user
    user = user_db.authenticate_user(email, password, verify_password)
    if not user:
        return templates.TemplateResponse(
            "login.html",
            {"request": request, "error": "Invalid email or password."}
        )
    
    # Create JWT token
    token = create_access_token(
        data={"sub": user["Email"], "type": user["Role"].lower()},
        expires_delta=timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)
    )
    
    # Create user info for cookie
    name_parts = user["Name"].split(' ', 1)
    user_info = {
        "id": user["User_ID"],
        "email": user["Email"],
        "name": user["Name"],
        "first_name": name_parts[0],
        "last_name": name_parts[1] if len(name_parts) > 1 else "",
        "user_type": user["Role"].lower(),
        "is_first_login": user.get("is_first_login", True)  # Include first login status
    }

    # Encrypt user info for cookie
    encrypted_user_info = encrypt_data(user_info)

    # Determine redirect URL based on user type and first login status
    if user.get("is_first_login", True):
        redirect_url = "/welcome"  # Send all first-time users to welcome page
    else:
        # Not first login, redirect based on user type
        redirect_url = "/portal" if user["Role"].lower() == "doctor" else "/patient-portal"
    
    # Create response with cookies
    response = RedirectResponse(url=redirect_url, status_code=status.HTTP_303_SEE_OTHER)
    
    # Set secure cookies
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    
    response.set_cookie(
        key="user_info",
        value=encrypted_user_info,
        httponly=True,
        max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        secure=False,  # Set to True in production with HTTPS
        samesite="lax"
    )
    
    return response

@app.get("/logout", response_class=HTMLResponse)
async def logout(request: Request):
    response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie("access_token")
    response.delete_cookie("user_info")
    return response

# Welcome page for first-time users
@app.get("/welcome", response_class=HTMLResponse)
async def welcome_page(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Check session for existing verification code
    session_cookie = request.cookies.get("session_data")
    session_data = decrypt_data(session_cookie) if session_cookie else {}
    verification_code = None
    
    if session_data and "verification_code" in session_data:
        # Use existing code from session
        verification_code = session_data["verification_code"]
        # Check if code is still valid
        is_valid = user_db.check_verification_code(user["id"], verification_code)
        if not is_valid:
            verification_code = None  # Code expired or invalid
    
    # Generate a new code only if needed
    if not verification_code:
        verification_code = user_db.generate_verification_code(user["id"])
        # Store in session
        session_data = session_data or {}
        session_data["verification_code"] = verification_code
    
    # Get preferences if the user is a patient
    preferences = None
    if user["user_type"] == "patient":
        preferences = user_db.get_patient_preferences(user["id"])
    
    context = {
        "request": request, 
        "user": user, 
        "verification_code": verification_code,
        "preferences": preferences
    }
    
    response = templates.TemplateResponse("welcome.html", context)
    
    # Update session cookie
    if session_data:
        encrypted_session = encrypt_data(session_data)
        response.set_cookie(
            key="session_data",
            value=encrypted_session,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=False,
            samesite="lax"
        )
    
    return response

# Update chat preferences for first-time patient users (on welcome page)
@app.post("/update-preferences")
async def update_preferences(
    request: Request,
    timezone: str = Form(...),
    chat_time: str = Form(...)
):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Update the user's preferences
    conn = user_db.db.get_connection()
    cursor = conn.cursor()
    
    try:
        cursor.execute(
            """
            UPDATE Patient
            SET timezone = ?, chat_time = ?
            WHERE Patient_ID = ?
            """,
            (timezone, chat_time, user["id"])
        )
        conn.commit()
        
        # Redirect back to welcome page - include a success flag
        response = RedirectResponse(url="/welcome?preferences_updated=true", status_code=status.HTTP_303_SEE_OTHER)
        
        # Don't regenerate the verification code - keep the existing one from session
        return response
    except Exception as e:
        print(f"Error updating preferences: {e}")
        return RedirectResponse(
            url="/welcome?error=Failed+to+update+preferences", 
            status_code=status.HTTP_303_SEE_OTHER
        )
    finally:
        conn.close()

# Patient portal page (for returning patients)
@app.get("/patient-portal", response_class=HTMLResponse)
async def patient_portal(request: Request):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    if user["user_type"] != "patient":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Get patient's last check-in time
    patient_data = user_db.get_patient_last_checkin(user["id"])
    last_checkin = patient_data.get("last_checkin") if patient_data else None
    
    # Update is_first_login to False if this is the first time accessing the portal
    if user.get("is_first_login", False):
        user_db.update_first_login(user["id"], False)
        
        # Update the cookie with the new status
        user["is_first_login"] = False
        encrypted_user_info = encrypt_data(user)
        response = templates.TemplateResponse(
            "patient_portal.html",
            {"request": request, "user": user, "last_checkin": last_checkin, "now": datetime.now()}
        )
        response.set_cookie(
            key="user_info",
            value=encrypted_user_info,
            httponly=True,
            max_age=ACCESS_TOKEN_EXPIRE_MINUTES * 60,
            secure=False,
            samesite="lax"
        )
        return response
    
    return templates.TemplateResponse(
        "patient_portal.html",
        {"request": request, "user": user, "last_checkin": last_checkin, "now": datetime.now()}
    )

# Doctor Portal - Dashboard of patient charts, stats, and mini list preview of patients
@app.get("/portal", response_class=HTMLResponse)
async def portal(request: Request):
    # Authentication check moved to middleware
    # Just get the user info from cookies
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    if user["user_type"] != "doctor":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Get patient data for doctor
    patient_data = user_db.get_patients_for_doctor(user["id"])

    # Normalize the data structure for each patient
    normalized_patients = []
    for patient in patient_data:
        normalized_patient = {
            'id': patient.get('User_ID'),
            'name': patient.get('Name'),
            'email': patient.get('Email'),
            'last_checkin': patient.get('last_checkin', 'N/A'),
            'latest_score': patient.get('latest_score', 0),
            'trend_data': patient.get('trend_data', '0,0,0,0,0'),
            'patient_id': patient.get('User_ID'),
            'first_name': patient.get('Name', '').split()[0],
            'last_name': ' '.join(patient.get('Name', '').split()[1:]) if len(patient.get('Name', '').split()) > 1 else ''
        }
        normalized_patients.append(normalized_patient)

    # Add current datetime for the template
    now = datetime.now()

    # Get alerts for this doctor
    alerts = user_db.get_alerts_for_doctor(user["id"])

    # Process alerts for the template
    processed_alerts = []
    for alert in alerts:
        alert_type = alert.get('Alert_Type')

        # Determine priority
        priority = "high" if alert_type == "professional_help" else "medium"
        
        processed_alerts.append({
            'patient_id': alert.get('Patient_ID'),
            'patient_name': alert.get('patient_name'),
            'message': alert.get('Message'),
            'priority': priority,
            'type': "Professional Help Requested" if alert_type == "professional_help" else "Low Sentiment Score",
            'created_at': alert.get('Created_At')
        })

    return templates.TemplateResponse(
        "portal.html",
        {
            "request": request, 
            "user": user, 
            "patients": normalized_patients, 
            "now": now, 
            "alerts": processed_alerts
        }
    )

# Add this endpoint to resolve alerts
@app.post("/portal/resolve-alert/{alert_id}")
async def resolve_alert(request: Request, alert_id: int):
    """Mark an alert as resolved"""
    user = await get_current_user(request)
    if not user or user["user_type"] != "doctor":
        return {"success": False, "message": "Unauthorized"}
    
    # Resolve the alert
    success = user_db.resolve_alert(alert_id)
    
    return {"success": success}

# Full patient list for doctor - after clicking on mini patient list with preview of patients on portal page previously
@app.get("/portal/patients", response_class=HTMLResponse)
async def patients_list(request: Request):
    # Authentication check moved to middleware
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    if user["user_type"] != "doctor":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Get patient data for doctor
    patient_data = user_db.get_patients_for_doctor(user["id"])

    # Normalize the data structure for each patient
    normalized_patients = []
    for patient in patient_data:
        normalized_patient = {
            'id': patient.get('User_ID'),
            'name': patient.get('Name'),
            'email': patient.get('Email'),
            'telegram_id': patient.get('telegram_id'),
            'last_checkin': patient.get('last_checkin', 'N/A'),
            'latest_score': patient.get('latest_score', 0),
            'avg_score': patient.get('avg_score', 0),
            'cumulative_score': patient.get('Cumulative_Score', 0),
            'trend_data': patient.get('trend_data', '0,0,0,0,0'),
            'patient_id': patient.get('User_ID'),
            'first_name': patient.get('Name', '').split()[0],
            'last_name': ' '.join(patient.get('Name', '').split()[1:]) if len(patient.get('Name', '').split()) > 1 else ''
        }
        normalized_patients.append(normalized_patient)

    # Add current datetime and alerts
    now = datetime.now()
    formatted_date = now.strftime('%B %d, %Y %H:%M')
    alerts = []

    return templates.TemplateResponse(
        "patients.html",
        {
            "request": request,
            "user": user,
            "patients": normalized_patients,
            "now": datetime.now(),
            "formatted_date": datetime.now().strftime('%B %d, %Y %H:%M'),
            "alerts": alerts,
            # Add default values for optional data
            "stats": {
                "total": len(normalized_patients),
                "good": sum(1 for p in normalized_patients if p['latest_score'] >= 70),
                "moderate": sum(1 for p in normalized_patients if 40 <= p['latest_score'] < 70),
                "low": sum(1 for p in normalized_patients if p['latest_score'] < 40)
            }
        }
    )

@app.get("/portal/patient/{patient_id}", response_class=HTMLResponse)
async def patient_detail(request: Request, patient_id: int):
    user = await get_current_user(request)
    if not user:
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        
    if user["user_type"] != "doctor":
        return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)

    # Get patient details
    patient = user_db.get_patient_by_id(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found.")
    
    # Normalize patient data
    normalized_patient = {
        'id': patient.get('User_ID'),
        'name': patient.get('Name'),
        'email': patient.get('Email'),
        'telegram_id': patient.get('telegram_id'),
        'phone': patient.get('phone', 'N/A'),
        'first_name': patient.get('Name', '').split()[0],
        'last_name': ' '.join(patient.get('Name', '').split()[1:]) if len(patient.get('Name', '').split()) > 1 else '',
        'created_at': patient.get('created_at', 'N/A')
    }
    
    # Get sentiment data with error handling
    try:
        sentiment_data = user_db.get_patient_sentiment_data(patient_id)
        # Extract just the sentiment_data array for metrics calculation
        sentiment_array = sentiment_data.get('sentiment_data', []) if isinstance(sentiment_data, dict) else []
        conversations = sentiment_data.get('conversations', []) if isinstance(sentiment_data, dict) else []
        
        # If no data, create placeholder data for charts
        if not sentiment_array:
            # Create sample data for empty charts
            today = datetime.now().strftime('%Y-%m-%d')
            sentiment_array = []
            for i in range(5):
                day = (datetime.now() - timedelta(days=i)).strftime('%Y-%m-%d')
                sentiment_array.insert(0, {'date': day, 'score': 0})
            
        # Calculate metrics with proper error handling
        metrics = calculate_patient_metrics(sentiment_array)
    except Exception as e:
        print(f"Error processing patient data: {str(e)}")
        # Create empty data structures with defaults
        sentiment_array = []
        conversations = []
        metrics = {
            'previous_score': None,
            'three_day_change': 0,
            'weekly_avg': 65,
            'weekly_change': 0,
            'completion_rate': 0,
            'completed_sessions': 0,
            'total_sessions': 1,
            'missed_sessions': 0
        }

    # Add current datetime
    now = datetime.now()
    formatted_date = now.strftime('%B %d, %Y %H:%M')
    alerts = []

    # Check if we need to add alerts
    if not sentiment_array:
        alerts.append({
            'type': 'info',
            'message': 'No sentiment data available for this patient yet.'
        })

    return templates.TemplateResponse(
        "patient_detail.html",
        {
            "request": request, 
            "user": user, 
            "patient": normalized_patient, 
            "sentiment_data": sentiment_array,
            "conversations": conversations,
            "now": now,
            "formatted_date": formatted_date,
            "alerts": alerts,
            "has_data": len(sentiment_array) > 0,
            **metrics  # Unpack all metrics
        }
    )

def calculate_patient_metrics(sentiment_data):
    """Calculate various metrics for patient dashboard"""
    # Check if sentiment_data is a dictionary with 'sentiment_data' key
    if isinstance(sentiment_data, dict) and 'sentiment_data' in sentiment_data:
        actual_data = sentiment_data['sentiment_data']
    else:
        actual_data = sentiment_data if isinstance(sentiment_data, list) else []
    
    # Default metrics
    metrics = {
        'previous_score': None,
        'three_day_change': 0,
        'weekly_avg': 65,
        'weekly_change': 0,
        'completion_rate': 92 if actual_data else 0,
        'completed_sessions': len(actual_data),
        'total_sessions': max(len(actual_data), 1),
        'missed_sessions': 0
    }
    
    # Only calculate metrics if we have data
    if actual_data and len(actual_data) > 0:
        # Previous score - check if we have at least 2 data points
        if len(actual_data) > 1:
            metrics['previous_score'] = actual_data[-2].get('score', 0)
        
        # 3-day change - check if we have at least 3 data points
        if len(actual_data) >= 3:
            first_score = actual_data[-3].get('score', 0)
            last_score = actual_data[-1].get('score', 0)
            if first_score > 0:  # Avoid division by zero
                metrics['three_day_change'] = round(((last_score - first_score) / first_score * 100))
        
        # Weekly average - get the last 7 data points or as many as we have
        recent_scores = [item.get('score', 0) for item in actual_data[-7:]]
        if recent_scores:
            metrics['weekly_avg'] = round(sum(recent_scores) / len(recent_scores))
            
        # Weekly change - check if we have at least 14 data points
        if len(actual_data) >= 14:
            current_week = actual_data[-7:]
            previous_week = actual_data[-14:-7]
            if previous_week:  # Make sure we have previous week data
                current_avg = sum(s.get('score', 0) for s in current_week) / len(current_week)
                previous_avg = sum(s.get('score', 0) for s in previous_week) / len(previous_week)
                if previous_avg > 0:  # Avoid division by zero
                    metrics['weekly_change'] = round(((current_avg - previous_avg) / previous_avg * 100))
    
    return metrics

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Check authentication for protected routes"""
    protected_paths = [
        "/portal", 
        "/portal/patients", 
        "/portal/patient/", 
        "/patient-dashboard"
    ]
    
    path = request.url.path
    
    # Check if this is a protected path
    is_protected = any(path.startswith(p) for p in protected_paths)
    
    if is_protected:
        try:
            # Get user info from cookies
            user = await get_current_user(request)
            
            if not user:
                print(f"Auth: No user found in cookies for path {path}")
                return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
            
            print(f"Auth: User authenticated as {user.get('name')} ({user.get('user_type')})")
                
            # Check role for doctor routes
            if path.startswith("/portal") and user["user_type"] != "doctor":
                print(f"Auth: Access denied - user type {user['user_type']} trying to access doctor route")
                return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
                
            # Check role for patient routes
            if path.startswith("/patient-dashboard") and user["user_type"] != "patient":
                print(f"Auth: Access denied - user type {user['user_type']} trying to access patient route")
                return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
                
        except Exception as e:
            print(f"Auth middleware error: {str(e)}")
            import traceback
            print(traceback.format_exc())
            return RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
    
    # Continue processing
    response = await call_next(request)
    return response

# Add this simple test route to check if cookies are working
@app.get("/test-cookies")
async def test_cookies(request: Request):
    # Get cookies
    user_cookie = request.cookies.get("user_info")
    token_cookie = request.cookies.get("access_token")
    
    # If cookies don't exist, set some test cookies
    if not user_cookie or not token_cookie:
        test_user = {"name": "Test User", "role": "tester"}
        response = {"message": "Test cookies set!", "status": "new"}
        
        # Create a response with cookies
        resp = RedirectResponse(url="/test-cookies", status_code=status.HTTP_303_SEE_OTHER)
        resp.set_cookie(
            key="user_info",
            value=encrypt_data(test_user),
            httponly=True,
            max_age=300,  # 5 minutes
            secure=False,
            samesite="lax"
        )
        resp.set_cookie(
            key="access_token",
            value="test_token_123",
            httponly=True,
            max_age=300,
            secure=False,
            samesite="lax"
        )
        return resp
    
    # If cookies exist, try to decrypt and return them
    try:
        user_data = decrypt_data(user_cookie)
        return {
            "message": "Cookies found!",
            "status": "existing",
            "user_data": user_data,
            "token": token_cookie[:10] + "..." # Show just the beginning of the token
        }
    except Exception as e:
        return {
            "message": "Error decrypting cookies",
            "error": str(e)
        }

# Run application:
if __name__ == "__main__":
    # Get the port from environment variable or use 8000 as default
    port = int(os.environ.get("PORT", 8000))
    
    # Start the application
    uvicorn.run(app, host="0.0.0.0", port=port)