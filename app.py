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
# AES-128-ku 16 characters key irundha podhum
SECRET_KEY = "My16ByteSecret!!" 
GAIN_FACTOR = 0.007 # Noise level (Viewers-ku kekkaadhu)

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

# --- 2. AES-128 ENCRYPTION & DSSS CORE ---

def encrypt_user_id(user_id):
    """AES-128 encryption for the User ID only."""
    data = f"USER_{user_id}"
    # Key-ah exact-ah 16 bytes-ah mathurom (AES-128)
    key = SECRET_KEY.ljust(16)[:16].encode()
    cipher = AES.new(key, AES.MODE_CBC)
    ct_bytes = cipher.encrypt(pad(data.encode(), AES.block_size))
    # IV + Encrypted Data
    combined = cipher.iv + ct_bytes
    return "".join([format(b, '08b') for b in combined])

def decrypt_user_id(bit_string):
    """AES-128 decryption to get back User ID."""
    try:
        key = SECRET_KEY.ljust(16)[:16].encode()
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
    # User ID-ya mattum encrypt panni bits-ah mathurom
    bit_str = encrypt_user_id(user_id)
    bits = [int(b) for b in bit_str]
    
    with wave.open(input_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio_samples = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    total_samples = len(audio_samples)
    pn = generate_pn_sequence(total_samples)
    
    # 5-second chunks redundancy
    segment_len = 5 * params.framerate
    num_segments = total_samples // segment_len
    watermark = np.zeros(total_samples)

    for s in range(num_segments):
        start_idx = s * segment_len
        sf = segment_len // len(bits)
        for i, bit in enumerate(bits):
            val = 1 if bit == 1 else -1
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            # Spreading the encrypted bits with PN sequence
            watermark[b_start:b_end] = val * pn[b_start:b_end]

    # Watermark-ah audio-la add pannurom
    result = np.clip(audio_samples + (GAIN_FACTOR * watermark * np.max(np.abs(audio_samples))), -32768, 32767).astype(np.int16)
    with wave.open(output_wav, 'wb') as out:
        out.setparams(params)
        out.writeframes(result.tobytes())

def extract_watermark(leaked_wav):
    with wave.open(leaked_wav, 'rb') as wav:
        params, frames = wav.getparams(), wav.readframes(wav.getparams().nframes)
        audio = np.frombuffer(frames, dtype=np.int16).astype(np.float64)

    segment_len = 5 * params.framerate
    # AES-128 combined length (IV 16 + Data 16) = 32 bytes = 256 bits
    bit_len = 256 
    pn = generate_pn_sequence(len(audio))
    
    for s in range(min(20, len(audio)//segment_len)):
        start_idx = s * segment_len
        sf = segment_len // bit_len
        extracted_bits = ""
        
        for i in range(bit_len):
            b_start, b_end = start_idx + (i*sf), start_idx + ((i+1)*sf)
            correlation = np.sum(audio[b_start:b_end] * pn[b_start:b_end])
            extracted_bits += "1" if correlation > 0 else "0"
        
        # Bits-ah decrypt panni User ID-ya check pannurom
        decrypted = decrypt_user_id(extracted_bits)
        if decrypted and "USER_" in decrypted:
            return decrypted
    return None

# --- [STREAMLIT UI CODE REMAINS THE SAME] ---
# (Pazhaya code-la irundha main() function logic-ah inga use panniko)
