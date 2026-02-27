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
DB_NAME = "guardian_ultimate.db" # Fresh DB for Final Test
UPLOAD_DIR = "master_videos"
SECRET_KEY = "My16ByteSecret!!" 

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

# --- 2. AES-128 & DSSS (The Core Security) ---

def encrypt_user_id(user_id):
    data = f"USER_{user_id}"
    key = SECRET_KEY.ljust(16)[:16].encode()
    cipher = AES.new(key, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
    combined = cipher.iv + ct_bytes # 32 bytes = 256 bits
    return "".join([format(b, '08b') for b in combined])

def decrypt_user_id(bit_string):
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
    bit_str = encrypt_user_id(user_id)
    bits = [int(b) for b in bit_str]
    
    with wave.open(input_wav, 'rb') as wav:
        params = wav.getparams()
        frames = wav.readframes(params.nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    
    total_samples = len(audio_samples)
    pn = generate_pn_sequence(total_samples)
    
    sf = total_samples // len(bits)
    watermark = np.zeros(total_samples)
    for i, bit in enumerate(bits):
        val = 1 if bit == 1 else -1
        watermark[i*sf : (i+1)*sf] = val * pn[i*sf : (i+1)*sf]

    # Solid Scaling for 15s clips
    max_amp = np.max(np.abs(audio_samples)) if np.max(np.abs(audio_samples)) > 0 else 32767
    result = audio_samples + (0.01 * watermark * max_amp) 
    result = np.clip(result, -32768, 32767).astype(np.int16)
    
    with wave.open(output_wav, 'wb') as out:
        out.setparams(params); out.writeframes(result.tobytes())

def extract_watermark(leaked_wav):
    with wave.open(leaked_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float64)
    
    bit_len = 256
    pn_full = generate_pn_sequence(len(audio))
    
    # Brute-force sync check (trying small offsets)
    for offset in range(0, 40, 4):
        search_audio = audio[offset:]
        search_pn = pn_full[offset:]
        sf = len(search_audio) // bit_len
        if sf <= 0: break
        
        extracted_bits = ""
        for i in range(bit_len):
            b_start, b_end = i*sf, (i+1)*sf
            correlation = np.sum(search_audio[b_start:b_end] * search_pn[b_start:b_end])
            extracted_bits += "1" if correlation > 0 else "0"
        
        res = decrypt_user_id(extracted_bits)
        if res and "USER_" in res: return res
    return None

# --- 3. MAIN UI ---
def main():
    st.set_page_config(page_title="Guardian Early Morning Fix", layout="wide")
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
                else: st.error("Login Error!")
        with c2:
            st.subheader("Register")
            nu, nem, nph, npw = st.text_input("Name"), st.text_input("Email"), st.text_input("Phone"), st.text_input("Pass", type="password")
            if st.button("Sign Up"):
                h = bcrypt.hashpw(npw.encode(), bcrypt.gensalt())
                conn = sqlite3.connect(DB_NAME)
                try:
                    conn.execute("INSERT INTO users (username, email, phone, password) VALUES (?,?,?,?)", (nu, nem, nph, h))
                    conn.commit()
                    st.success("Account created!")
                except: st.error("Error!")
        st.stop()

    st.sidebar.button("Logout", on_click=lambda: st.session_state.update({"uid": None}))
    
    t1, t2, t3, t4 = st.tabs(["📚 Shared Library", "📤 Upload", "🔍 Detector", "👥 Users"])

    with t1:
        conn = sqlite3.connect(DB_NAME)
        vids = conn.execute("SELECT filename FROM videos").fetchall()
        for v in vids:
            if st.button(f"Secure Download: {v[0]}", key=v[0]):
                with st.spinner("Processing..."):
                    with tempfile.TemporaryDirectory() as tmp:
                        in_v = os.path.join(UPLOAD_DIR, v[0])
                        in_a, out_a, out_v = os.path.join(tmp,"1.wav"), os.path.join(tmp,"2.wav"), os.path.join(tmp,"out.mp4")
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-vn","-acodec","pcm_s16le",in_a], capture_output=True)
                        embed_watermark(in_a, out_a, st.session_state.uid)
                        subprocess.run(["ffmpeg","-y","-i",in_v,"-i",out_a,"-map","0:v:0","-map","1:a:0","-c:v","copy","-c:a","aac",out_v], capture_output=True)
                        with open(out_v, "rb") as f:
                            st.download_button("Download Now", f.read(), file_name=f"secured_{v[0]}")

    with t2:
        up = st.file_uploader("Upload Master")
        if up and st.button("Save"):
            path = os.path.join(UPLOAD_DIR, up.name)
            with open(path, "wb") as f: f.write(up.read())
            conn = sqlite3.connect(DB_NAME)
            conn.execute("INSERT INTO videos (filename, uploader_id) VALUES (?,?)", (up.name, st.session_state.uid))
            conn.commit()
            st.success("Saved.")

    with t3:
        leak = st.file_uploader("Upload Leak")
        if leak and st.button("Identify Pirater"):
            with tempfile.TemporaryDirectory() as tmp:
                lp, lw = os.path.join(tmp, "l.mp4"), os.path.join(tmp, "l.wav")
                with open(lp, "wb") as f: f.write(leak.read())
                subprocess.run(["ffmpeg","-i",lp,"-acodec","pcm_s16le",lw], capture_output=True)
                res = extract_watermark(lw)
                if res: st.error(f"FOUND: {res}"); st.balloons()
                else: st.warning("Not found.")

    with t4:
        conn = sqlite3.connect(DB_NAME)
        st.table(pd.read_sql_query("SELECT id, username, email, phone FROM users", conn))

if __name__ == "__main__":
    main()
