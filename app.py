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

# --- 1. SETUP & CONFIGURATION ---
DB_NAME = "guardian.db"
UPLOAD_DIR = "master_videos"
SECRET_KEY = "ThisIsASecretKeyForAES256!!!!!" # 32 chars recommended
GAIN_FACTOR = 0.007  # Noise-ah kuraikka (Pazhayadhu 0.02 irundhuchu)

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR)

def init_db():
    conn = sqlite3.connect(DB_NAME)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users 
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                  username TEXT UNIQUE, email TEXT, phone TEXT, password TEXT)''')
    c.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, uploader_id INTEGER)')
    conn.commit()
    conn.close()

# --- 2. ENCRYPTION & DSSS CORE LOGIC ---

def encrypt_data(data):
    key = SECRET_KEY.ljust(32)[:32].encode()
    cipher = AES.new(key, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
    combined = cipher.iv + ct_bytes
    return "".join([format(b, '08b') for b in combined])

def decrypt_data(bit_string):
    try:
        key = SECRET_KEY.ljust(32)[:32].encode()
        byte_list = [int(bit_string[i:i+8], 2) for i in range(0, len(bit_string), 8)]
        full_data = bytes(byte_list)
        iv = full_data[:16]
        ct = full_data[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        pt = unpad(cipher.decrypt(ct), AES.block_size)
        return pt.decode()
    except:
        return None

def generate_pn_sequence(duration_samples):
    np.random.seed(42) 
    return (np.random.randint(0, 2, duration_samples) * 2 - 1).astype(np.float64)

def embed_watermark(input_wav, output_wav, user_id):
    bit_str = encrypt_data(f"USER_{user_id}")
    bits = [int(b) for b in bit_str]
    
    with wave.open(input_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    total_samples = len(audio_samples)
    pn = generate_pn_sequence(total_samples)
    
    # Redundancy for Trimming Resistance
    segment_len = 5 * params.framerate
    num_segments = total_samples // segment_len
    watermark = np.zeros(total_samples)

    for s in range(num_segments):
        start_idx = s * segment_len
        sf = segment_len // len(bits)
        for i, bit in enumerate(bits):
            val = 1 if bit == 1 else -1
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            watermark[b_start:b_end] = val * pn[b_start:b_end]

    # Optimized Gain to reduce Audible Noise
    result = np.clip(audio_samples + (GAIN_FACTOR * watermark * np.max(np.abs(audio_samples))), -32768, 32767).astype(np.int16)
    with wave.open(output_wav, 'wb') as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

def extract_watermark(leaked_wav):
    with wave.open(leaked_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    segment_len = 5 * params.framerate
    bit_len = 256 # Fixed bit length for encrypted USER_ID
    pn = generate_pn_sequence(len(audio))
    
    # Deep scan: First 20 segments to find watermark after trimming
    for s in range(min(20, len(audio)//segment_len)):
        start_idx = s * segment_len
        sf = segment_len // bit_len
        extracted_bits = ""
        
        for i in range(bit_len):
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            correlation = np.sum(audio[b_start:b_end] * pn[b_start:b_end])
            extracted_bits += "1" if correlation > 0 else "0"
        
        decrypted = decrypt_data(extracted_bits)
        if decrypted and "USER_" in decrypted:
            return decrypted
    return None

# --- 3. MAIN APP ---
def main():
    st.set_page_config(page_title="Guardian Anti-Piracy v2.0", layout="wide")
    init_db()

    # --- REFRESH PERSISTENCE (Query Params) ---
    if "user_id" in st.query_params:
        st.session_state.uid = int(st.query_params["user_id"])
    elif 'uid' not in st.session_state: 
        st.session_state.uid = None

    # --- LOGIN / REGISTER ---
    if st.session_state.uid is None:
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Login")
            u = st.text_input("Username", key="l_u")
            p = st.text_input("Password", type="password", key="l_p")
            if st.button("Login"):
                conn = sqlite3.connect(DB_NAME)
                res = conn.execute("SELECT id, password FROM users WHERE username=?", (u,)).fetchone()
                if res and bcrypt.checkpw(p.encode(), res[1]):
                    st.session_state.uid = res[0]
                    st.query_params["user_id"] = str(res[0]) # Save to URL for Refresh
                    st.rerun()
                else: st.error("Invalid Credentials")
        with col2:
            st.subheader("Register")
            nu, nem, nph, npw = st.text_input("Name"), st.text_input("Email"), st.text_input("Phone"), st.text_input("Pass", type="password")
            if st.button("Register"):
                if nu and nem and nph and npw:
                    h = bcrypt.hashpw(npw.encode(), bcrypt.gensalt())
                    conn = sqlite3.connect(DB_NAME)
                    try:
                        conn.execute("INSERT INTO users (username, email, phone, password) VALUES (?,?,?,?)", (nu, nem, nph, h))
                        conn.commit()
                        st.success("Registration Successful!")
                    except: st.error("Username already exists.")
        st.stop()

    # --- DASHBOARD ---
    st.sidebar.title("Guardian Dashboard")
    st.sidebar.info(f"Logged in: User {st.session_state.uid}")
    if st.sidebar.button("Logout"):
        st.session_state.uid = None
        st.query_params.clear() # Clear URL session
        st.rerun()

    tab1, tab2, tab3, tab4 = st.tabs(["📚 Shared Library", "📤 Upload Content", "🔍 Forensic Detector", "👥 Admin"])

    with tab1:
        st.header("Available Content")
        conn = sqlite3.connect(DB_NAME)
        vids = conn.execute("SELECT filename FROM videos").fetchall()
        for v in vids:
            fname = v[0]
            if st.button(f"Download Protected Copy: {fname}", key=fname):
                with st.spinner("Locking Watermark..."):
                    with tempfile.TemporaryDirectory() as tmp:
                        in_v = os.path.join(UPLOAD_DIR, fname)
                        in_a, out_a, out_v = os.path.join(tmp,"1.wav"), os.path.join(tmp,"2.wav"), os.path.join(tmp,"out.mp4")
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-vn","-acodec","pcm_s16le",in_a], capture_output=True)
                        embed_watermark(in_a, out_a, st.session_state.uid)
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-i",out_a,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac",out_v], capture_output=True)
                        with open(out_v, "rb") as f:
                            st.download_button("Click to Download", f.read(), file_name=f"secured_{fname}")

    with tab2:
        up_file = st.file_uploader("Upload Master Video")
        if up_file and st.button("Confirm Master Upload"):
            path = os.path.join(UPLOAD_DIR, up_file.name)
            with open(path, "wb") as f: f.write(up_file.read())
            conn = sqlite3.connect(DB_NAME)
            conn.execute("INSERT INTO videos (filename, uploader_id) VALUES (?,?)", (up_file.name, st.session_state.uid))
            conn.commit()
            st.success("Master video saved in central repository.")

    with tab3:
        st.header("Forensic Analysis")
        leak_file = st.file_uploader("Upload Leaked/Pirated Video", type=['mp4','mkv'])
        if leak_file and st.button("Run Extraction Scan"):
            with tempfile.TemporaryDirectory() as tmp:
                leak_path = os.path.join(tmp, "leak.mp4")
                with open(leak_path, "wb") as f: f.write(leak_file.read())
                leak_wav = os.path.join(tmp, "leak.wav")
                subprocess.run(["ffmpeg","-i",leak_path,"-acodec","pcm_s16le",leak_wav], capture_output=True)
                
                result = extract_watermark(leak_wav)
                if result:
                    st.error(f"🚨 PIRATER IDENTIFIED: {result}")
                    st.balloons()
                else:
                    st.warning("No valid watermark detected in this file.")

    with tab4:
        st.header("User Management")
        conn = sqlite3.connect(DB_NAME)
        st.dataframe(pd.read_sql_query("SELECT id, username, email, phone FROM users", conn))

if __name__ == "__main__":
    main()
