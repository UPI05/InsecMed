BEGIN TRANSACTION;
CREATE TABLE diagnoses
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  model TEXT,
                  image_filename TEXT,
                  prediction TEXT,
                  probability REAL,
                  timestamp DATETIME,
                  FOREIGN KEY (user_id) REFERENCES users(id));
INSERT INTO "diagnoses" VALUES(1,2,2,'skin_cancer_vit','4ec3b859-f621-4de4-a02f-9c7ba445cd88_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 04:10:42.757472');
INSERT INTO "diagnoses" VALUES(2,1,'BN_1','skin_cancer_vit','cf0546de-c57f-45f8-aa6a-86d8d201e00e_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 04:47:47.553378');
INSERT INTO "diagnoses" VALUES(3,2,1,'skin_cancer_vit','cf4f3afc-6c28-4f85-8760-fc56d478de73_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 04:49:07.787197');
INSERT INTO "diagnoses" VALUES(4,2,1,'skin_cancer_vit','d40a5e7e-1de6-4353-9356-060b6521e2ae_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 04:50:07.958227');
INSERT INTO "diagnoses" VALUES(5,2,1,'skin_cancer_vit','323952c6-c877-4522-ab91-219f8d063530_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:36:05.959824');
INSERT INTO "diagnoses" VALUES(6,2,1,'skin_cancer_vit','19a18cc1-04b4-4924-8904-98e8e46235af_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:36:35.818430');
INSERT INTO "diagnoses" VALUES(7,2,1,'skin_cancer_vit','06a270d8-ffdf-4cc1-a2af-8b2b90e1a3ca_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:39:02.277302');
INSERT INTO "diagnoses" VALUES(8,2,1,'skin_cancer_vit','24d2c019-23ee-4cb4-9b5a-71335dea0134_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:39:30.043117');
INSERT INTO "diagnoses" VALUES(9,2,1,'skin_cancer_vit','489585c3-09ea-49d5-92d2-8966c130bb62_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:44:29.861847');
INSERT INTO "diagnoses" VALUES(10,1,'BN_1','skin_cancer_vit','aa7124e2-7f7c-4ba5-935f-e1dc07f4666b_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 07:51:03.195656');
INSERT INTO "diagnoses" VALUES(11,1,'BN_1','pneumonia_vit','9091e8b8-cf6e-46de-b5dd-12f212be7b25_mun.jpg','PNEUMONIA',5.83904445171356201e-01,'2025-10-03 07:51:18.561482');
INSERT INTO "diagnoses" VALUES(12,3,3,'skin_cancer_vit','6838a765-5154-4a16-814d-3fba07a0beea_vit-con.jpg','melanocytic_Nevi',8.65956306457519531e-01,'2025-10-03 08:36:25.950420');
INSERT INTO "diagnoses" VALUES(13,4,'BN_4','pneumonia_vit','d209f330-986d-4b61-b5e0-144efb3c3902_vit-con.jpg','PNEUMONIA',5.66875338554382324e-01,'2025-10-03 08:40:04.662637');
INSERT INTO "diagnoses" VALUES(14,4,'BN_4','pneumonia_vit','3ee51faf-e574-4d4a-bafc-f6efa60e3334_..vit-con.jpg','PNEUMONIA',5.66875338554382324e-01,'2025-10-03 09:05:43.010811');
INSERT INTO "diagnoses" VALUES(15,1,'BN_1','skin_cancer_vit','aa5e77fe-837b-4255-910a-b17ad5eb99c6_mun.jpg','actinic_keratoses',9.41553950309753418e-01,'2025-10-03 15:56:32.749096');
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
INSERT INTO "patients" VALUES(1,'Võ Trường Trung Hiếu',11,'Nam','0980000000','votruongtrunghieu@gmail.com','Everise',2);
INSERT INTO "patients" VALUES(2,'Khang Nguyen',12,'','238741923','votruongtrunghieu@gmail.com','HCM',2);
INSERT INTO "patients" VALUES(3,'NGUYEN DANG QUYNH NHU',22,'','0909501046','quynhnhu170218@gmail.com','152/1 Nguyen Thi Tan Ward2, District 8',3);
CREATE TABLE qa_interactions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  patient_id INTEGER,
                  image_filename TEXT,
                  question TEXT,
                  answer TEXT,
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
INSERT INTO "users" VALUES(1,'Võ Trường Trung Hiếu','votruongtrunghieu@gmail.com','0378741924',NULL,'patient','$2b$12$GrOLntFogvaOIXuQhhamLOOgYJp7elegPMkINCIEbmd6d6dIuLJYK');
INSERT INTO "users" VALUES(2,'Võ Trường Trung Hiếu','votruongtrunghieu1@gmail.com','0378741924',NULL,'doctor','$2b$12$ENZhkR07bYCwKkA8ITp5eeH2wXd2E/CREuyeZ6T5PNDkvvrdR4KQW');
INSERT INTO "users" VALUES(3,'NGUYEN DANG QUYNH NHU','quynhnhu170218@gmail.com','0909501046',NULL,'doctor','$2b$12$jfkNHrl2g6I4QqTqOYxcZeLxpK3Vp8Yk6JqdoW9mnryKBBFYkFDaq');
INSERT INTO "users" VALUES(4,'NGUYEN DANG QUYNH NHU','22521050@gm.uit.edu.vn','0909501046','bb3bc59e-e3c0-488a-8d2b-c2ddd45416f2_vit-con.jpg','patient','$2b$12$uAGRYPEcpquipZvoLpR2aegZP0cGvWqxm6UjebsdB.2I1WjfMnh/S');
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('users',4);
INSERT INTO "sqlite_sequence" VALUES('patients',3);
INSERT INTO "sqlite_sequence" VALUES('diagnoses',15);
COMMIT;
