import os
import subprocess
import time
import signal
import sys
import platform

# Track subprocesses
processes = []

def signal_handler(sig, frame):
    """Handle Ctrl+C signal to gracefully shut down all processes"""
    print("\nShutting down all processes...")
    for process in processes:
        if process.poll() is None:  # Check if process is still running
            try:
                if platform.system() == "Windows":
                    process.terminate()
                else:
                    process.send_signal(signal.SIGTERM)
                print(f"Terminated process {process.pid}")
            except Exception as e:
                print(f"Error terminating process: {e}")
    sys.exit(0)

def init_database():
    """Initialize the database before starting services"""
    print("Initializing database...")
    try:
        from telegram_bot import ensure_database_tables
        ensure_database_tables()
        print("Database initialized successfully")
        return True
    except Exception as e:
        print(f"Error initializing database: {e}")
        import traceback
        traceback.print_exc()
        return False

def start_webapp():
    """Start the FastAPI web application"""
    print("Starting FastAPI web application...")
    web_process = subprocess.Popen(
        ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    processes.append(web_process)
    return web_process

def start_scheduler():
    """Start the Telegram scheduler for daily check-ins"""
    print("Starting Telegram scheduler...")
    scheduler_process = subprocess.Popen(
        ["python", "telegram_scheduler.py"], 
        stdout=subprocess.PIPE, 
        stderr=subprocess.STDOUT,
        universal_newlines=True
    )
    processes.append(scheduler_process)
    return scheduler_process

def monitor_processes():
    """Monitor process outputs and restart if needed"""
    while True:
        try:
            for i, process in enumerate(processes[:]):
                if process.poll() is not None:
                    print(f"Process {process.pid} exited with code {process.returncode}")
                    
                    # Log specific info based on process type
                    process_name = "Web app" if i == 0 else "Scheduler"
                    print(f"⚠️ {process_name} process terminated unexpectedly with code {process.returncode}")
                    
                    # Restart process if needed
                    if i == 0:
                        print("Restarting FastAPI web application...")
                        processes[0] = start_webapp()
                    elif i == 1:
                        print("Restarting Telegram scheduler...")
                        processes[1] = start_scheduler()
                
                # Read and display output
                try:
                    output = process.stdout.readline() if process.stdout else ""
                    if output:
                        print(output.strip())
                except Exception as e:
                    print(f"Error reading process output: {e}")
            
            time.sleep(0.1)
        except Exception as e:
            print(f"Error in monitor_processes: {e}")
            # Continue monitoring even if an error occurs
            time.sleep(1)

if __name__ == "__main__":
    # Register signal handler for graceful shutdown
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    print("EchoMind Application Startup")
    print("============================")
    
    # Initialize database first
    if not init_database():
        print("Failed to initialize database. Application may not work correctly.")
    
    # Start web application
    web_process = start_webapp()
    processes.append(web_process)
    
    # Start scheduler
    scheduler_process = start_scheduler()
    processes.append(scheduler_process)

    try:
        # Monitor subprocesses
        monitor_processes()
    except KeyboardInterrupt:
        signal_handler(None, None)