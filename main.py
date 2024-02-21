from sys import argv
from convert import *
import os
from mutagen.easyid3 import EasyID3
from mutagen.id3 import ID3NoHeaderError
from mutagen.flac import FLAC

def main(args):
    print("Converting mp4 files to mp3 files")
    path, delete = parseArgs(args)
    mp4_to_mp3(path, delete)
    aiff_to_flac(path, delete)
    wma_to_mp3(path, delete)
    rename_track_titles(path)
    organize_files_by_artist_and_album(path)
    if delete:
        remove_empty_subdirectories(path)

def parseArgs(args):
    if len(args) > 1:
        path = args[1]
    if len(args) > 2:
        delete = args[2] == "delete"
    else:
        delete = False
    return path, delete

def rename_track_titles(directory):
    print("renaming track titles")
    for root, _, files in os.walk(directory):
        for file in files:
            if "track" in file or "Track" in file or "Spår" in file or "download" in file:
                file_path = os.path.join(root, file)
                try:
                    audio = None
                    if file.endswith(".mp3"):
                        audio = EasyID3(file_path)
                    elif file.endswith(".flac"):
                        audio = FLAC(file_path)

                    title = audio["title"][0]
                    if "/" in title:
                        title = title.replace("/", "-")

                    filename = title + "." + file.split(".")[1]
                    print(f"Renaming {file} to {filename}")
                    os.rename(file_path, os.path.join(root, filename))
                    print(f"Renamed {file} to {filename}")
                except (KeyError, IndexError, ID3NoHeaderError):
                    print(f"No Data for {file}")
                

def organize_files_by_artist_and_album(directory):
    print("organizing media files by artist")
    for root, dirs, files in os.walk(directory):
                for file in files:
                    if file.endswith(".mp3") or file.endswith(".m4a") or file.endswith(".mp4") or file.endswith(".flac") or file.endswith(".wma") or file.endswith(".aiff") or file.endswith(".wav"):
                        file_path = os.path.join(root, file)
                        artist = ""
                        try:
                            audio = None
                            if file.endswith(".mp3"):
                                audio = EasyID3(file_path)
                            elif file.endswith(".flac"):
                                audio = FLAC(file_path)
                            
                            if audio is not None:
                                if "albumartist" in audio:
                                    print("using album artist")
                                    artist = audio["albumartist"][0]
                                else:
                                    artist = audio["artist"][0]

                            else:
                                artist = "Unknown Artist"
                                print(f"Couldn't find artist for {file}")
                            
                        except (KeyError, IndexError, ID3NoHeaderError) as e:
                            artist = "Unknown Artist"
                            print(f"Couldn't find artist for {file}")
                            print(f"Error: {e}")

                        album = ""
                        try:
                            audio = None
                            if file.endswith(".mp3"):
                                audio = EasyID3(file_path)
                            elif file.endswith(".flac"):
                                audio = FLAC(file_path)
                            
                            if audio is not None:
                                album = audio["album"][0]
                            else:
                                album = "Unknown Album"
                                print(f"Couldn't find album for {file}")
                            
                        except (KeyError, IndexError, ID3NoHeaderError) as e:
                            album = "Unknown Album"
                            print(f"Couldn't find album for {file}")
                            print(f"Error: {e}")
                        


                        print(f"Moving {file} to {artist}")
                        artist.replace("/", "-")
                        album.replace("/", "-")
                        artist_path = os.path.join(directory, artist)
                        album_path = os.path.join(artist_path, album)
                        os.makedirs(artist_path, exist_ok=True)
                        os.makedirs(album_path, exist_ok=True)
                        os.rename(file_path, os.path.join(album_path, file))
                        print(f"Moved {file} to {album_path}")

def remove_empty_subdirectories(directory):
    print("Removing empty subdirectories")
    changed = True
    while changed:
        changed = False
        for root, dirs, _ in os.walk(directory, topdown=False):
            for dir in dirs:
                dir_path = os.path.join(root, dir)
                if not os.listdir(dir_path):
                    changed = True
                    print(f"Removing empty subdirectory: {dir_path}")
                    os.rmdir(dir_path)
                    print(f"Removed empty subdirectory: {dir_path}")
    print("Empty subdirectories removed")


if __name__ == "__main__":
    main(argv)
