from flask import Flask, request, send_file, jsonify
import requests
import json
from mutagen.mp4 import MP4, MP4Cover
from io import BytesIO
import tempfile
import os
import logging

app = Flask(__name__)

# Configure logging for production
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s %(message)s')


def extract_value(text, start_marker, end_marker):
    try:
        start_index = text.find(start_marker)
        end_index = text.find(end_marker, start_index)

        if start_index != -1 and end_index != -1:
            return text[start_index + len(start_marker):end_index]
        else:
            return "Unknown"
    except Exception as e:
        logging.error(f"An error occurred in extract_value: {e}")
        return "Unknown"


def extract_track_url(response_text):
    try:
        mime_index = response_text.find("mime_type=audio_mp4")
        if mime_index == -1:
            return "Unknown"

        start_index = response_text.rfind(":", 0, mime_index) + 1
        end_index = response_text.find(",", mime_index)

        raw_url = response_text[start_index:end_index].strip().strip('"')

        track_url = json.loads(f'"{raw_url}"')
        if track_url.startswith("//"):
            track_url = f"https:{track_url}"

        return track_url
    except Exception as e:
        logging.error(f"An error occurred while extracting track URL: {e}")
        return "Unknown"


def extract_and_log_data(response_text):
    try:
        track_name = extract_value(response_text, '"trackName":"', '","')
        logging.info(f"Track Name: {track_name}")

        artist_name = extract_value(response_text, '"artistName":"', '","')
        logging.info(f"Artist Name: {artist_name}")

        cover_url = extract_value(response_text, '"coverURL":"', '","')
        cover_url = json.loads(f'"{cover_url}"')
        logging.info(f"Cover URL: {cover_url}")

        track_url = extract_track_url(response_text)
        logging.info(f"Track URL: {track_url}")

        return {"track_name": track_name, "artist_name": artist_name, "cover_url": cover_url, "track_url": track_url}
    except Exception as e:
        logging.error(f"An error occurred while extracting data: {e}")
        return {}


# Initialize a session for HTTP requests to reuse connections
session = requests.Session()
session.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
})


def download_and_set_metadata(track_data):
    try:
        # Download audio file
        track_url = track_data["track_url"]
        track_name = track_data["track_name"]
        artist_name = track_data["artist_name"]
        cover_url = track_data["cover_url"]

        logging.info(f"Downloading audio from: {track_url}")

        # Download audio content
        response = session.get(track_url, allow_redirects=True)
        if response.status_code != 200:
            logging.error(f"Failed to download audio. Status code: {response.status_code}")
            return None, None

        # Verify content type
        content_type = response.headers.get("Content-Type", "")
        if "audio/mp4" not in content_type and "video/mp4" not in content_type:
            logging.error(f"Unexpected Content-Type: {content_type}")
            return None, None

        audio_content = response.content

        # Save audio to a temporary file
        temp_audio = tempfile.NamedTemporaryFile(delete=False, suffix=".m4a")
        temp_audio.write(audio_content)
        temp_audio.close()

        # Download cover image
        logging.info(f"Downloading cover image from: {cover_url}")
        response = session.get(cover_url)
        if response.status_code != 200:
            logging.error(f"Failed to download cover image. Status code: {response.status_code}")
            os.unlink(temp_audio.name)
            return None, None
        cover_data = response.content

        # Load the temporary audio file with mutagen
        try:
            audio = MP4(temp_audio.name)
        except Exception as e:
            logging.error(f"Failed to parse MP4 file: {e}")
            os.unlink(temp_audio.name)
            return None, None

        audio["\xa9nam"] = track_name  # Title
        audio["\xa9ART"] = artist_name  # Artist
        audio["covr"] = [MP4Cover(cover_data, imageformat=MP4Cover.FORMAT_JPEG)]
        audio.save()

        # Read the processed file into memory for sending
        with open(temp_audio.name, "rb") as audio_file:
            output_buffer = BytesIO(audio_file.read())

        # Clean up temporary file
        os.unlink(temp_audio.name)
        logging.info("Metadata set successfully and temporary file cleaned up.")

        return output_buffer, f"{track_name} - {artist_name}.m4a"

    except Exception as e:
        logging.error(f"An error occurred while downloading or setting metadata: {e}")
        return None, None


def fetch_and_process(url):
    try:
        response = session.get(url)

        if response.status_code == 200:
            response_text = response.text

            track_data = extract_and_log_data(response_text)

            audio_buffer, filename = download_and_set_metadata(track_data)

            if audio_buffer:
                return audio_buffer, filename
            else:
                return None, None
        else:
            logging.error(f"Failed to fetch the URL. Status code: {response.status_code}")
            return None, None
    except Exception as e:
        logging.error(f"An error occurred: {e}")
        return None, None


@app.route('/download', methods=['GET'])
def download_track():
    url = request.args.get('url')
    if not url:
        return jsonify({"error": "No URL provided"}), 400

    audio_buffer, filename = fetch_and_process(url)

    if audio_buffer and filename:
        audio_buffer.seek(0)  # Ensure the buffer is at the beginning
        return send_file(
            audio_buffer,
            as_attachment=True,
            download_name=filename,
            mimetype='audio/mp4'
        )
    else:
        return jsonify({"error": "Failed to process the track"}), 500


@app.route('/')
def index():
    return """
    <h1>Music Downloader</h1>
    <p>Use the <code>/download</code> endpoint with a 'url' query parameter to download a track.</p>
    <p>Example: <code>/download?url=https://music.douyin.com/qishui/share/track?track_id=7426362667027466281&hybrid_sdk_version=bullet&auto_play_bgm=1</code></p>
    """


if __name__ == '__main__':
    # Run Flask without debug mode
    app.run(host='0.0.0.0', port=5000, debug=False)
