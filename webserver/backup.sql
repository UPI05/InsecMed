BEGIN TRANSACTION;
CREATE TABLE diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
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
INSERT INTO "users" VALUES(1,'Nguyen Van A','nva@gmail.com','0378241922',NULL,'doctor','$2b$12$DhysnXXn16Pfc1FdZnEWEe9IBJ2dp.EadG7MYap3C40zU6Kq3TPC6');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('users',1);
COMMIT;
