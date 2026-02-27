import json
import os
import requests
import numpy as np
from PIL import Image
from moviepy.editor import ImageClip, concatenate_videoclips, AudioFileClip, CompositeAudioClip
import traceback

# API Configuration
API_KEY = os.getenv("API_KEY", "01828567716") # Fallback key
API_URL = "https://simple-ai-image-genaretor.deptoroy91.workers.dev/"
DIMENSIONS = {"16:9": (1920, 1080), "9:16": (1080, 1920)}

# --- Helper: Time Parser ---
def parse_time(val):
    """Converts 'MM:SS' or int/float to seconds"""
    if val is None: return 0
    try:
        val = str(val)
        if ":" in val:
            m, s = val.split(":")
            return (float(m) * 60) + float(s)
        return float(val)
    except:
        return 0.0

# --- Helper: Generate Image ---
def generate_image(prompt, ratio, index):
    print(f"Generating Scene {index}...")
    headers = {"Content-Type": "application/json", "x-api-key": str(API_KEY).strip()}
    payload = {"prompt": prompt, "size": ratio, "model": "@cf/black-forest-labs/flux-1-schnell"}
    
    try:
        # Check if image already exists (caching for local testing)
        filename = f"scene_{index}.jpg"
        if os.path.exists(filename):
            print(f"Skipping download, {filename} exists.")
            return filename

        response = requests.post(API_URL, json=payload, headers=headers, timeout=120)
        if response.status_code == 200:
            with open(filename, "wb") as f:
                f.write(response.content)
            return filename
        else:
            print(f"API Error {response.status_code}: {response.text}")
            return None
    except Exception as e:
        print(f"Request Error: {e}")
        return None

# --- Helper: Motion Effect ---
def apply_motion(clip, motion, size):
    w, h = size
    def effect(get_frame, t):
        img = Image.fromarray(get_frame(t))
        p = t / clip.duration
        s = 1.0
        if motion == "zoom-in": s = 1.0 + (0.15 * p) # Smooth zoom
        elif motion == "zoom-out": s = 1.15 - (0.15 * p)
        
        nw, nh = int(w * s), int(h * s)
        img = img.resize((nw, nh), Image.Resampling.LANCZOS)
        
        # Center crop logic
        ox, oy = (nw - w) / 2, (nh - h) / 2
        
        if motion == "pan-right": ox = (nw - w) * p
        elif motion == "pan-left": ox = (nw - w) * (1 - p)
        elif motion == "pan-up": oy = (nh - h) * (1 - p)
        elif motion == "pan-down": oy = (nh - h) * p
        
        return np.array(img.crop((ox, oy, ox + w, oy + h)).resize((w, h)))
    
    return clip.fl(effect) if motion != "none" else clip

# --- MAIN BUILDER FUNCTION ---
def build_video(input_data=None):
    try:
        # 1. Handle Input (Object vs JSON String)
        data = {}
        if input_data:
            # If function is called with a Dictionary/Object directly
            data = input_data if isinstance(input_data, dict) else json.loads(input_data)
        else:
            # Fallback to Environment Variable (GitHub Actions)
            json_str = os.getenv("JSON_INPUT")
            if not json_str:
                print("❌ Error: No input provided.")
                return
            data = json.loads(json_str)

        # Settings
        ratio = data.get("global_settings", {}).get("ratio", "16:9")
        W, H = DIMENSIONS.get(ratio, (1920, 1080))
        
        # 2. Process Scenes (Visuals)
        video_clips = []
        scenes = data.get("scenes", [])
        
        # 'enumerate' gives us the index (0, 1, 2...), so we don't need scene_n input
        for idx, scene in enumerate(scenes):
            scene_num = idx + 1 # 1, 2, 3...
            img_path = generate_image(scene["bg_prompt"], ratio, scene_num)
            
            if img_path:
                dur = parse_time(scene.get("duration", 5))
                c = ImageClip(img_path).set_duration(dur)
                c = apply_motion(c, scene.get("motion", "none"), (W, H))
                
                if scene.get("transition") == "crossfade":
                    c = c.crossfadein(1.0)
                
                video_clips.append(c)

        if not video_clips:
            print("❌ No scenes generated.")
            return

        final_video = concatenate_videoclips(video_clips, method="compose")
        print(f"🎥 Video created. Duration: {final_video.duration}s")

        # 3. Process Sound Effects (Advanced)
        audio_clips = []
        assets_dir = "assets/soundEffects"
        
        for sfx in data.get("soundEffects", []):
            name = sfx.get("name")
            start_t = parse_time(sfx.get("start", 0))
            vol = float(sfx.get("volume", 0.5))
            
            # Optional Parameters
            duration = sfx.get("duration") # Cut audio length
            fade_in = sfx.get("fade_in", 0)
            fade_out = sfx.get("fade_out", 0)

            # Find file
            f_path = None
            for ext in [".mp3", ".wav", ".ogg"]:
                p = os.path.join(assets_dir, name + ext)
                if os.path.exists(p):
                    f_path = p
                    break
            
            if f_path:
                try:
                    ac = AudioFileClip(f_path).volumex(vol)
                    
                    # Apply Trimming (Custom Duration)
                    if duration:
                        dur_sec = parse_time(duration)
                        if dur_sec < ac.duration:
                            ac = ac.subclip(0, dur_sec)
                    
                    # Apply Fades
                    if fade_in > 0: ac = ac.audio_fadein(fade_in)
                    if fade_out > 0: ac = ac.audio_fadeout(fade_out)
                    
                    # Set Start Time
                    ac = ac.set_start(start_t)
                    audio_clips.append(ac)
                    print(f"✅ Added SFX: {name} | Start: {start_t}s")
                except Exception as e:
                    print(f"⚠️ Error with SFX {name}: {e}")
            else:
                print(f"❌ SFX File not found: {name}")

        # 4. Merge Audio & Export
        if audio_clips:
            comp_audio = CompositeAudioClip(audio_clips)
            # Clip audio to match video duration prevents black frames/silence at end
            if comp_audio.duration > final_video.duration:
                comp_audio = comp_audio.set_duration(final_video.duration)
            final_video = final_video.set_audio(comp_audio)

        final_video.write_videofile(
            "final_video.mp4", 
            fps=24, 
            codec="libx264", 
            audio_codec="aac",
            preset="ultrafast", 
            threads=2
        )
        print("🎉 Render Complete: final_video.mp4")

    except Exception as e:
        print(traceback.format_exc())

# --- ENTRY POINT ---
if __name__ == "__main__":
    # GitHub Actions will use env var, but you can also pass a dict directly here for local testing
    build_video()
