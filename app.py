#===============================================
#    Matt Lindborg
#    UAT MS587 Week 6 Assignment 6.1
#    AI eBook & Audiobook Library - Dynamic homepage, database integration
#    Purpose: Lists all eBooks with links to read, generate audio and new book, or listen
#    Notes:
#    - Fixed background from 'images/back.jpg'
#    - Changed over to gemini ai for dynamic story generation
#    - Changed from pyttsx3 to gTTS for cloud compatible mp3 from text
#    - Changed local filesystem data handling to use a database
#    - Ready for live hosting
#    - Changed the tts to use official gtts
#    - Refactored to remove repetitive code and better organization of sections
#===============================================

#app.py
import os
import json
import tempfile
import shutil
import logging
from datetime import timedelta
from contextlib import contextmanager

from flask import (
    Flask, render_template, request, abort,
    redirect, url_for, jsonify, make_response
)
from dotenv import load_dotenv
import google.generativeai as genai
from google.cloud import texttospeech, storage
import psycopg2.pool

# Configuration & Clients
load_dotenv(override=True)

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set.")

RAW_KEY = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
USE_GCS = False
if RAW_KEY:
    try:
        creds = json.loads(RAW_KEY)
        USE_GCS = True
        tf = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
        tf.write(json.dumps(creds).encode())
        tf.close()
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tf.name

        GCS_BUCKET = os.getenv("GCS_BUCKET_NAME")
        if not GCS_BUCKET:
            raise RuntimeError("GCS_BUCKET_NAME not set")
        gcs_client = storage.Client()
        bucket = gcs_client.bucket(GCS_BUCKET)
    except json.JSONDecodeError:
        USE_GCS = False

tts_client = texttospeech.TextToSpeechClient()
db_pool = psycopg2.pool.SimpleConnectionPool(1, 5, dsn=DATABASE_URL)

app = Flask(__name__)
app.logger.setLevel(logging.INFO)


# Helpers
@contextmanager
def db_cursor():
    conn = db_pool.getconn()
    try:
        cur = conn.cursor()
        yield cur
        conn.commit()
    finally:
        db_pool.putconn(conn)

def fetch_all(sql, *params):
    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchall()

def fetch_one(sql, *params):
    with db_cursor() as cur:
        cur.execute(sql, params)
        return cur.fetchone()

def synthesize(text, out_path):
    """Uses Cloud TTS to synthesize `text` into an MP3 at `out_path`."""
    inp = texttospeech.SynthesisInput(text=text)
    voice = texttospeech.VoiceSelectionParams(
        language_code="en-US",
        ssml_gender=texttospeech.SsmlVoiceGender.NEUTRAL
    )
    cfg = texttospeech.AudioConfig(audio_encoding=texttospeech.AudioEncoding.MP3)
    resp = tts_client.synthesize_speech(input=inp, voice=voice, audio_config=cfg)
    with open(out_path, "wb") as f:
        f.write(resp.audio_content)
    app.logger.info(f"TTS → {out_path} ({len(resp.audio_content)} bytes)")

def get_signed_url(filename, expiry=timedelta(hours=1)):
    blob = bucket.blob(filename)
    return blob.generate_signed_url(
        expiration=expiry,
        version="v4",
        response_disposition=f'attachment; filename="{filename}"'
    )

def upload_to_gcs(local_path, filename):
    blob = bucket.blob(filename)
    blob.upload_from_filename(local_path)
    return get_signed_url(filename)


# Routes
@app.route("/")
def index():
    """
    Homepage: displays a list of all eBooks from the PostgreSQL database.
    """
    ebooks = fetch_all("""
        SELECT b.book_id, b.title, a.name, b.genre, b.published_date,
               AVG(r.rating) AS avg_rating, COUNT(r.review_id) AS total_reviews
          FROM books b
          JOIN authors a USING (author_id)
          LEFT JOIN reviews r USING (book_id)
      GROUP BY b.book_id, b.title, a.name, b.genre, b.published_date
      ORDER BY b.published_date DESC;
    """)
    return render_template(
        "index.html",
        ebooks=ebooks,
        use_gcs=USE_GCS,
        bucket_name=(GCS_BUCKET if USE_GCS else "")
    )


@app.route("/read/<int:book_id>")
def read(book_id):
    """
    Read page: fetches title & content from the database.
    """
    row = fetch_one("SELECT title, content FROM books WHERE book_id = %s", book_id)
    if not row:
        abort(404)
    title, content = row
    return render_template("read_book.html", title=title, content=content, book_id=book_id)


@app.route("/audio/<int:book_id>")
def audio(book_id):
    """
    Generate (if needed) and serve audio via GCS or local fallback.
    """
    row = fetch_one("SELECT title, content FROM books WHERE book_id = %s", book_id)
    if not row:
        abort(404)
    title, text = row
    if not text.strip():
        return "This eBook is empty – no audio.", 400

    filename = f"book_{book_id}.mp3"
    tmp = os.path.join(tempfile.gettempdir(), filename)

    try:
        synthesize(text, tmp)
    except Exception as e:
        app.logger.error(f"TTS failed: {e}")
        return f"TTS error: {e}", 500

    if USE_GCS:
        url = upload_to_gcs(tmp, filename)
    else:
        local_dir = os.path.join(app.root_path, "static", "audio")
        os.makedirs(local_dir, exist_ok=True)
        dst = os.path.join(local_dir, filename)
        if not os.path.exists(dst):
            shutil.copy(tmp, dst)
        url = url_for("static", filename=f"audio/{filename}")

    return render_template("audio_player.html", audio_url=url, title=title)


@app.route("/download_text/<int:book_id>")
def download_text(book_id):
    """
    Download .txt version of a book from the database.
    """
    row = fetch_one("SELECT title, content FROM books WHERE book_id = %s", book_id)
    if not row:
        abort(404)
    title, content = row
    safe = "".join(c for c in title if c.isalnum() or c in (" ", "_")).strip().replace(" ", "_")
    resp = make_response(content)
    resp.headers.update({
        "Content-Disposition": f'attachment; filename="{safe}.txt"',
        "Content-Type": "text/plain"
    })
    return resp


@app.route("/generate", methods=["POST"])
def generate():
    """
    Handles AI story generation using Gemini.
    Saves new eBook to the database.
    """
    theme = request.form.get("theme", "").strip()
    if not theme:
        return redirect(url_for("index"))

    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-flash")
        story = model.generate_content(
            f"Write a creative short story (~500 words) titled '{theme}'."
        ).text.strip()

        with db_cursor() as cur:
            cur.execute("SELECT author_id FROM authors WHERE name=%s", ("Gemini AI",))
            r = cur.fetchone()
            if r:
                aid = r[0]
            else:
                cur.execute(
                    "INSERT INTO authors(name) VALUES(%s) RETURNING author_id",
                    ("Gemini AI",)
                )
                aid = cur.fetchone()[0]

            cur.execute(
                "INSERT INTO books(title,content,genre,published_date,author_id) "
                "VALUES(%s,%s,%s,CURRENT_DATE,%s)",
                (theme, story, "Fiction", aid)
            )
        app.logger.info("New story saved: %s", theme)

    except Exception:
        app.logger.exception("AI generation failed")

    return redirect(url_for("index"))


@app.route("/submit_review/<int:book_id>", methods=["POST"])
def submit_review(book_id):
    """
    Submit a review for a book, using DB for users & reviews.
    Returns JSON.
    """
    uname = request.form["username"]
    email = request.form["email"]
    rating = int(request.form["rating"])
    text = request.form["review_text"]

    with db_cursor() as cur:
        cur.execute("SELECT user_id, email FROM users WHERE username=%s", (uname,))
        u = cur.fetchone()
        if u and u[1] != email:
            return jsonify(success=False, error="❌ Email mismatch.")
        if not u:
            cur.execute(
                "INSERT INTO users(username,email) VALUES(%s,%s) RETURNING user_id",
                (uname, email)
            )
            uid = cur.fetchone()[0]
        else:
            uid = u[0]

        cur.execute(
            "INSERT INTO reviews(user_id,book_id,rating,review_text,review_date)"
            "VALUES(%s,%s,%s,%s,CURRENT_DATE)",
            (uid, book_id, rating, text)
        )
    return jsonify(success=True)


if __name__ == "__main__":
    app.run(debug=not USE_GCS)
