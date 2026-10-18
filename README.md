# YouTube Audio

A small local page for saving a YouTube video as MP3 or MP4. Search and file saving run on your computer through [yt-dlp](https://github.com/yt-dlp/yt-dlp) and ffmpeg.

GitHub Pages cannot run this. The page is only a front end. yt-dlp has to run on a machine you control.

Save only recordings you have the right to keep.

## Run it

Install the tools once:

```bash
brew install yt-dlp ffmpeg
```

Start the app:

```bash
python3 server.py
```

Open http://127.0.0.1:8787

Paste a YouTube link, or type a title and pick a result. Choose **Save MP3** or **Save MP4**. The browser downloads the file, and a copy stays in `downloads/`.
