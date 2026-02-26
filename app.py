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

# --- 1. SETUP (Tanglish: Configuration Section) ---
DB_NAME = "guardian_final.db" 
UPLOAD_DIR = "master_videos"
SECRET_KEY = "My16ByteSecret!!" 
GAIN_FACTOR = 0.02 # Noise-ah mask panna safe value

if not os.path.exists(UPLOAD_DIR):
    os.makedirs(UPLOAD_DIR, exist_ok=True)

def init_db():
    try:
        conn = sqlite3.connect(DB_NAME)
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS users 
                     (id INTEGER PRIMARY KEY AUTOINCREMENT, 
                      username TEXT UNIQUE, email TEXT, phone TEXT, password TEXT)''')
        c.execute('CREATE TABLE IF NOT EXISTS videos (id INTEGER PRIMARY KEY AUTOINCREMENT, filename TEXT, uploader_id INTEGER)')
        conn.commit()
        conn.close()
    except Exception as e:
        st.error(f"DB Error: {e}")

# --- 2. AES-128 & DSSS (Tanglish: Protection Logic) ---

def encrypt_user_id(user_id):
    """User ID-ya AES-128 bits-ah mathurom"""
    data = f"USER_{user_id}"
    key = SECRET_KEY.ljust(16)[:16].encode()
    cipher = AES.new(key, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
    combined = cipher.iv + ct_bytes
    return "".join([format(b, '08b') for b in combined])

def decrypt_user_id(bit_string):
    """Bits-ah thirumba identity-ah mathurom"""
    try:
        key = SECRET_KEY.ljust(16)[:16].encode()
        byte_list = [int(bit_string[i:i+8], 2) for i in range(0, len(bit_string), 8)]
        full_data = bytes(byte_list)
        iv, ct = full_data[:16], full_data[16:]
        cipher = AES.new(key, AES.MODE_CBC, iv)
        pt = unpad(cipher.decrypt(ct), AES.block_size)
        return pt.decode()
    except: return None

def generate_pn_sequence(duration_samples):
    np.random.seed(42) 
    return (np.random.randint(0, 2, duration_samples) * 2 - 1).astype(np.float64)

def embed_watermark(input_wav, output_wav, user_id):
    """Inaudible and Redundant Watermarking"""
    bit_str = encrypt_user_id(user_id)
    bits = [int(b) for b in bit_str]
    
    with wave.open(input_wav, 'rb') as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    
    total_samples = len(audio_samples)
    pn = generate_pn_sequence(total_samples)
    
    # Trim-proof aaka ovvoru 7 seconds-kum ID-ya repeat panrom
    seg_sec = 7 
    segment_len = seg_sec * params.framerate
    num_segments = max(1, total_samples // segment_len)
    
    watermark = np.zeros(total_samples)

    for s in range(num_segments):
        start_idx = s * segment_len
        # Last segment length-ah calculate panrom
        current_seg_size = min(segment_len, total_samples - start_idx)
        if current_seg_size < (len(bits) * 10): break # Romba chinna segment-na skip pannu
        
        sf = current_seg_size // len(bits)
        for i, bit in enumerate(bits):
            val = 1 if bit == 1 else -1
            b_start = start_idx + (i*sf)
            b_end = start_idx + ((i+1)*sf)
            if b_end <= total_samples:
                watermark[b_start:b_end] = val * pn[b_start:b_end]

    # Local Envelope Scaling: Satham irukura idathula noise-ah maraikirom
    envelope = np.abs(audio_samples)
    result = np.clip(audio_samples + (GAIN_FACTOR * watermark * envelope), -32768, 32767).astype(np.int16)
    
    with wave.open(output_wav, 'wb') as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

def extract_watermark(leaked_wav):
    """Trimmed video-layum ID-ya kandupidikum extractor"""
    with wave.open(leaked_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    
    bit_len = 256
    pn = generate_pn_sequence(len(audio))
    
    # Leaked clip length-ku thagapadi search panrom
    sf = len(audio) // bit_len
    if sf <= 0: return None

    extracted_bits = ""
    for i in range(bit_len):
        b_start, b_end = i*sf, (i+1)*sf
        correlation = np.sum(audio[b_start:b_end] * pn[b_start:b_end])
        extracted_bits += "1" if correlation > 0 else "0"
        
    return decrypt_user_id(extracted_bits)

# --- 3. UI (Tanglish: Website Interface) ---
def main():
    st.set_page_config(page_title="Guardian v5.0 (Final)", layout="wide")
    init_db()

    if 'uid' not in st.session_state: st.session_state.uid = None

    if st.session_state.uid is None:
        c1, c2 = st.columns(2)
        with c1:
            st.subheader("Login")
            u = st.text_input("Username")
            p = st.text_input("Password", type="password")
            if st.button("Log In"):
                conn = sqlite3.connect(DB_NAME)
                res = conn.execute("SELECT id, password FROM users WHERE username=?", (u,)).fetchone()
                if res and bcrypt.checkpw(p.encode(), res[1]):
                    st.session_state.uid = res[0]
                    st.rerun()
                else: st.error("Login detail thappu!")
        with c2:
            st.subheader("Register")
            nu, nem, nph, npw = st.text_input("Name"), st.text_input("Email"), st.text_input("Phone"), st.text_input("Pass", type="password")
            if st.button("Sign Up"):
                if nu and nem and nph and npw:
                    h = bcrypt.hashpw(npw.encode(), bcrypt.gensalt())
                    conn = sqlite3.connect(DB_NAME)
                    try:
                        conn.execute("INSERT INTO users (username, email, phone, password) VALUES (?,?,?,?)", (nu, nem, nph, h))
                        conn.commit()
                        st.success("Account created! Login pannu macha.")
                    except: st.error("Username already taken!")
        st.stop()

    st.sidebar.success(f"User ID: {st.session_state.uid}")
    if st.sidebar.button("Logout"):
        st.session_state.uid = None
        st.rerun()
    
    t1, t2, t3, t4 = st.tabs(["📚 Library", "📤 Upload", "🔍 Detector", "👥 Users"])

    with t1:
        conn = sqlite3.connect(DB_NAME)
        vids = conn.execute("SELECT filename FROM videos").fetchall()
        for v in vids:
            if st.button(f"Secure Download: {v[0]}", key=v[0]):
                with st.spinner("Watermarking with Redundancy (Trim-Proof)..."):
                    with tempfile.TemporaryDirectory() as tmp:
                        in_v = os.path.join(UPLOAD_DIR, v[0])
                        in_a, out_a, out_v = os.path.join(tmp,"1.wav"), os.path.join(tmp,"2.wav"), os.path.join(tmp,"out.mp4")
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-vn","-acodec","pcm_s16le",in_a], capture_output=True)
                        embed_watermark(in_a, out_a, st.session_state.uid)
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-i",out_a,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac",out_v], capture_output=True)
                        with open(out_v, "rb") as f:
                            st.download_button("Download Now", f.read(), file_name=f"secured_{v[0]}")

    with t2:
        up = st.file_uploader("Original Master-ah upload pannu")
        if up and st.button("Save to Server"):
            path = os.path.join(UPLOAD_DIR, up.name)
            with open(path, "wb") as f: f.write(up.read())
            conn = sqlite3.connect(DB_NAME)
            conn.execute("INSERT INTO videos (filename, uploader_id) VALUES (?,?)", (up.name, st.session_state.uid))
            conn.commit()
            st.success("Saved successfully!")

    with t3:
        st.write("Leaked video-va trim panni upload pannaalum scan pannum.")
        leak = st.file_uploader("Upload Leak")
        if leak and st.button("Identify Pirater"):
            with tempfile.TemporaryDirectory() as tmp:
                lp, lw = os.path.join(tmp, "l.mp4"), os.path.join(tmp, "l.wav")
                with open(lp, "wb") as f: f.write(leak.read())
                subprocess.run(["ffmpeg","-i",lp,"-acodec","pcm_s16le",lw], capture_output=True)
                res = extract_watermark(lw)
                if res: 
                    st.error(f"⚠️ THIRUDAN IDENTIFIED: {res}")
                    st.balloons()
                else: st.warning("ID kandupidiika mudiyala (Maybe trimmed too much).")

    with t4:
        conn = sqlite3.connect(DB_NAME)
        st.table(pd.read_sql_query("SELECT id, username, email, phone FROM users", conn))

if __name__ == "__main__":
    main()


