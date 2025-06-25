# 🎙️ VocalLabs Studio

**VocalLabs Studio** is a web-based audio processing suite that empowers users to manipulate their audio tracks with features like **vocal removal**, **instrument splitting**, **noise reduction**, **pitch and speed adjustment**, and **karaoke mode**. Built with Flask (Python) on the backend and a responsive frontend, the platform is designed for music enthusiasts, creators, and editors.

---

## 🚀 Features

- 🎧 **Vocal Remover**  
  Remove vocals from any song to create karaoke tracks.

- 🎚️ **Instrument Splitter**  
  Separate different instruments from audio (drums, bass, vocals, etc.).

- 🔇 **Noise Reducer**  
  Clean audio recordings by removing background noise.

- 🎼 **Pitch & Speed Changer**  
  Modify pitch and tempo of songs with real-time preview.

- 🗂️ **User Dashboard**  
  View, re-download, and manage all previously processed files.

- 🔐 **Authentication System**  
  Email/password-based login and signup with secure session management.

---

## 🛠️ Tech Stack

| Layer        | Technology               |
| ------------ | ------------------------ |
| Frontend     | HTML, CSS, JavaScript    |
| Backend      | Python (Flask)           |
| Auth         | Firebase Authentication  |
| Database     | Firebase Realtime DB     |
| Audio APIs   | [Spleeter](https://github.com/deezer/spleeter), pydub, librosa |
| Hosting      | Flask Server (Local ready) |

---

## 📂 Project Structure

VocalLabs_Studio/
├── static/ # CSS, JS, images
├── templates/ # HTML pages
├── audio_processing/ # Audio handling scripts
├── routes/ # Flask route handlers
├── firebase_config.py # Firebase setup
├── app.py # Flask main app
└── README.md
