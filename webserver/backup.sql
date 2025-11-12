BEGIN TRANSACTION;
CREATE TABLE diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  share_to INTEGER,
                  accept_share INTEGER,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id));
INSERT INTO "diagnoses" VALUES(1,1,0,'skin_cancer_vit,pneumonia_vit,breast_cancer_vit,covid19_vit,brain_tumor_vit,brain_tumor_resnet','efb43dd8-0ad2-48a0-b9ae-06d53264803b_1000010436.jpg.png','U ác tính/Viêm phổi/Không bị ung thư vú/Hình ảnh CT có dấu hiệu COVID-19/Bị u não/U màng não/',0.3627,1,0,'2025-11-11 20:31:22.403498');
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
                  share_to INTEGER,
                  accept_share INTEGER,
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
INSERT INTO "users" VALUES(1,'Nguyen Van A','nva@gmail.com','0378241922',NULL,'doctor','$2b$12$umrsjXzy03RKJLetaqHRde83gg27J09ckQYqHEKlsYxvirFMYWFcu');
INSERT INTO "users" VALUES(2,'Nguyen Van B','nvb@gmail.com','0378241922',NULL,'doctor','$2b$12$u/3WiMtIEmJhpzmxjuqcguCWEMhbiEfv1lJlgjCbHPHAmLcqMfgMC');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('users',2);
INSERT INTO "sqlite_sequence" VALUES('diagnoses',1);
COMMIT;
