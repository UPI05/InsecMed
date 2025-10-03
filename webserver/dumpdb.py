import sqlite3

db_path = 'insecmed.db'
conn = sqlite3.connect(db_path)

with open('backup.sql', 'w', encoding='utf-8') as f:
    for line in conn.iterdump():
        f.write('%s\n' % line)

conn.close()
print("Dumped to backup.sql")
