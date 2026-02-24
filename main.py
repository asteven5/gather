
import os
import subprocess
import shutil
from pathlib import Path
from fastapi import FastAPI, UploadFile, File, BackgroundTasks
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn
import datetime
import pytz
from PIL import Image, ImageDraw, ImageFont
import concurrent.futures

app = FastAPI()

# Setup directories
BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "output"
LIBRARY_DIR = BASE_DIR / "library"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)
LIBRARY_DIR.mkdir(exist_ok=True)


def get_creation_date_raw(file_path):
    # Internal helper to get the raw datetime object
    try:
        cst = pytz.timezone('US/Central')
        cmd = ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries", "format_tags=com.apple.quicktime.creationdate", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
        result = subprocess.run(cmd, capture_output=True, text=True)
        date_str = result.stdout.strip()
        if not date_str:
            cmd = ["ffprobe", "-v", "quiet", "-select_streams", "v:0", "-show_entries", "format_tags=creation_time", "-of", "default=noprint_wrappers=1:nokey=1", str(file_path)]
            result = subprocess.run(cmd, capture_output=True, text=True)
            date_str = result.stdout.strip()
        
        if date_str:
            dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.astimezone(cst)
    except: pass
    return datetime.datetime.fromtimestamp(os.path.getmtime(file_path), tz=pytz.utc).astimezone(pytz.timezone('US/Central'))


def get_creation_date(file_path):
    try:
        # Central Time Zone
        cst = pytz.timezone('US/Central')
        
        # Tags to check, prioritizing the most accurate local ones
        tags_to_check = [
            "format_tags=com.apple.quicktime.creationdate",
            "format_tags=creation_time",
            "stream_tags=creation_time",
            "format_tags=datetime"
        ]
        
        for tag in tags_to_check:
            cmd = [
                "ffprobe", "-v", "quiet", "-select_streams", "v:0",
                "-show_entries", tag,
                "-of", "default=noprint_wrappers=1:nokey=1",
                str(file_path)
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)
            date_str = result.stdout.strip()
            
            if date_str:
                print(f"🐶 DEBUG: Raw date string from {tag}: {date_str}")
                try:
                    # Handle Z and other formats
                    if date_str.endswith('Z'):
                        dt = datetime.datetime.fromisoformat(date_str.replace('Z', '+00:00'))
                    else:
                        dt = datetime.datetime.fromisoformat(date_str)
                    
                    # If it's naive (no timezone), assume it was recorded in CST or UTC depending on tag
                    if dt.tzinfo is None:
                        if 'creation_time' in tag:
                            dt = pytz.utc.localize(dt)
                        else:
                            dt = cst.localize(dt)
                    
                    # Convert to CST finally
                    local_dt = dt.astimezone(cst)
                    return local_dt.strftime("%B %d, %Y %I:%M %p")
                except Exception as e:
                    print(f"🐶 DEBUG: Parse failed for {date_str}: {e}")
                    continue

    except Exception as e:
        print(f"Error getting date: {e}")
    
    # Absolute fallback to file modification time
    ctime = os.path.getmtime(file_path)
    dt = datetime.datetime.fromtimestamp(ctime, tz=pytz.utc).astimezone(pytz.timezone('US/Central'))
    return dt.strftime("%B %d, %Y %I:%M %p")


def create_date_image(text, output_path):
    # Create a transparent image for the overlay
    # 1920x1080 is our target resolution
    img = Image.new('RGBA', (1920, 1080), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    
    # Try to use a nice font, fallback to default
    try:
        # Mac default font path
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 60)
    except:
        font = ImageFont.load_default()

    # Draw a semi-transparent black box for readability
    # Position: Bottom Left
    bbox = draw.textbbox((40, 980), text, font=font)
    draw.rectangle([bbox[0]-10, bbox[1]-5, bbox[2]+10, bbox[3]+5], fill=(0,0,0,100))
    draw.text((40, 980), text, font=font, fill=(255, 255, 255, 255))
    
    img.save(output_path)
    return output_path

def process_single_video(i, name, date_text):
    input_path = UPLOAD_DIR / name
    output_path = UPLOAD_DIR / f"proc_{i}_{name}"
    overlay_img_path = UPLOAD_DIR / f"overlay_{i}.png"
    
    print(f"🐶 STARTING: Processing {name} (Part {i+1})...")
    
    # Create the date overlay image
    create_date_image(date_text, overlay_img_path)
    
    # Strategy 1: Mac Hardware Acceleration with Pro Cinema Tune-up
    # Explicitly map and re-encode audio to standard stereo AAC to ensure compatibility
    strategies = [
        ["ffmpeg", "-y", "-i", str(input_path), "-i", str(overlay_img_path),
         "-filter_complex", "[0:v:0]scale=1920:1080,unsharp=5:5:1.0:5:5:0.0,eq=contrast=1.1:saturation=1.2[v];[v][1:v:0]overlay=0:0",
         "-map", "[v]", "-map", "0:a:0?", "-c:v", "h264_videotoolbox", "-b:v", "8000k", "-profile:v", "high", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(output_path)],
        # Strategy 2: Ultra-fast Software Encoding (Fallback)
        ["ffmpeg", "-y", "-i", str(input_path), "-i", str(overlay_img_path),
         "-filter_complex", "[0:v:0]scale=1920:1080,unsharp=5:5:1.0:5:5:0.0,eq=contrast=1.1:saturation=1.2[v];[v][1:v:0]overlay=0:0",
         "-map", "[v]", "-map", "0:a:0?", "-c:v", "libx264", "-preset", "slow", "-crf", "18", "-c:a", "aac", "-ar", "44100", "-ac", "2", str(output_path)]
    ]



    for cmd in strategies:
        print(f"🐶 BARK: Trying strategy with command: {' '.join(cmd[:10])}...")
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            print(f"🐶 SUCCESS: Finished {name}!")
            # Cleanup temp files
            try: 
                os.remove(overlay_img_path)
            except: pass
            return output_path
        else:
            print(f"🐶 WHIMPER: Strategy failed for {name}.")
            print(f"🐶 ERROR LOG:\n{res.stderr}")
    
    return None


def process_videos(filenames):
    # 1. Parallel Processing - use all available cores to process videos simultaneously!
    processed_files_map = {}
    with concurrent.futures.ThreadPoolExecutor() as executor:
        futures = {
            executor.submit(process_single_video, i, name, get_creation_date(UPLOAD_DIR / name)): i 
            for i, name in enumerate(filenames)
        }
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            path = future.result()
            if path:
                processed_files_map[idx] = path
            else:
                raise Exception(f"Video processing failed for index {idx}")

    processed_files = [processed_files_map[i] for i in range(len(filenames))]

    # 2. Create concat list
    concat_list_path = UPLOAD_DIR / "concat.txt"
    with open(concat_list_path, "w") as f:
        for p in processed_files:
            # Use absolute paths and escape single quotes for ffmpeg
            safe_path = str(p.absolute()).replace("'", "'\\''")
            f.write(f"file '{safe_path}'\n")

    # 3. Concatenate
    final_output = OUTPUT_DIR / "final_movie.mp4"
    print(f"DEBUG: Merging into {final_output}")
    
    # We now ALWAYS re-encode during concat to ensure audio is perfectly synced and preserved
    # Hardware accelerated re-encoding is used for speed
    cmd = [
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(concat_list_path),
        "-c:v", "h264_videotoolbox", "-b:v", "8000k", "-profile:v", "high",
        "-c:a", "aac", "-ar", "44100", "-ac", "2", str(final_output)
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    
    if res.returncode != 0:
        print("DEBUG: Hardware merge failed, trying software-based high-quality merge...")
        cmd = [
            "ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list_path),
            "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-c:a", "aac", "-ar", "44100", "-ac", "2", str(final_output)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            print(f"FFMPEG ERROR (Stage 3): {res.stderr}")
            raise Exception(f"Failed to merge videos: {res.stderr}")
            raise Exception(f"Failed to merge videos: {res.stderr}")
    
    if not final_output.exists():
        raise Exception("Final movie file was not created!")
        
    return final_output

@app.get("/", response_class=HTMLResponse)
async def index():
    with open(BASE_DIR / "index.html", "r") as f:
        return f.read()

@app.post("/save-to-library")
async def save_to_library(data: dict):
    year = data.get("year")
    title = data.get("title", "My Movie")
    temp_file = OUTPUT_DIR / "final_movie.mp4"
    
    if not temp_file.exists():
        return {"status": "error", "message": "No file to save"}
        
    year_dir = LIBRARY_DIR / year
    year_dir.mkdir(exist_ok=True)
    
    # Create a safe filename
    safe_title = "".join([c for c in title if c.isalnum() or c in (' ', '_')]).rstrip()
    final_path = year_dir / f"{safe_title}.mp4"
    
    shutil.copy(temp_file, final_path)
    
    # Generate thumbnail
    thumb_path = year_dir / f"{safe_title}.jpg"
    cmd = [
        "ffmpeg", "-y", "-i", str(final_path),
        "-ss", "00:00:01", "-vframes", "1",
        "-vf", "scale=400:400:force_original_aspect_ratio=increase,crop=400:400",
        str(thumb_path)
    ]
    subprocess.run(cmd)
    
    return {"status": "success"}

@app.post("/upload")
async def upload_videos(background_tasks: BackgroundTasks, files: list[UploadFile] = File(...)):
    print("🐶 MEGA BARK: BUTTON CLICKED! Starting the process...")
    try:
        # Cleanup old sessions
        for old_file in UPLOAD_DIR.glob("*"):
            try: os.remove(old_file)
            except: pass
            
        filenames = []
        for file in files:
            file_path = UPLOAD_DIR / file.filename
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            filenames.append(file.filename)
        
        # Sort files chronologically based on metadata date
        main_dt = get_creation_date_raw(UPLOAD_DIR / filenames[0])
        year = str(main_dt.year)

        filenames.sort(key=lambda x: get_creation_date(UPLOAD_DIR / x))

        final_file = process_videos(filenames)
        return {"status": "success", "year": year}
    except Exception as e:
        print(f"CRITICAL ERROR DURING UPLOAD/PROCESS: {e}")
        import traceback
        traceback.print_exc()
        return {"status": "error", "message": str(e)}

@app.get("/library-data")
async def get_library_data():
    years = {}
    for year_folder in sorted(LIBRARY_DIR.iterdir(), reverse=True):
        if year_folder.is_dir():
            videos = []
            for f in sorted(year_folder.glob("*.mp4"), reverse=True):
                thumb = f.stem + ".jpg"
                videos.append({
                    "title": f.stem,
                    "filename": f.name,
                    "thumb": thumb if (year_folder / thumb).exists() else None
                })
            years[year_folder.name] = videos
    return years

@app.get("/library/{year}/{filename}")
async def get_library_video(year: str, filename: str):
    return FileResponse(LIBRARY_DIR / year / filename)

@app.post("/update-thumbnail")
async def update_thumbnail(data: dict):
    year = data.get("year")
    filename = data.get("filename")
    timestamp = data.get("timestamp", "00:00:01")
    
    video_path = LIBRARY_DIR / year / filename
    thumb_path = LIBRARY_DIR / year / (Path(filename).stem + ".jpg")
    
    # Generate new thumbnail at specific timestamp
    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-ss", timestamp, "-vframes", "1",
        "-vf", "scale=400:400:force_original_aspect_ratio=increase,crop=400:400",
        str(thumb_path)
    ]
    subprocess.run(cmd)
    return {"status": "success"}

@app.get("/download")
async def download():
    return FileResponse(OUTPUT_DIR / "final_movie.mp4", filename="chronicle.mp4")

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
