import sqlite3
import os

def update_database_schema():
    """Update database schema to add necessary columns"""
    db_path = os.path.join("database", "echomind.sqlite")
    
    if not os.path.exists(db_path):
        print(f"Database file not found at {db_path}")
        return
    
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # Add the is_first_login column to User table
    try:
        cursor.execute("PRAGMA table_info(User)")
        columns = cursor.fetchall()
        column_names = [column[1] for column in columns]
        
        if "is_first_login" not in column_names:
            print("Adding is_first_login column to User table...")
            cursor.execute("ALTER TABLE User ADD COLUMN is_first_login BOOLEAN DEFAULT 1")
            print("Success!")
        else:
            print("is_first_login column already exists in User table")
        
        # Add telegram_verification_code to Patient table
        cursor.execute("PRAGMA table_info(Patient)")
        patient_columns = cursor.fetchall()
        patient_column_names = [column[1] for column in patient_columns]
        
        if "telegram_verification_code" not in patient_column_names:
            print("Adding telegram_verification_code column to Patient table...")
            cursor.execute("ALTER TABLE Patient ADD COLUMN telegram_verification_code TEXT")
            print("Success!")
        else:
            print("telegram_verification_code column already exists in Patient table")
        
        conn.commit()
        print("Database schema updated successfully")
    except sqlite3.Error as e:
        print(f"Database error: {e}")
        conn.rollback()
    finally:
        conn.close()

if __name__ == "__main__":
    update_database_schema()