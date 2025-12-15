import paramiko
import getpass

# ===== CONFIG =====
KEY_PATH = "/home/d1l1th1um/Desktop/id_rsa"
CMS_HOST = "cms-ssh.sc.imr.tohoku.ac.jp"
GPU_HOST = "gpu.sc.imr.tohoku.ac.jp"
USER = "inomar01"
REMOTE_DIR = "/home/inomar01/Hieu"
REMOTE_IMAGE = f"{REMOTE_DIR}/upload.jpg"
LOCAL_IMAGE = "/home/d1l1th1um/Desktop/demo/vqa-image.png"

# ===== COMMAND =====
curl_cmd = f"""
cd {REMOTE_DIR} && curl -X POST http://10.200.1.4:5000/medgemma -F "image=@upload.jpg" -F "question=Describe this X-ray"
"""

# ===== INPUT SECRETS =====
key_passphrase = getpass.getpass("🔑 Enter SSH key passphrase: ")
gpu_password = getpass.getpass("🔐 Enter GPU password: ")

# ===== SSH TO CMS =====
print("[*] Connecting to CMS...")
pkey = paramiko.RSAKey.from_private_key_file(
    KEY_PATH, password=key_passphrase
)

cms = paramiko.SSHClient()
cms.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cms.connect(CMS_HOST, username=USER, pkey=pkey)

# ===== TUNNEL TO GPU =====
transport = cms.get_transport()
dest_addr = (GPU_HOST, 22)
local_addr = ("127.0.0.1", 0)

channel = transport.open_channel(
    "direct-tcpip", dest_addr, local_addr
)

gpu = paramiko.SSHClient()
gpu.set_missing_host_key_policy(paramiko.AutoAddPolicy())
gpu.connect(
    GPU_HOST,
    username=USER,
    password=gpu_password,
    sock=channel
)

# ===== UPLOAD IMAGE =====
print("[*] Uploading image to GPU node...")
sftp = gpu.open_sftp()

try:
    sftp.chdir(REMOTE_DIR)
except IOError:
    sftp.mkdir(REMOTE_DIR)
    sftp.chdir(REMOTE_DIR)

sftp.put(LOCAL_IMAGE, REMOTE_IMAGE)
sftp.close()

# ===== EXEC CURL =====
print("[*] Running MedGemma request...")
stdin, stdout, stderr = gpu.exec_command(curl_cmd)

print("----- RESPONSE -----")
print(stderr.read().decode())
print("--------------------")

print("----- RESPONSE -----")
print(stdout.read().decode())
print("--------------------")

gpu.close()
cms.close()
