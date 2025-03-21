import sqlite3
import os
from tabulate import tabulate
import argparse

def execute_query(query, db_path="database/echomind.sqlite"):
    """Execute a query and display results in a neatly formatted table"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    try:
        cursor.execute(query)
        
        # For SELECT queries, fetch and display results
        if query.strip().upper().startswith("SELECT"):
            # Get column names
            column_names = [description[0] for description in cursor.description]
            
            # Fetch rows (limit to 100 for display purposes)
            rows = cursor.fetchmany(100)
            
            # Print formatted table
            if rows:
                print("\n" + tabulate(rows, headers=column_names, tablefmt="grid"))
                print(f"Showing up to 100 rows. Total rows: {len(rows)}")
            else:
                print("No results found.")
        else:
            # For non-SELECT queries, commit and show affected rows
            conn.commit()
            print(f"Query executed successfully. Rows affected: {cursor.rowcount}")
    
    except sqlite3.Error as e:
        print(f"SQLite error: {e}")
    finally:
        conn.close()

def show_tables(db_path="database/echomind.sqlite"):
    """List all tables in the database"""
    query = "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name;"
    print("\n===== TABLES IN DATABASE =====")
    execute_query(query, db_path)

def show_table_schema(table_name, db_path="database/echomind.sqlite"):
    """Show the schema for a specific table"""
    query = f"PRAGMA table_info('{table_name}');"
    print(f"\n===== SCHEMA FOR TABLE: {table_name} =====")
    execute_query(query, db_path)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SQLite Database Explorer")
    parser.add_argument("-q", "--query", help="SQL query to execute")
    parser.add_argument("-t", "--tables", action="store_true", help="List all tables")
    parser.add_argument("-s", "--schema", help="Show schema for a specific table")
    
    args = parser.parse_args()
    
    db_path = os.path.join(os.path.dirname(__file__), "database", "echomind.sqlite")
    
    if args.query:
        execute_query(args.query, db_path)
    elif args.tables:
        show_tables(db_path)
    elif args.schema:
        show_table_schema(args.schema, db_path)
    else:
        # Interactive mode
        print("SQLite Database Explorer")
        print("Type 'exit' to quit, 'tables' to list tables, 'schema [table]' to show table schema")
        
        while True:
            cmd = input("\nEnter SQL query or command: ").strip()
            
            if cmd.lower() == 'exit':
                break
            elif cmd.lower() == 'tables':
                show_tables(db_path)
            elif cmd.lower().startswith('schema '):
                table = cmd[7:].strip()
                show_table_schema(table, db_path)
            elif cmd:
                execute_query(cmd, db_path)

"""
# List all tables
python db_explorer.py --tables

# Show schema for Messages table
python db_explorer.py --schema Messages

# Run a specific query
python db_explorer.py --query "SELECT * FROM Messages LIMIT 10"

# Or run in interactive mode
python db_explorer.py
"""