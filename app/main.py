import os
import uuid
import shutil
import threading
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks, HTTPException
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.detector import SafetyDetector

# Initialize App
app = FastAPI(title="Real-Time Smart Traffic & Safety Monitoring")

# Paths Configuration
BASE_DIR = Path(__file__).resolve().parent.parent
TEMP_DIR = BASE_DIR / "temp"
UPLOAD_DIR = TEMP_DIR / "uploads"
PROCESSED_DIR = TEMP_DIR / "processed"

# Ensure directories exist
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Mount Static Files and Templates
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "app" / "static")), name="static")
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))

# Initialize detector
detector = SafetyDetector(
    base_model_path=str(BASE_DIR / "models" / "yolov8n.pt"),
    helmet_model_path=str(BASE_DIR / "models" / "best.pt")
)

# In-Memory Task Status Tracker
tasks_status = {}
tasks_lock = threading.Lock()

def update_task_progress(task_id, progress, frames_processed, total_frames, stats, status="processing", error=None):
    with tasks_lock:
        if task_id in tasks_status:
            tasks_status[task_id].update({
                "progress": progress,
                "frames_processed": frames_processed,
                "total_frames": total_frames,
                "stats": stats,
                "status": status,
                "error": error
            })

def run_detection_background(task_id: str, input_path: str, output_path: str):
    try:
        detector.process_video(
            input_path=input_path,
            output_path=output_path,
            task_id=task_id,
            update_progress=update_task_progress
        )
    except Exception as e:
        print(f"[Task {task_id}] Processing failed: {e}")
        update_task_progress(
            task_id=task_id,
            progress=0,
            frames_processed=0,
            total_frames=0,
            stats={},
            status="failed",
            error=str(e)
        )

# --- Routes ---

@app.get("/", response_class=HTMLResponse)
async def get_index():
    return FileResponse(str(BASE_DIR / "app" / "templates" / "index.html"))

@app.post("/upload")
async def upload_video(file: UploadFile = File(...), background_tasks: BackgroundTasks = None):
    # Validate extension
    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in [".mp4", ".avi", ".mov", ".mkv"]:
        raise HTTPException(status_code=400, detail="Unsupported video format. Upload .mp4, .avi, .mov, or .mkv")
        
    task_id = str(uuid.uuid4())
    input_filename = f"{task_id}{file_ext}"
    output_filename = f"{task_id}.mp4"
    
    input_path = UPLOAD_DIR / input_filename
    output_path = PROCESSED_DIR / output_filename
    
    # Save uploaded file
    try:
        with input_path.open("wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to save video: {str(e)}")
        
    # Initialize status
    with tasks_lock:
        tasks_status[task_id] = {
            "status": "processing",
            "progress": 0.0,
            "frames_processed": 0,
            "total_frames": 0,
            "stats": {
                "persons": 0,
                "motorcycles": 0,
                "helmets": 0,
                "violations": 0
            },
            "error": None
        }
        
    # Start background execution
    background_tasks.add_task(run_detection_background, task_id, str(input_path), str(output_path))
    
    return {"task_id": task_id, "status": "queued"}

@app.get("/status/{task_id}")
async def get_status(task_id: str):
    with tasks_lock:
        if task_id not in tasks_status:
            raise HTTPException(status_code=404, detail="Task not found")
        return tasks_status[task_id]

@app.get("/video/{task_id}")
async def get_video(task_id: str):
    output_path = PROCESSED_DIR / f"{task_id}.mp4"
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Processed video not found")
    return FileResponse(str(output_path), media_type="video/mp4")
