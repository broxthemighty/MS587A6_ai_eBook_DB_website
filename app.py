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
#===============================================

#app.py
import os
import logging
import json
import tempfile
import time
from datetime import timedelta

# Third-party imports
from flask import (
    Flask, render_template, request, abort, 
    redirect, url_for, jsonify, make_response
)
from dotenv import load_dotenv
from gtts import gTTS
import google.generativeai as genai
import psycopg2
import psycopg2.pool

# Conditional import for GCS
from google.cloud import storage

# Flask app setup
app = Flask(__name__)

# Load environment variables (e.g., GEMINI_API_KEY)
load_dotenv(override=True)

# Database URL
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please set it in your .env file or Render settings.")
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# only enable GCS if we actually have valid JSON
raw_key_json = os.getenv("GCP_SERVICE_ACCOUNT_JSON", "").strip()
creds = None
if raw_key_json:
    try:
        creds = json.loads(raw_key_json)
        USE_GCS = True
    except json.JSONDecodeError:
        app.logger.warning("GCP_SERVICE_ACCOUNT_JSON is not valid JSON; falling back to local audio storage")
        USE_GCS = False
else:
    USE_GCS = False

if USE_GCS:
    # Write JSON blob to temp file for SDK
    tf = tempfile.NamedTemporaryFile(delete=False, suffix=".json")
    tf.write(json.dumps(creds).encode("utf-8"))
    tf.close()
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = tf.name

    # Bucket name
    GCS_BUCKET_NAME = os.getenv("GCS_BUCKET_NAME")
    if not GCS_BUCKET_NAME:
        raise ValueError("GCS_BUCKET_NAME is not set")

    # Initialize storage client & bucket handle
    storage_client = storage.Client()
    bucket = storage_client.bucket(GCS_BUCKET_NAME)
else:
    # Local filesystem fallback for development (5)
    AUDIO_DIR = os.path.join(os.getcwd(), "static", "audio")
    os.makedirs(AUDIO_DIR, exist_ok=True)

# Configure Flask's logger
app.logger.setLevel(logging.INFO)

# Database connection pool
db_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1, maxconn=5, dsn=DATABASE_URL
)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    db_pool.putconn(conn)
    
def generate_mp3_with_retries(text, out_path, max_retries=5):
    backoff = 1.0
    for attempt in range(1, max_retries + 1):
        try:
            tts = gTTS(text)
            tts.save(out_path)
            if attempt > 1:
                app.logger.info(f"gTTS succeeded on retry #{attempt}")
            return
        except Exception as e:
            msg = str(e)
            # look for 429 in the exception text
            if "429" in msg and attempt < max_retries:
                app.logger.warning(f"gTTS rate limit (429) on attempt {attempt}, retrying in {backoff}s…")
                time.sleep(backoff)
                backoff *= 2
                continue
            # non-rate-limit error or out of retries → bubble up
            app.logger.error(f"gTTS failed on attempt {attempt}: {e}")
            raise
    
def split_text(text, max_chars=800):
    paras = text.split("\n\n")
    chunks, current = [], ""
    for p in paras:
        # If a single paragraph is too large, break it into sub‐chunks
        if len(p) > max_chars:
            for i in range(0, len(p), max_chars):
                chunks.append(p[i : i + max_chars])
            continue

        if len(current) + len(p) + 2 <= max_chars:
            current += p + "\n\n"
        else:
            chunks.append(current.strip())
            current = p + "\n\n"

    if current:
        chunks.append(current.strip())
    return chunks

def generate_mp3_chunks(text: str, out_path: str):
    # synthesize each chunk to a .part file
    temp_parts = []
    for i, chunk in enumerate(split_text(text, max_chars=800)):
        part = f"{out_path}.part{i}.mp3"
        generate_mp3_with_retries(chunk, part)
        time.sleep(0.5)               # pause half a second between calls
        temp_parts.append(part)

    # concatenate all parts byte-wise
    with open(out_path, "wb") as outf:
        for part in temp_parts:
            with open(part, "rb") as inf:
                outf.write(inf.read())
            os.remove(part)
    
@app.route("/")

def index():
    """
    Homepage: displays a list of all eBooks from the PostgreSQL database.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
            SELECT
                b.book_id,
                b.title,
                a.name AS author_name,
                b.genre,
                b.published_date,
                AVG(r.rating) AS avg_rating,
                COUNT(r.review_id) AS total_reviews
            FROM books b
            JOIN authors a ON b.author_id = a.author_id
            LEFT JOIN reviews r ON b.book_id = r.book_id
            GROUP BY b.book_id, b.title, a.name, b.genre, b.published_date
            ORDER BY b.published_date DESC;
                    """)
            ebooks = cur.fetchall()
    finally:
            release_db_connection(conn)
        
    ctx = {"ebooks": ebooks}
    if USE_GCS:
        ctx["bucket_name"] = GCS_BUCKET_NAME  # show bucket in template
    return render_template("index.html", **ctx)

@app.route("/read/<int:book_id>")
def read(book_id):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, content FROM books WHERE book_id = %s", (book_id,))
            result = cur.fetchone()
        if not result:
            abort(404)
        title, content = result
    finally:
        release_db_connection(conn)
    return render_template("read_book.html", title=title, content=content, book_id=book_id)

@app.route("/audio/<int:book_id>")
def audio(book_id):
    """
    Generate (if needed) and serve audio via Google Cloud Storage or local fallback.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, content FROM books WHERE book_id = %s", (book_id,))
            row = cur.fetchone()
        if not row:
            abort(404)
        title, text = row
    finally:
        release_db_connection(conn)

    filename = f"book_{book_id}.mp3"

    if USE_GCS:
        blob = bucket.blob(filename)
        try:
            exists = blob.exists()
        except Exception as e:
            app.logger.error(f"Error checking blob existence for {filename}: {e}")
            exists = False

        if not exists:
            if not text.strip():
                return "This eBook is empty and cannot be converted to audio.", 400

            try:
                tmp_path = os.path.join(tempfile.gettempdir(), filename)
                generate_mp3_chunks(text, tmp_path)
                blob.upload_from_filename(tmp_path)
                audio_url = blob.generate_signed_url(
                            expiration=timedelta(minutes=30),
                            version="v4",
                            response_disposition=f'attachment; filename="{filename}"'
                            )
                app.logger.info(f"Generated and uploaded {filename} to GCS")
            except Exception as e:
                app.logger.error(f"Audio gen/upload failed: {e}")
                return f"Error during audio processing: {e}", 500
        else:
            audio_url = blob.generate_signed_url(
                        expiration=timedelta(minutes=30),
                        version="v4",
                        response_disposition=f'attachment; filename="{filename}"'
                        )

        return render_template("audio_player.html", audio_url=audio_url, title=title)
    else:
        # Local dev fallback
        local_path = os.path.join(AUDIO_DIR, filename)
        if not os.path.exists(local_path):
            tts = gTTS(text)
            tts.save(local_path)
        audio_url = url_for('static', filename=f"audio/{filename}")
        return render_template("audio_player.html", audio_url=audio_url, title=title)

@app.route("/download_text/<int:book_id>")
def download_text(book_id):
    """
    Allows users to download the raw .txt version of a book,
    fetching content directly from the database.
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, content FROM books WHERE book_id = %s", (book_id,))
            result = cur.fetchone()
        if not result:
            abort(404)
        title, content = result
    finally:
        release_db_connection(conn)

    # Create a response with the text content
    response = make_response(content)
    # Ensure filename is safe and descriptive
    safe_title = "".join(c for c in title if c.isalnum() or c in (' ', '.', '_')).rstrip()
    response.headers["Content-Disposition"] = f"attachment; filename=\"{safe_title.replace(' ', '_')}.txt\""
    response.headers["Content-Type"] = "text/plain"
    return response

@app.route("/generate", methods=["POST"])
def generate():
    """
    Handles AI story generation using Gemini when the user submits a theme.
    Saves a new eBook and refreshes the index page.
    Switched to use the database
    """
    theme = request.form.get("theme", "").strip()
    if not theme:
        return redirect(url_for("index"))

    try:
        genai.configure(api_key=os.getenv("GEMINI_API_KEY"))
        model = genai.GenerativeModel("gemini-1.5-flash")
        prompt = f"Write a creative short story (~500 words) titled '{theme}'. It should be imaginative and suitable for general audiences."

        response = model.generate_content(prompt)
        story = response.text.strip()

        # Insert into database
        conn = get_db_connection()
        try:
            with conn.cursor() as cur:
               # Ensure 'Gemini AI' exists
                cur.execute("SELECT author_id FROM authors WHERE name = %s", ("Gemini AI",))
                author = cur.fetchone()
                if not author:
                    cur.execute("INSERT INTO authors (name) VALUES (%s) RETURNING author_id", ("Gemini AI",))
                    author_id = cur.fetchone()[0]
                else:
                    author_id = author[0]
                cur.execute("""
                    INSERT INTO books (title, content, genre, published_date, author_id)
                    VALUES (%s, %s, %s, CURRENT_DATE, %s)
                """, (theme, story, "Fiction", author_id))

                conn.commit()
        finally:
            release_db_connection(conn)

        app.logger.info(f"New story saved to database: {theme}")

    except Exception as e:
        app.logger.exception("Error during AI story generation")

    return redirect(url_for("index"))

@app.route("/submit_review/<int:book_id>", methods=["POST"])
def submit_review(book_id):
    """
    Submit a review for a book
    Changed to use the database
    Returns JSON instead of rendering a page.
    """
    username = request.form["username"]
    email = request.form["email"]
    rating = int(request.form["rating"])
    text = request.form["review_text"]

    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Check if the username exists
            cur.execute("SELECT user_id, email FROM users WHERE username = %s", (username,))
            user_by_name = cur.fetchone()

            # Check if the email exists
            cur.execute("SELECT user_id FROM users WHERE email = %s", (email,))
            user_by_email = cur.fetchone()

            if user_by_name:
                user_id, existing_email = user_by_name
                if existing_email != email:
                    return jsonify(success=False, error="❌ Email does not match the username on file.")
            elif not user_by_email:
                # Create new user if email not in use
                cur.execute(
                    "INSERT INTO users (username, email) VALUES (%s, %s) RETURNING user_id",
                    (username, email),
                )
                user_id = cur.fetchone()[0]
            else:
                user_id = user_by_email[0]

            # Insert the review
            cur.execute(
                "INSERT INTO reviews (user_id, book_id, rating, review_text, review_date) VALUES (%s, %s, %s, %s, CURRENT_DATE)",
                (user_id, book_id, rating, text),
            )
            conn.commit()
    finally:
        release_db_connection(conn)

    return jsonify(success=True)

if __name__ == "__main__":
    app.run(debug=(not USE_GCS))
