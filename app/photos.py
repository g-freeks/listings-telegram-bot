"""Downloads Telegram photo messages into a job's working directory."""
from pathlib import Path
from typing import List

from telegram import Message


async def download_photos(messages: List[Message], cwd: Path) -> List[str]:
    """Saves the highest-resolution image from each message as photo_NN.jpg
    under cwd and returns the saved filenames in order."""
    cwd.mkdir(parents=True, exist_ok=True)
    filenames = []
    for i, msg in enumerate(messages, start=1):
        photo = msg.photo[-1]
        file = await msg.get_bot().get_file(photo.file_id)
        filename = f"photo_{i:02d}.jpg"
        await file.download_to_drive(str(cwd / filename))
        filenames.append(filename)
    return filenames
