#!/bin/bash

# Get a list of files ending with "mp3.mp3"
files=()
while IFS= read -r -d '' file; do
    files+=("$file")
done < <(find . -type f -name "*mp3.mp3" -print0)

# Loop through each file and rename it
for file in "${files[@]}"; do
    new_name=$(echo "$file" | sed 's/mp3.mp3$/.mp3/')
    mv "$file" "$new_name"
done