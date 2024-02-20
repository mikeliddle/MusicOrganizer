import os
import subprocess

def mp4_to_mp3(directory, delete=False):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".mp4") or file.endswith(".m4a"):
                mp4_path = os.path.join(root, file)
                mp3_path = os.path.splitext(mp4_path)[0] + ".mp3"
                if not os.path.exists(mp3_path):
                    print(f"Converting {mp4_path} to {mp3_path}")
                    result = subprocess.run(["ffmpeg", "-i", mp4_path, mp3_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode == 0:
                        print("Conversion succeeded")
                        if delete:
                            os.remove(mp4_path)
                            print(f"Deleted {mp4_path}")
                        print(f"Converted {mp4_path} to {mp3_path}")
                    else:
                        print("Conversion failed")
                    
                
def aiff_to_flac(directory, delete=False):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".aiff"):
                aiff_path = os.path.join(root, file)
                flac_path = os.path.splitext(aiff_path)[0] + ".flac"
                if not os.path.exists(flac_path):
                    print(f"Converting {aiff_path} to {flac_path}")
                    result = subprocess.run(["ffmpeg", "-i", aiff_path, flac_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode == 0:
                        print("Conversion succeeded")
                        if delete:
                            os.remove(aiff_path)
                            print(f"Deleted {aiff_path}")
                        print(f"Converted {aiff_path} to {flac_path}")
                    else:
                        print("Conversion failed")

def wav_to_flac(directory, delete=False):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".wav"):
                wav_path = os.path.join(root, file)
                flac_path = os.path.splitext(wav_path)[0] + ".flac"
                if not os.path.exists(flac_path):
                    print(f"Converting {wav_path} to {flac_path}")
                    result = subprocess.run(["ffmpeg", "-i", wav_path, flac_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode == 0:
                        print("Conversion succeeded")
                        if delete:
                            os.remove(wav_path)
                            print(f"Deleted {wav_path}")
                        print(f"Converted {wav_path} to {flac_path}")
                    else:
                        print("Conversion failed")

def wma_to_mp3(directory, delete=False):
    for root, _, files in os.walk(directory):
        for file in files:
            if file.endswith(".wma"):
                wma_path = os.path.join(root, file)
                mp3_path = os.path.splitext(wma_path)[0] + ".mp3"
                if not os.path.exists(mp3_path):
                    print(f"Converting {wma_path} to {mp3_path}")
                    result = subprocess.run(["ffmpeg", "-i", wma_path, mp3_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    if result.returncode == 0:
                        print("Conversion succeeded")
                        if delete:
                            os.remove(wma_path)
                            print(f"Deleted {wma_path}")
                        print(f"Converted {wma_path} to {mp3_path}")
                    else:
                        print("Conversion failed")