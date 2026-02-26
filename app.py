import os
import sqlite3
import tempfile
import subprocess
import numpy as np
import wave
import bcrypt
import streamlit as st
import pandas as pd
from Cryptodome.Cipher import AES
from Cryptodome.Util.Padding import pad, unpad

# --- 1. SETUP & CONFIGURATION (Inga thaan ellam define panrom) ---
DB_NAME = "guardian_v3.db" # Database name (v3 nu mathirukaen fresh-ah start panna)
UPLOAD_DIR = "master_videos" # Original videos save aaga
SECRET_KEY = "My16ByteSecret!!" # AES-128-ku 16 characters key
GAIN_FACTOR = 0.004 # Watermark noise level (romba kammiya vachurukaen)

# Folder illana create pannurom
if not os.path.exists(UPLOAD_DIR):
    try:
        os.makedirs(UPLOAD_DIR, exist_ok=True)
    except Exception as e:
        st.error(f"Folder create panna mudiyala: {e}")

def init_db():
    """Database-ah start panni tables create pannum"""
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        # User table-la ippo email and phone-um irukku
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      username TEXT UNIQUE, email TEXT, phone TEXT, password TEXT)''')
        c.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, uploader_id INTEGER)')
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"DB initialize panna mudiyala: {e}")

# --- 2. AES-128 & DSSS LOGIC (Main protection inga thaan nadakuthu) ---

def encrypt_user_id(user_id):
    """User ID-ya mattum AES-128 vechu encrypt panni bits-ah mathurom"""
    data = f"USER_{user_id}"
    key = SECRET_KEY.ljust(16)[:16].encode()
    cipher = AES.new(key, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
    combined = cipher.iv + ct_bytes
    return "".join([format(b, '08b') for b in combined])

def decrypt_user_id(bit_string):
    """Encrypted bits-ah thirumba User ID-ya mathurom"""
    try:
        key = SECRET_KEY.ljust(16)[:16].encode()
        byte_list = [int(bit_string[i:i+8], 2) for i in range(0, len(bit_string), 8)]
        full_data = bytes(byte_list)
        iv, ct = full_data[:16], full_data[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        pt = unpad(cipher.decrypt(ct), AES.block_size)
        return pt.decode()
    except:
        return None

def generate_pn_sequence(duration_samples):
    """Watermark-ah maraika oru random noise sequence generate pannuthu"""
    np.random.seed(42) 
    return (np.random.randint(0, 2, duration_samples) * 2 - 1).astype(np.float64)

def embed_watermark(input_wav, output_wav, user_id):
    """Audio-kulla User ID watermark-ah merge pannuthu"""
    bit_str = encrypt_user_id(user_id)
    bits = [int(b) for b in bit_str]
    with wave.open(input_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    
    total_samples = len(audio_samples)
    pn = generate_pn_sequence(total_samples)
    segment_len = 5 * params.framerate # 5 second chunks
    num_segments = total_samples // segment_len
    watermark = np.zeros(total_samples)

    for s in range(num_segments):
        start_idx = s * segment_len
        sf = segment_len // len(bits)
        for i, bit in enumerate(bits):
            val = 1 if bit == 1 else -1
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            watermark[b_start:b_end] = val * pn[b_start:b_end]

    # Inga thaan GAIN_FACTOR use aaguthu noise kuraika
    result = np.clip(audio_samples + (GAIN_FACTOR * watermark * np.max(np.abs(audio_samples))), -32768, 32767).astype(np.int16)
    with wave.open(output_wav, 'wb') as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

def extract_watermark(leaked_wav):
    """Leaked video-la irunthu User ID-ya kandupidikuthu"""
    with wave.open(leaked_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    segment_len = 5 * params.framerate
    bit_len = 256 # IV(128) + Data(128)
    pn = generate_pn_sequence(len(audio))
    for s in range(min(20, len(audio)//segment_len)):
        start_idx = s * segment_len
        sf = segment_len // bit_len
        extracted_bits = ""
        for i in range(bit_len):
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            correlation = np.sum(audio[b_start:b_end] * pn[b_start:b_end])
            extracted_bits += "1" if correlation > 0 else "0"
        decrypted = decrypt_user_id(extracted_bits)
        if decrypted and "USER_" in decrypted:
            return decrypted
    return None

# --- 3. MAIN APP (Inga thaan UI design irukku) ---
def main():
    st.set_page_config(page_title="Guardian Anti-Piracy v3.0", layout="wide")
    init_db()

    # User login-la irukana nu check pannuthu
    if "user_id" in st.query_params:
        st.session_state.uid = int(st.query_params["user_id"])
    elif 'uid' not in st.session_state: 
        st.session_state.uid = None

    if st.session_state.uid is None:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Login Section")
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.button("Log In"):
                conn = sqlite3.connect(DB_NAME)
                res = conn.execute("SELECT id, password FROM users WHERE username=?", (u,)).fetchone()
                if res and bcrypt.checkpw(p.encode(), res[1]):
                    st.session_state.uid = res[0]
                    st.query_params["user_id"] = str(res[0])
                    st.rerun()
                else: st.error("Login thappu macha!")
        with c2:
            st.subheader("Register Section")
            nu = st.text_input("Puthiya Username")
            nem = st.text_input("E-mail Address") # Email field
            nph = st.text_input("Phone Number") # Phone field
            npw = st.text_input("Password set pannu", type="password")
            if st.button("Sign Up"):
                if nu and nem and nph and npw:
                    h = bcrypt.hashpw(npw.encode(), bcrypt.gensalt())
                    conn = sqlite3.connect(DB_NAME)
                    try:
                        conn.execute("INSERT INTO users (username, email, phone, password) VALUES (?,?,?,?)", (nu, nem, nph, h))
                        conn.commit()
                        st.success("User register aayachu! Login pannu macha.")
                    except: st.error("Intha username already irukku.")
                else:
                    st.warning("Ella fields-aiyum fill pannu!")
        st.stop()

    st.sidebar.title("🛡️ Guardian v3.0")
    if st.sidebar.button("Log Out"):
        st.session_state.uid = None
        st.query_params.clear()
        st.rerun()

    # User details sidebar-la kaata
    st.sidebar.info(f"LoggedIn User ID: {st.session_state.uid}")

    t1, t2, t3, t4 = st.tabs(["📚 Shared Library", "📤 Upload Master", "🔍 Detector", "👥 User List"])

    with t1:
        st.write("Videos download pannumpothu automatic-ah unga ID kulla lock aagidum.")
        conn = sqlite3.connect(DB_NAME)
        vids = conn.execute("SELECT filename FROM videos").fetchall()
        for v in vids:
            if st.button(f"Secure Download: {v[0]}", key=v[0]):
                with st.spinner("Wait macha... Watermark add aaguthu..."):
                    with tempfile.TemporaryDirectory() as tmp:
                        in_v = os.path.join(UPLOAD_DIR, v[0])
                        in_a, out_a, out_v = os.path.join(tmp,"1.wav"), os.path.join(tmp,"2.wav"), os.path.join(tmp,"out.mp4")
                        # Audio-va extract pannurom
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-vn","-acodec","pcm_s16le",in_a], capture_output=True)
                        # Watermark embed pannurom
                        embed_watermark(in_a, out_a, st.session_state.uid)
                        # Thirumba video kulla merge pannurom
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-i",out_a,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac",out_v], capture_output=True)
                        with open(out_v, "rb") as f:
                            st.download_button("Download Now", f.read(), file_name=f"secured_{v[0]}")

    with t2:
        st.subheader("Master Video-va upload panna")
        up = st.file_uploader("Video-va inga podunga")
        if up and st.button("Server-la save pannu"):
            path = os.path.join(UPLOAD_DIR, up.name)
            with open(path, "wb") as f: f.write(up.read())
            conn = sqlite3.connect(DB_NAME)
            conn.execute("INSERT INTO videos (filename, uploader_id) VALUES (?,?)", (up.name, st.session_state.uid))
            conn.commit()
            st.success("Master video saved successfully!")

    with t3:
        st.subheader("Pirated video-la irunthu thirudan-ai kandupidi")
        leak = st.file_uploader("Social media-la kedacha leaked video")
        if leak and st.button("Start Scanning"):
            with tempfile.TemporaryDirectory() as tmp:
                lp, lw = os.path.join(tmp, "l.mp4"), os.path.join(tmp, "l.wav")
                with open(lp, "wb") as f: f.write(leak.read())
                # Video-la irunthu audio extract panni check panrom
                subprocess.run(["ffmpeg","-i",lp,"-acodec","pcm_s16le",lw], capture_output=True)
                res = extract_watermark(lw)
                if res: 
                    st.error(f"⚠️ PIRATER ID KEDACHIDUCHI: {res}")
                    st.balloons()
                else: 
                    st.warning("Watermark edhum illa macha.")

    with t4:
        st.subheader("Registered Users List")
        conn = sqlite3.connect(DB_NAME)
        df = pd.read_sql_query("SELECT id, username, email, phone FROM users", conn)
        st.table(df)

if __name__ == "__main__":
    main()

