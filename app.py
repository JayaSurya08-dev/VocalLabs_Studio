from flask import Flask, request, render_template,send_from_directory,redirect,url_for,jsonify,session
from joblib import Parallel, delayed
import os
import subprocess
import time
import librosa
import noisereduce as nr
import numpy as np
import soundfile as sf
from werkzeug.utils import secure_filename
from pydub import AudioSegment
import firebase_admin
from firebase_admin import credentials, auth,firestore
from dotenv import load_dotenv 
import requests
from urllib.parse import quote


app = Flask(__name__, static_folder="static")

load_dotenv()
app.secret_key = os.getenv("SECRET_KEY")
UPLOAD_FOLDER = "uploads"
OUTPUT_FOLDER = "static/output"  # ✅ Store files in static for frontend access

app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["OUTPUT_FOLDER"] = OUTPUT_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 50 * 1024 * 1024  # 50MB file size limit

@app.route('/static/<path:filename>')
def static_files(filename):
    return send_from_directory('static', filename)

# Ensure directories exist
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
os.makedirs(OUTPUT_FOLDER, exist_ok=True)

# Check if Spleeter & FFmpeg are installed
def check_dependencies():
    try:
        subprocess.run(["spleeter", "-h"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("Error: Spleeter or FFmpeg not found. Install them before running the app.")
        exit(1)

check_dependencies()

def convert_wav_to_mp3(input_wav, output_mp3):
    command = ["ffmpeg", "-i", input_wav, "-acodec", "libmp3lame", "-ab", "192k", output_mp3]
    result = subprocess.run(command, capture_output=True, text=True)
    
    if result.returncode != 0:
        print(f"FFmpeg Error: {result.stderr}")

def parallel_conversion(wav_files, mp3_files):
    Parallel(n_jobs=-1)(delayed(convert_wav_to_mp3)(wav, mp3) for wav, mp3 in zip(wav_files, mp3_files))


# Vocal Remover
@app.route("/upload", methods=["POST"])
def upload_file():
    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    if "file" not in request.files:
        return "No file uploaded", 400

    file = request.files["file"]
    if file.filename == "":
        return "No file selected", 400

    filename = secure_filename(file.filename)
    unique_filename = f"{int(time.time())}_{filename}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(file_path)

    # Run Spleeter command
    command = [
        "spleeter", "separate",
        "-p", "spleeter:2stems",
        "-o", OUTPUT_FOLDER, 
        file_path
    ]

    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        return f"Error processing file: {result.stderr}", 500

    # Convert separated WAV files to MP3 and move them to static/output
    processed_files = []
    user_id = session["user"]["user_id"]
    for stem in ["vocals", "accompaniment"]:
        wav_file = os.path.join(OUTPUT_FOLDER, unique_filename.rsplit(".", 1)[0], f"{stem}.wav")
        mp3_file = os.path.join(OUTPUT_FOLDER, f"{unique_filename}_{stem}.mp3")
        convert_wav_to_mp3(wav_file, mp3_file)

        # Remove WAV file after conversion
        if os.path.exists(wav_file):
            os.remove(wav_file)
        
        # Store file information in Firestore
        file_url = url_for("static_files", filename=f"output/{unique_filename}_{stem}.mp3")
        safe_filename = quote(f"{unique_filename}_{stem}.mp3")

        file_data = {
            "name": f"{unique_filename}_{stem}.mp3",
            "url": file_url,
            "user_id": user_id,
            "timestamp": time.time()
        }
        db.collection("processed_files").add(file_data)
        processed_files.append(file_data)

    return render_template("download.html", song=unique_filename)

@app.route('/download/<filename>/<stem>')
def download_file(filename, stem):
    return send_from_directory(OUTPUT_FOLDER, f"{filename}_{stem}.mp3")


# Splitter
@app.route("/splitter_upload", methods=["POST"])
def splitter_upload():
    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    if "file" not in request.files:
        return jsonify({"error": "No file uploaded"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "No file selected"}), 400

    filename = secure_filename(file.filename)
    unique_filename = f"{int(time.time())}_{filename}"
    file_path = os.path.join(UPLOAD_FOLDER, unique_filename)
    file.save(file_path)

    # Run Spleeter
    command = [
        'spleeter', 'separate',
        '-p', 'spleeter:4stems',
        '-o', OUTPUT_FOLDER,
        file_path
    ]
    print(f"Running command: {' '.join(command)}")
    result = subprocess.run(command, capture_output=True, text=True)

    if result.returncode != 0:
        print("Spleeter Error:", result.stderr)
        print("Spleeter Output:", result.stdout)
        return jsonify({"error": f"Error processing file: {result.stderr}"}), 500

    # Convert WAV files to MP3 and store file info
    stem_folder = os.path.join(OUTPUT_FOLDER, unique_filename.rsplit(".", 1)[0])
    user_id = session["user"]["user_id"]

    for stem in ['vocals', 'bass', 'drums', 'other']:
        wav_file = os.path.join(stem_folder, f"{stem}.wav")
        mp3_file = os.path.join(OUTPUT_FOLDER, f"{unique_filename}_{stem}.mp3")

        if os.path.exists(wav_file):
            convert_wav_to_mp3(wav_file, mp3_file)
            os.remove(wav_file)

        # Construct URL and store file information in Firestore
        file_url = url_for('static_files', filename=f"output/{unique_filename}_{stem}.mp3")
        file_data = {
            "name": f"{unique_filename}_{stem}.mp3",
            "url": file_url,
            "user_id": user_id,
            "timestamp": time.time()
        }
        db.collection("processed_files").add(file_data)
        print(f"Stored file: {file_data['name']} for user {user_id}")

    return render_template("splitter_download.html", song=unique_filename)
    
# Noise Reducer
def reduce_noise(input_path, output_path):
    """Applies ultra-aggressive noise reduction while keeping speech clear."""
    print(f"Processing noise reduction for: {input_path}")

    # Load audio file
    y, sr = librosa.load(input_path, sr=None, mono=True)

    # Select noise profile (longer noise sample for better reduction)
    noise_start = int(sr * 0.1) # Start at 0.1s
    noise_end = int(sr * 2.0) # Use up to 2.0s

    if len(y) > noise_end:
        noise_sample = y[noise_start:noise_end]
    else:
        noise_sample = y[:min(len(y), noise_start)]

    # 🔹 **Aggressive multi-pass noise reduction**
    reduced_noise = nr.reduce_noise(y=y, sr=sr, y_noise=noise_sample, prop_decrease=0.98, stationary=False, n_fft=4096)
    reduced_noise = nr.reduce_noise(y=y, sr=sr, y_noise=noise_sample, prop_decrease=0.92, stationary=False, n_fft=4096)
    # 🔹 **Boost voice clarity**
    reduced_noise = librosa.util.normalize(reduced_noise) # Normalize volume
    reduced_noise = np.clip(reduced_noise * 2.2, -1.0, 1.0) # Boost volume (2.2x)

    # Save processed file
    sf.write(output_path, reduced_noise, sr)
    print(f" Ultra noise reduction complete. Saved to: {output_path}")

ALLOWED_EXTENSIONS = {"wav", "mp3", "flac", "ogg", "m4a"}

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

@app.route("/reduce-noise", methods=["POST"])
def noise_reducer():

    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401
    
    if "file" not in request.files:
        return "No file uploaded", 400

    file = request.files["file"]
    if not allowed_file(file.filename):
        return "Invalid file type. Please upload an audio file.", 400

    filename = secure_filename(file.filename)
    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_path = os.path.join(OUTPUT_FOLDER, filename)

    file.save(input_path)

    try:
        reduce_noise(input_path, output_path)
    except Exception as e:
        return f"Error processing file: {str(e)}", 500

    return render_template("download_noise.html", song=filename, processed_file=filename)

@app.route("/apply-noise-reduction", methods=["POST"])
def apply_noise_reduction():
    data = request.get_json()
    noiseLevel = float(data['noiseLevel'])
    filename = data['filename']

    input_path = os.path.join(UPLOAD_FOLDER, filename)
    output_filename = f"reduced_{noiseLevel}_{filename}"
    output_path = os.path.join(OUTPUT_FOLDER, output_filename)

    # Load audio file
    y, sr = librosa.load(input_path, sr=None, mono=True)

    # Apply noise reduction
    reduced_noise = nr.reduce_noise(y=y, sr=sr, prop_decrease=noiseLevel)

    # Save processed file
    sf.write(output_path, reduced_noise, sr)

    # Store file information in Firestore
    user_id = session["user"]["user_id"]
    file_url = url_for('download_reduced_noise_file', filename=output_filename)  # Unique route for noise-reduced files
    file_data = {
        "name": output_filename,
        "url": file_url,
        "user_id": user_id,
        "timestamp": time.time()
    }
    db.collection("processed_files").add(file_data)
    print(f"Stored file: {file_data['name']} for user {user_id}")

    # Return URLs for processed audio
    processedUrl = url_for('download_reduced_noise_file', filename=output_filename)  # Unique route
    downloadUrl = url_for('download_reduced_noise_file', filename=output_filename)  # Unique route
    return jsonify({'processedUrl': processedUrl, 'downloadUrl': downloadUrl})

@app.route("/download_reduced/<filename>")  # Unique route for noise-reduced files
def download_reduced_noise_file(filename):
    return send_from_directory(OUTPUT_FOLDER, filename, as_attachment=True)


#Pitcher and speed
@app.route("/pitch-speed", methods=["POST"])
def process_audio():

    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401
    
    if "audio" not in request.files:
        return redirect(request.url)
    
    file = request.files["audio"]
    if file.filename == "":
        return redirect(request.url)
    
    # Secure the filename to prevent directory traversal attacks
    filename = secure_filename(file.filename)
    filepath = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    file.save(filepath)

    return redirect(url_for("preview_page", filename=filename))

@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route("/download_pitcher")
def preview_page():
    filename = request.args.get("filename")
    if not filename:
        return "No filename provided", 400
    
    return render_template("download_pitcher.html", filename=filename)

def change_pitch_speed(input_path, output_path, pitch, speed):
    try:
        # Load MP3 with PyDub
        audio = AudioSegment.from_file(input_path, format="mp3")
        
        # Ensure 44.1kHz sample rate and mono (MP3 standard)
        audio = audio.set_frame_rate(44100).set_channels(1)

        # Export as WAV temporarily for processing
        temp_wav_path = "temp_audio.wav"
        audio.export(temp_wav_path, format="wav")

        # Load WAV with Librosa
        samples, sample_rate = librosa.load(temp_wav_path, sr=44100)

        # Apply speed change
        samples = librosa.effects.time_stretch(samples, rate=speed)

        # Apply pitch shift
        samples = librosa.effects.pitch_shift(samples, sr=sample_rate, n_steps=pitch)

        # Save as WAV first
        temp_processed_wav = "temp_processed.wav"
        sf.write(temp_processed_wav, samples, sample_rate, format="WAV", subtype="PCM_16")

        # Convert back to MP3
        processed_audio = AudioSegment.from_file(temp_processed_wav, format="wav")
        processed_audio.export(output_path, format="mp3", bitrate="192k")

        print(f"Processed MP3 saved: {output_path}")

    except Exception as e:
        print(f"Error processing file: {str(e)}")

@app.route("/apply_changes", methods=["POST"])
def apply_changes():
    data = request.json
    filename = data.get("filename")
    pitch = float(data.get("pitch", 0))
    speed = float(data.get("speed", 1.0))

    if not filename:
        return jsonify({"error": "Filename is missing"}), 400

    input_path = os.path.join(app.config["UPLOAD_FOLDER"], filename)
    output_filename = f"processed_{filename}"
    output_path = os.path.join(app.config["OUTPUT_FOLDER"], output_filename)

    if not os.path.exists(input_path):
        return jsonify({"error": "File not found"}), 404

    try:
        print(f"Processing file: {input_path}")
        change_pitch_speed(input_path, output_path, pitch, speed)

        # Store file information in Firestore
        user_id = session["user"]["user_id"]
        file_url = url_for('output_file', filename=output_filename)
        file_data = {
            "name": output_filename,
            "url": file_url,
            "user_id": user_id,
            "timestamp": time.time()
        }
        db.collection("processed_files").add(file_data)
        print(f"Stored file: {file_data['name']} for user {user_id}")

        download_url = url_for("output_file", filename=output_filename)
        return jsonify({"download_url": download_url})

    except Exception as e:
        print(f"Error processing file: {str(e)}")
        return jsonify({"error": "Failed to process audio"}), 500


@app.route("/output/<filename>")
def output_file(filename):
    return send_from_directory(app.config["OUTPUT_FOLDER"], filename)

@app.route("/config")
def get_config():
    return jsonify({
        "apiKey": os.getenv("FIREBASE_API_KEY"),
        "authDomain": os.getenv("FIREBASE_AUTH_DOMAIN"),
        "projectId": os.getenv("FIREBASE_PROJECT_ID"),
        "storageBucket": os.getenv("FIREBASE_STORAGE_BUCKET"),
        "messagingSenderId": os.getenv("FIREBASE_MESSAGING_SENDER_ID"),
        "appId": os.getenv("FIREBASE_APP_ID")
    })

cred = credentials.Certificate("config.json")
firebase_admin.initialize_app(cred)
db = firestore.client()  # Firestore database instance

@app.route("/signup", methods=["POST"])
def signup():
    data = request.json
    email = data.get("email")
    password = data.get("password")
    username = data.get("username")

    if not email or not password or not username:
        return jsonify({"error": "Missing required fields"}), 400

    try:
        # Create user in Firebase Authentication
        user = auth.create_user(
            email=email,
            password=password,
            display_name=username
        )

        # Store user data in Firestore
        user_ref = db.collection("users").document(user.uid)
        user_ref.set({
            "username": username,
            "email": email,
            "uid": user.uid,
        })

        return jsonify({"message": "User created successfully", "user_id": user.uid}), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/login", methods=["POST"])
def login():
    data = request.json
    email = data.get("email")
    password = data.get("password")

    if not email or not password:
        return jsonify({"error": "Missing email or password"}), 400

    try:
        api_key = os.getenv("FIREBASE_API_KEY")
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:signInWithPassword?key={api_key}"
        payload = {
            "email": email,
            "password": password,
            "returnSecureToken": True
        }
        response = requests.post(url, json=payload)
        data = response.json()

        if "idToken" in data:
            username = data.get("displayName", "User")  # Extract displayName or set default
            
            session["user"] = {
                "username": username,  # Ensure it's stored as "username" for frontend consistency
                "email": data["email"],
                "user_id": data["localId"]
            }

            return jsonify({
                "message": "Login successful",
                "user": session["user"],
                "idToken": data["idToken"]
            }), 200
        else:
            return jsonify({"error": data.get("error", {}).get("message", "Login failed")}), 400
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.route("/forgot-password", methods=["POST"])
def forgot_password():
    data = request.json
    email = data.get("email")

    if not email:
        return jsonify({"error": "Email is required"}), 400

    try:
        api_key = os.getenv("FIREBASE_API_KEY")
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:sendOobCode?key={api_key}"
        payload = {
            "requestType": "PASSWORD_RESET",
            "email": email
        }
        response = requests.post(url, json=payload)
        data = response.json()

        if "error" in data:
            return jsonify({"error": data["error"]["message"]}), 400

        return jsonify({"message": "Password reset email sent successfully."}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/reset-password", methods=["POST"])
def reset_password():
    data = request.json
    oob_code = data.get("oobCode")
    new_password = data.get("newPassword")

    if not oob_code or not new_password:
        return jsonify({"error": "Missing reset code or password"}), 400

    try:
        api_key = os.getenv("FIREBASE_API_KEY")
        url = f"https://identitytoolkit.googleapis.com/v1/accounts:resetPassword?key={api_key}"
        payload = {
            "oobCode": oob_code,
            "newPassword": new_password
        }
        response = requests.post(url, json=payload)
        data = response.json()

        if "error" in data:
            return jsonify({"error": data["error"]["message"]}), 400

        return jsonify({"message": "Password reset successful"}), 200

    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/reset-password", methods=["GET"])
def reset_password_page():
    return render_template("reset-password.html")

print("Firebase API Key:", os.getenv("FIREBASE_API_KEY"))

@app.route("/get-user-info", methods=["GET"])
def get_user_info():
    if "user" not in session:
        return jsonify({"error": "User not logged in"}), 401

    return jsonify(session["user"]), 200 

@app.route("/get-processed-files", methods=["GET"])
def get_processed_files():
    if "user" not in session:
        return jsonify({"error": "Unauthorized. Please log in first."}), 401

    user_id = session["user"]["user_id"]
    try:
        results = db.collection("processed_files").where("user_id", "==", user_id).get()
        if not results:
            return jsonify([]), 200  # Return an empty list if no files found

        files = [doc.to_dict() for doc in results]
        return jsonify(files), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/")
def home():
    return render_template("index.html")

@app.route("/splitter")
def splitter():
    return render_template("splitter.html")

@app.route("/reduce-noise")
def noise_reducer_page():
    return render_template("noise_reducer.html")

@app.route("/pitcher")
def pitcher():
    return render_template("pitcher_speed.html")

@app.route('/login')
def login_page():
    return render_template('login.html')

@app.route('/signup')
def signup_page():
    return render_template('signup.html')

@app.route("/logout")
def logout():
    session.clear() 
    return redirect(url_for("home"))

@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")

if __name__ == "__main__":
    app.run(debug=True)

