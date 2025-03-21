-- Creating the User table to store both patients and doctors/nurses
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
);

-- Creating the Patient table, which extends the User table
CREATE TABLE IF NOT EXISTS Patient (
    Patient_ID INTEGER PRIMARY KEY,
    condition TEXT,
    timezone TEXT DEFAULT 'UTC',
    chat_time TEXT,
    Cumulative_Score REAL DEFAULT 0.00,
    Day_On_Day_Score REAL DEFAULT 0.00,
    ThreeDay_Day_On_Day_Score REAL DEFAULT 0.00,
    FOREIGN KEY (Patient_ID) REFERENCES User(User_ID) ON DELETE CASCADE
);

-- Creating the Doctor/Nurse table, which extends the User table
CREATE TABLE IF NOT EXISTS Doctor_Nurse (
    Doctor_ID INTEGER PRIMARY KEY,
    Specialty TEXT,
    License_Number TEXT NOT NULL,
    Institution TEXT NOT NULL,
    FOREIGN KEY (Doctor_ID) REFERENCES User(User_ID) ON DELETE CASCADE
);

-- Creating the Session_Scores table with separate Date and Timestamp columns
CREATE TABLE IF NOT EXISTS Session_Scores (
    Session_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    User_ID INTEGER,
    Date TEXT,  -- Separate date field (YYYY-MM-DD format)
    Timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    Sentiment_Score REAL,
    FOREIGN KEY (User_ID) REFERENCES User(User_ID) ON DELETE CASCADE
);

-- Creating the Messages table to store conversations
CREATE TABLE IF NOT EXISTS Messages (
    Message_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    Session_ID INTEGER,
    Question TEXT NOT NULL,
    Response TEXT NOT NULL,
    Timestamp TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    Sentiment_Score REAL DEFAULT 0.50,
    Patient_ID INTEGER,
    FOREIGN KEY (Patient_ID) REFERENCES User(User_ID) ON DELETE CASCADE,
    FOREIGN KEY (Session_ID) REFERENCES Session_Scores(Session_ID) ON DELETE SET NULL
);

-- Creating the Doctor_Patient relationship table
CREATE TABLE IF NOT EXISTS Doctor_Patient (
    Doctor_ID INTEGER,
    Patient_ID INTEGER,
    Start_Date TEXT DEFAULT (date('now')),
    PRIMARY KEY (Doctor_ID, Patient_ID),
    FOREIGN KEY (Doctor_ID) REFERENCES Doctor_Nurse(Doctor_ID) ON DELETE CASCADE,
    FOREIGN KEY (Patient_ID) REFERENCES Patient(Patient_ID) ON DELETE CASCADE
);

CREATE TABLE Alerts (
    Alert_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    Patient_ID INTEGER NOT NULL,
    Alert_Type TEXT NOT NULL,
    Message TEXT,
    Created_At TIMESTAMP DEFAULT (datetime('now', 'localtime')),
    Resolved_At TIMESTAMP,
    Status TEXT DEFAULT 'pending',
    FOREIGN KEY (Patient_ID) REFERENCES User(User_ID)
);