#===============================================
#    Matt Lindborg
#    UAT MS587 Week 6 Assignment 6.1
#    AI eBook & Audiobook Library - Dynamic homepage, database integration
#    Purpose: Lists all eBooks with links to read, generate audio and new book, or listen
#    Notes:
#    - Fixed background from 'images/back.jpg'
#    - Changed over to gemini ai for dynamic story generation
#    - Changed from pyttsx3 to gTTS for cloud compatible mp3 from text
#===============================================

#app.py
import os
import logging
from flask import Flask, render_template, send_from_directory, request, abort, redirect, url_for
from dotenv import load_dotenv
from gtts import gTTS
import google.generativeai as genai
import psycopg2
import psycopg2.pool

# Load environment variables (e.g., GEMINI_API_KEY)
load_dotenv(override=True)

# Flexible database connection for local or production
DATABASE_URL = os.getenv("DATABASE_URL")

if not DATABASE_URL:
    raise ValueError("DATABASE_URL is not set. Please set it in your .env file or Render settings.")

if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

db_pool = psycopg2.pool.SimpleConnectionPool(
    minconn=1,
    maxconn=5,
    dsn=DATABASE_URL
)

def get_db_connection():
    return db_pool.getconn()

def release_db_connection(conn):
    db_pool.putconn(conn)

# Flask app setup
app = Flask(__name__)

# Directory configuration
EBOOK_DIR = "ebooks"
AUDIO_DIR = "static/audio"
os.makedirs(EBOOK_DIR, exist_ok=True)
os.makedirs(AUDIO_DIR, exist_ok=True)

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")


def generate_unique_filename(base: str, extension: str, directory: str) -> str:
    """
    Prevents file overwrites by appending a numeric suffix.
    Example: story.txt → story_1.txt
    """
    counter = 0
    candidate = f"{base}.{extension}"
    while os.path.exists(os.path.join(directory, candidate)):
        counter += 1
        candidate = f"{base}_{counter}.{extension}"
    return candidate


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
        
    return render_template("index.html", ebooks=ebooks)


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
    return render_template("read_book.html", title=title, content=content)


@app.route("/audio/<int:book_id>")
def audio(book_id):
    """
    Converts an eBook to audio using pyttsx3 and streams it in-browser.
    Changed from pyttsx3 to gtts, added additional error handling
    Updated to save to the database instead of locally
    """
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT title, content FROM books WHERE book_id = %s", (book_id,))
            result = cur.fetchone()
        if not result:
            abort(404)
        title, text = result
    finally:
        release_db_connection(conn)

    audio_filename = f"book_{book_id}.mp3"
    audio_path = os.path.join(AUDIO_DIR, audio_filename)

    if not os.path.exists(audio_path):
        try:
            if not text.strip():
                return "This eBook is empty and cannot be converted to audio.", 400

            tts = gTTS(text)
            tts.save(audio_path)

            logging.info(f"Audio generated: {audio_filename}")

        except Exception as e:
            logging.error(f"Audio generation failed for book_id={book_id}: {e}")
            return f"Error during audio generation: {str(e)}", 500

    return render_template("audio_player.html", audio_file=audio_filename, title=title)


@app.route("/download/<filename>")
def download(filename):
    """
    Allows users to download the raw .txt version of a book.
    """
    return send_from_directory(EBOOK_DIR, filename, as_attachment=True)


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
                # Ensure 'AI Author' exists
                cur.execute("SELECT author_id FROM authors WHERE name = %s", ("AI Author",))
                author = cur.fetchone()
                if not author:
                    cur.execute("INSERT INTO authors (name) VALUES (%s) RETURNING author_id", ("AI Author",))
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

        logging.info(f"New story saved to database: {theme}")

    except Exception as e:
        logging.exception("Error during AI story generation")

    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(debug=True)
