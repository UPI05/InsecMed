BEGIN TRANSACTION;
CREATE TABLE diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
                  explain_image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  share_to TEXT,
                  accept_share INTEGER,
                  sharer INTEGER,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id));
CREATE TABLE patients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            phone TEXT,
            email TEXT,
            address TEXT,
            creator_id INTEGER NOT NULL
        );
CREATE TABLE qa_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  model TEXT,
                  patient_id INTEGER,
                  image_filename TEXT,
                  question TEXT,
                  answer TEXT,
                  share_to TEXT,
                  accept_share INTEGER,
                  sharer INTEGER,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id));
CREATE TABLE users
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  full_name TEXT NOT NULL,
                  email TEXT UNIQUE NOT NULL,
                  phone TEXT,
                  profile_pic TEXT,
                  role TEXT,
                  password_hash TEXT NOT NULL);
DELETE FROM "sqlite_sequence";
COMMIT;
