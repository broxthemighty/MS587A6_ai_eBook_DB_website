# AI eBook & Audiobook Library

## Project Overview

This Flask web application transforms a traditional file-based eBook and audiobook library into a dynamic, database-driven system. It integrates with an AI (Google Gemini) to generate new short stories on demand and converts book content into audio, providing a seamless user experience for reading, listening, and contributing reviews. The application leverages PostgreSQL for efficient data storage and retrieval, enhancing performance and scalability compared to a local file system.

---

## Features

* **Dynamic eBook Listing:** Displays a comprehensive list of AI-generated books fetched directly from a PostgreSQL database.
* **AI Story Generation:** Users can submit a theme, and the Google Gemini AI will generate a new short story, which is then saved directly into the database.
* **In-Browser Reading:** View and read the full content of any eBook directly within the browser.
* **Audiobook Generation & Playback:** Converts eBook content into audio using `gTTS` (Google Text-to-Speech) and allows in-browser playback. Audio files are generated on demand and cached locally for efficiency.
* **Text Download:** Download the plain text content of any book from the database.
* **User Reviews:** Submit ratings and text reviews for books, with user information managed in the database.
* **Responsive Design:** Styled with custom CSS for a visually appealing and adaptive user experience across various devices.

---

## Technologies Used

* **Backend:** Python 3.x
* **Web Framework:** Flask
* **Database:** PostgreSQL (via `psycopg2`)
* **AI Integration:** Google Gemini API (`google-generativeai`)
* **Text-to-Speech:** `gTTS` (Google Text-to-Speech)
* **Environment Variables:** `python-dotenv`
* **Frontend:** HTML5, CSS3, JavaScript

---

## Database Schema

The application uses a PostgreSQL database with the following schema:

```sql
-- Authors Table
CREATE TABLE IF NOT EXISTS Authors (
    author_id SERIAL PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    bio TEXT
);

-- Users Table
CREATE TABLE IF NOT EXISTS Users (
    user_id SERIAL PRIMARY KEY,
    username VARCHAR(50) NOT NULL UNIQUE,
    email VARCHAR(100) NOT NULL UNIQUE
);

-- Books Table
CREATE TABLE IF NOT EXISTS Books (
    book_id SERIAL PRIMARY KEY,
    title VARCHAR(200) NOT NULL,
    author_id INTEGER NOT NULL REFERENCES Authors(author_id),
    genre VARCHAR(50),
    published_date DATE,
    content TEXT
);

-- Reviews Table
CREATE TABLE IF NOT EXISTS Reviews (
    review_id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES Users(user_id),
    book_id INTEGER NOT NULL REFERENCES Books(book_id),
    rating INTEGER CHECK (rating BETWEEN 1 AND 10),
    review_text TEXT,
    review_date DATE DEFAULT CURRENT_DATE
);
````

-----

## Setup Instructions

Follow these steps to set up and run the application locally.

### 1\. Clone the Repository

```bash
git clone <your-repository-url>
cd MS587A6_ai_eBook_DB_website # Or whatever your project folder is named
```

### 2\. Create and Activate a Virtual Environment

It's highly recommended to use a virtual environment to manage dependencies.

```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On macOS/Linux:
source venv/bin/activate
```

### 3\. Install Dependencies

Install all required Python packages using pip:

```bash
pip install -r requirements.txt
# If requirements.txt is not present, create it first using:
# pip freeze > requirements.txt
# And then install:
# pip install Flask python-dotenv gTTS google-generativeai psycopg2-binary
```

### 4\. Environment Variables

Create a file named `.env` in the root directory of your project. This file will store your sensitive API keys and database connection string.

```ini
# .env file content
DATABASE_URL="postgresql://user:password@host:port/database_name"
GEMINI_API_KEY="YOUR_GEMINI_API_KEY_HERE"
```

  * Replace `"YOUR_GEMINI_API_KEY_HERE"` with your actual Google Gemini API Key.
  * Replace `"postgresql://user:password@host:port/database_name"` with your PostgreSQL database connection string. For local testing, this might look something like `"postgresql://postgres:mysecretpassword@localhost:5432/ebook_db"`.

### 5\. Database Setup

1.  **Install PostgreSQL:** If you don't have PostgreSQL installed, download and install it from [postgresql.org](https://www.postgresql.org/download/).
2.  **Create a Database:** Create a new database for your application (e.g., `ebook_db`).
    ```sql
    CREATE DATABASE ebook_db;
    ```
3.  **Run Schema Script:** Connect to your new database and run the table creation script to set up the tables:
    ```bash
    psql -d ebook_db -f MattLindborg_Postgres_Table_Creation_Script.sql
    ```
4.  **Insert Initial Data:** Populate the tables with initial authors, users, and book placeholders using the data insert script:
    ```bash
    psql -d ebook_db -f MattLindborg_Postgres_Data_Insert_Script.sql
    ```
5.  **Update Book Content:** Run the update script to fill in the full book content:
    ```bash
    psql -d ebook_db -f MattLindborg_Postgres_Book_Text_Update_Script.sql
    ```
    *Note: The `MattLindborg_Postgres_Retrieve_Books_Script.sql` file is a simple `SELECT` query for retrieving books and is not part of the setup process.*

### 6\. Run the Flask Application

Once the database is set up and environment variables are configured, you can run the Flask application:

```bash
python app.py
```

The application will typically run on `http://127.0.0.1:5000/`. Open this URL in your web browser.

-----

## Usage

  * **Homepage (`/`):** View a list of all available AI-generated eBooks.
  * **Generate New Story:** Use the form on the homepage to enter a theme and generate a new AI story.
  * **Read Book (`/read/<book_id>`):** Click "Read" on a book card to view its full content.
  * **Listen to Audiobook (`/audio/<book_id>`):** Click "Listen" on a book card. The first time, it will generate the MP3; subsequent clicks will play it directly.
  * **Download Text (`/download_text/<book_id>`):** Download the book's content as a `.txt` file.
  * **Submit Review:** On the "Read Book" page, you can leave a star rating and a text review.

-----

## Credits and Acknowledgements

  * **Author:** Matt Lindborg
  * **Course:** UAT MS587 Week 6 Assignment 6.1
  * **Purpose:** AI eBook & Audiobook Library - Dynamic homepage, database integration

-----