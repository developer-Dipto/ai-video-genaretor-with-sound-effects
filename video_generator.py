import json
import os
import requests
import numpy as np
from PIL import Image
# AudioFileClip এবং CompositeAudioClip ইম্পোর্ট করা হলো সাউন্ডের জন্য
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
import traceback

# API Configuration
API_KEY = os.getenv("API_KEY")
if not API_KEY or API_KEY == "":
    API_KEY = "01828567716"  # আপনার ব্যাকআপ কি

API_URL = "https://simple-ai-image-genaretor.deptoroy91.workers.dev/"

print(f"DEBUG: Using API Key starting with: {API_KEY[:3]}... (Total length: {len(API_KEY)})")

DIMENSIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}

# --- Helper Function for Time Parsing ---
def parse_time_to_seconds(time_input):
    """
    Converts 'MM:SS' string or numeric input to seconds (float).
    Examples: "1:13" -> 73.0, "0:05" -> 5.0, 10 -> 10.0
    """
    try:
        time_str = str(time_input)
        if ":" in time_str:
            parts = time_str.split(":")
            if len(parts) == 2:
                minutes = float(parts[0])
                seconds = float(parts[1])
                return (minutes * 60) + seconds
        return float(time_str)
    except Exception as e:
        print(f"Error parsing time '{time_input}': {e}")
        return 0.0

def generate_image(prompt, size_ratio, scene_n):
    print(f"Generating Scene {scene_n}...")
    
    headers = {
        "Content-Type": "application/json",
        "x-api-key": str(API_KEY).strip() 
    }
    
    payload = {
        "prompt": prompt,
        "size": size_ratio,
        "model": "@cf/black-forest-labs/flux-1-schnell"
    }
    
    try:
        response = requests.post(API_URL, json=payload, headers=headers, timeout=120)
        if response.status_code == 200:
            path = f"scene_{scene_n}.jpg"
            with open(path, "wb") as f:
                f.write(response.content)
            print(f"Success: Saved scene_{scene_n}.jpg")
            return path
        else:
            print(f"API Failed (Status {response.status_code}): {response.text}")
            return None
    except Exception as e:
        print(f"Request Error: {e}")
        return None

def apply_motion(clip, motion_type, size):
    w, h = size
    def effect(get_frame, t):
        img = Image.fromarray(get_frame(t))
        p = t / clip.duration
        s = 1.2 
        if motion_type == "zoom-in": s = 1.0 + (0.2 * p)
        elif motion_type == "zoom-out": s = 1.2 - (0.2 * p)
        nw, nh = int(w * s), int(h * s)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        ox, oy = (nw - w) / 2, (nh - h) / 2
        if motion_type == "pan-right": ox = (nw - w) * p
        elif motion_type == "pan-left": ox = (nw - w) * (1 - p)
        elif motion_type == "pan-down": oy = (nh - h) * p
        elif motion_type == "pan-up": oy = (nh - h) * (1 - p)
        return np.array(img.crop((ox, oy, ox + w, oy + h)).resize((w, h)))
    return clip.fl(effect)

def build_video():
    try:
        json_str = os.getenv("JSON_INPUT")
        if not json_str:
            print("ERROR: JSON_INPUT is empty.")
            return
        
        data = json.loads(json_str)
        ratio = data["global_settings"].get("ratio", "16:9")
        W, H = DIMENSIONS.get(ratio, (1920, 1080))
        
        # 1. Video Clips Processing
        video_clips = []
        for scene in data["scenes"]:
            img_path = generate_image(scene["bg_prompt"], ratio, scene["scene_n"])
            if img_path:
                c = ImageClip(img_path).set_duration(scene.get("duration", 5))
                c = apply_motion(c, scene.get("motion", "none"), (W, H))
                if scene.get("transition") == "crossfade": 
                    c = c.crossfadein(1.0)
                video_clips.append(c)
        
        if not video_clips:
            print("No video clips generated.")
            return

        final_video = concatenate_videoclips(video_clips, method="compose")
        
        # 2. Sound Effects Processing (NEW FEATURE)
        audio_clips = []
        
        # Check if soundEffects exists in JSON
        if "soundEffects" in data and isinstance(data["soundEffects"], list):
            print("Processing Sound Effects...")
            
            # Ensure assets directory logic handles missing folders gracefully
            assets_dir = "assets/soundEffects"
            
            for sfx in data["soundEffects"]:
                name = sfx.get("name")
                start_raw = sfx.get("start", 0)
                vol = float(sfx.get("volume", 0.5)) # Default volume 0.5 if missing
                
                start_time = parse_time_to_seconds(start_raw)
                
                # Check for both .mp3 and .wav extensions
                possible_paths = [
                    os.path.join(assets_dir, f"{name}.mp3"),
                    os.path.join(assets_dir, f"{name}.wav")
                ]
                
                found_path = None
                for p in possible_paths:
                    if os.path.exists(p):
                        found_path = p
                        break
                
                if found_path:
                    try:
                        # Load audio, set start time and volume
                        audioclip = AudioFileClip(found_path)
                        audioclip = audioclip.set_start(start_time).volumex(vol)
                        audio_clips.append(audioclip)
                        print(f"  [+] Added SFX: {name} at {start_time}s (Vol: {vol})")
                    except Exception as e:
                        print(f"  [!] Error loading SFX '{name}': {e}")
                else:
                    print(f"  [-] Warning: SFX file not found for '{name}' in {assets_dir}")

        # 3. Merge Audio and Video
        if audio_clips:
            # Combine all SFX clips
            composite_audio = CompositeAudioClip(audio_clips)
            
            # ভিডিওর দৈর্ঘ্যের চেয়ে অডিও বড় হলে কেটে ফেলা (যাতে ভিডিওর শেষে কালো স্ক্রিন না আসে)
            # তবে আপনার যদি ভিডিওর চেয়ে বড় অডিও প্রয়োজন না হয়, এই লাইনটি সেইফটি হিসেবে কাজ করবে
            if composite_audio.duration > final_video.duration:
                composite_audio = composite_audio.set_duration(final_video.duration)
            
            # Attach audio to video
            final_video = final_video.set_audio(composite_audio)
            print("Audio tracks merged successfully.")
        else:
            print("No audio tracks to merge.")

        # 4. Export Final Video
        final_video.write_videofile(
            "final_video.mp4", 
            fps=24, 
            codec="libx264", 
            audio_codec="aac", # Audio codec added
            preset="ultrafast", 
            threads=2
        )
        print("Video generated successfully!")

    except Exception as e:
        print(traceback.format_exc())

if __name__ == "__main__":
    build_video()
