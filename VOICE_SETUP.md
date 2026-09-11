# JARVIS Voice Configuration Guide

## 🎤 Female Voice Setup (JARVIS Girl Mode)

To make JARVIS speak with a female voice, follow these steps:

### Step 1: Download a Female Voice Model

**Option A: Use Python download script (easiest)**
```powershell
python download_voice.py amy
```
This downloads Amy voice (~275 MB) and sets up everything automatically.

**Option B: Manual download with PowerShell**

```powershell
# Create models directory
mkdir models/piper -Force

# Download Amy voice metadata and model
$base = 'https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US-amy-medium'
Invoke-WebRequest "$base/en_US-amy-medium.onnx" -OutFile "models/piper/en_US-amy-medium.onnx"
Invoke-WebRequest "$base/en_US-amy-medium.onnx.json" -OutFile "models/piper/en_US-amy-medium.onnx.json"
```

**Available Female Voices:**
- **`en_US-amy-medium`** (275 MB) ⭐ RECOMMENDED
  - Friendly, natural female voice
  - https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US-amy-medium

- **`en_US-libritts-high`** (1 GB)
  - High-quality, expressive female voice
  - https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_US-libritts-high

- **`en_GB-semaine-medium`** (300 MB)
  - British female voice
  - https://huggingface.co/rhasspy/piper-voices/tree/main/en/en_GB-semaine-medium

### Step 2: Save to Models Directory

Files should be placed at:
- `models/piper/en_US-amy-medium.onnx`
- `models/piper/en_US-amy-medium.onnx.json`

If you downloaded manually, just extract both files into the `models/piper/` folder.

### Step 3: Update Configuration

Create or edit `.env` in the project root (copy from `.env.example` if needed):

```env
JARVIS_TTS_ENABLED=true
JARVIS_PIPER_MODEL=models/piper/en_US-amy-medium.onnx
```

### Step 4: Install Voice Output Dependencies (if needed)

```powershell
pip install -e ".[voice-output]"
```

This includes:
- **piper-tts** — Text-to-speech engine
- **sounddevice** — Audio playback
- **numpy** — Audio processing

### Step 5: Test It!

1. Start JARVIS:
   ```powershell
   python main.py
   ```

2. Send a message and it should respond with female voice! 🎤

3. Or start voice mode:
   ```
   > /voice
   Say something...
   ```

---

## 🎵 Voice Selection Tips

| Voice | Best For | File Size | Quality |
|-------|----------|-----------|---------|
| **amy-medium** | Conversational, friendly | 275 MB | Very Good |
| **libritts-high** | High-quality responses | 1 GB | Excellent |
| **semaine-medium** | British accent | 300 MB | Very Good |
| **lessac-medium** (male) | Deep voice | 250 MB | Very Good |
| **joe-medium** (male) | Warm male voice | 320 MB | Very Good |

---

## 🐛 Troubleshooting

### "Voice model not found"
- Make sure `.onnx` file exists at the path specified in `JARVIS_PIPER_MODEL`
- Verify path is relative to project root or absolute

### "Piper is missing"
- Run: `pip install -e ".[voice-output]"`

### "No sound output"
- Check speakers/headphones are connected
- Verify `JARVIS_TTS_ENABLED=true` in `.env`
- Test with: `python -c "from piper import PiperVoice; print('Piper OK')"`

### Model too slow
- Use `amy-medium` for fast response (CPU-friendly)
- Avoid `libritts-high` on slower systems

---

## 📱 Dashboard Voice

The web dashboard at `http://127.0.0.1:8765` uses **browser speech synthesis**. The female voice there is system-dependent (Windows Narrator voices). To customize:

1. Open browser DevTools (F12)
2. In Console, check available voices:
   ```javascript
   window.speechSynthesis.getVoices().forEach(v => console.log(v.name))
   ```

3. Edit [jarvis/api/ui/index.html](jarvis/api/ui/index.html) to select a specific voice:
   ```javascript
   utterance.voice = window.speechSynthesis.getVoices().find(v => v.name.includes('Female'));
   ```

---

Happy chatting with JARVIS! 💬✨
