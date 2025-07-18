import uvicorn
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app.main import app

if __name__ == "__main__":
    uvicorn.run(
        "app.main:app", 
        host="localhost", 
        port=8000, 
        reload=False, 
        log_level="info",
        timeout_keep_alive=300,  # 5분
        timeout_graceful_shutdown=300  # 5분
    )
