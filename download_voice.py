#!/usr/bin/env python3
"""
Quick script to download Piper voice models for JARVIS.

Usage:
    python download_voice.py amy        # Download Amy (female) - RECOMMENDED
    python download_voice.py libritts   # Download LibriTTS (female, high quality)
    python download_voice.py semaine    # Download Semaine (British female)
    python download_voice.py lessac     # Download Lessac (male)
    python download_voice.py joe        # Download Joe (male)
"""

import sys
from pathlib import Path
import urllib.request
import shutil

VOICES = {
    'amy': {
        'name': 'en_US-amy-medium',
        'description': 'Friendly, natural female voice',
        'size': '63 MB',
        'voice': 'amy',
        'locale': 'en_US',
        'quality': 'medium',
    },
    'libritts': {
        'name': 'en_US-libritts-high',
        'description': 'High-quality, expressive female voice',
        'size': '486 MB',
        'voice': 'libritts',
        'locale': 'en_US',
        'quality': 'high',
    },
    'semaine': {
        'name': 'en_GB-semaine-medium',
        'description': 'British female voice',
        'size': '73 MB',
        'voice': 'semaine',
        'locale': 'en_GB',
        'quality': 'medium',
    },
    'lessac': {
        'name': 'en_US-lessac-medium',
        'description': 'Natural male voice',
        'size': '70 MB',
        'voice': 'lessac',
        'locale': 'en_US',
        'quality': 'medium',
    },
    'joe': {
        'name': 'en_US-joe-medium',
        'description': 'Deep, warm male voice',
        'size': '89 MB',
        'voice': 'joe',
        'locale': 'en_US',
        'quality': 'medium',
    }
}

HF_BASE = 'https://huggingface.co/rhasspy/piper-voices/resolve/main'

def download_voice(voice_key):
    """Download a voice model and its metadata."""
    if voice_key not in VOICES:
        print(f'❌ Unknown voice: {voice_key}')
        print(f'Available: {", ".join(VOICES.keys())}')
        return False
    
    voice = VOICES[voice_key]
    name = voice['name']
    desc = voice['description']
    size = voice['size']
    
    print(f'\n🎤 Downloading {name}')
    print(f'   Description: {desc}')
    print(f'   Size: {size}')
    print()
    
    # Determine path
    model_dir = Path('models/piper')
    model_dir.mkdir(parents=True, exist_ok=True)
    
    # Build correct URL - format: lang/locale/voice/quality/full_name.onnx
    # e.g., en/en_US/amy/medium/en_US-amy-medium.onnx
    voice_name = voice['voice']
    locale = voice['locale']
    quality = voice['quality']
    lang_folder = locale.split('_')[0]  # e.g., 'en' from 'en_US' or 'en_GB'
    
    onnx_url = f'{HF_BASE}/{lang_folder}/{locale}/{voice_name}/{quality}/{name}.onnx'
    onnx_path = model_dir / f'{name}.onnx'
    json_url = f'{HF_BASE}/{lang_folder}/{locale}/{voice_name}/{quality}/{name}.onnx.json'
    json_path = model_dir / f'{name}.onnx.json'
    
    try:
        print(f'📥 Downloading {name}.onnx...')
        print(f'   URL: {onnx_url}')
        urllib.request.urlretrieve(onnx_url, onnx_path, _progress_hook)
        print(f'\n✅ Downloaded to {onnx_path}')
        
        print(f'📥 Downloading {name}.onnx.json...')
        urllib.request.urlretrieve(json_url, json_path)
        print(f'✅ Downloaded to {json_path}')
        
        print(f'\n✨ Voice ready! Update .env:')
        print(f'   JARVIS_TTS_ENABLED=true')
        print(f'   JARVIS_PIPER_MODEL=models/piper/{name}.onnx')
        print(f'\nThen run: pip install -e ".[voice-output]"')
        print(f'And test with: python main.py')
        return True
    
    except Exception as e:
        print(f'\n❌ Download failed: {e}')
        print(f'\n💡 Manual download (PowerShell):')
        print(f'   1. Create folder: mkdir models/piper -Force')
        lang = 'en_GB' if 'semaine' in name else 'en'
        print(f'   2. Download .onnx file:')
        print(f'      $url = "{onnx_url}"')
        print(f'      Invoke-WebRequest $url -OutFile "{onnx_path}"')
        print(f'   3. Download .json file:')
        print(f'      $url = "{json_url}"')
        print(f'      Invoke-WebRequest $url -OutFile "{json_path}"')
        print(f'\nOr visit: https://huggingface.co/rhasspy/piper-voices/tree/main/{lang}/{name}')
        return False

def _progress_hook(block_num, block_size, total_size):
    """Show download progress."""
    downloaded = block_num * block_size
    if total_size > 0:
        percent = min(100, (downloaded / total_size) * 100)
        bar_length = 40
        filled = int(bar_length * percent / 100)
        bar = '█' * filled + '░' * (bar_length - filled)
        print(f'\r[{bar}] {percent:.1f}%', end='', flush=True)

def main():
    if len(sys.argv) < 2:
        print('🎤 Piper Voice Downloader for JARVIS')
        print('\nUsage: python download_voice.py <voice>')
        print('\nAvailable voices:')
        for key, info in VOICES.items():
            print(f'  {key:12} - {info["description"]} ({info["size"]})')
        print('\nExample:')
        print('  python download_voice.py amy        # Recommended: friendly female voice')
        print('  python download_voice.py libritts   # High-quality female voice')
        return
    
    voice_key = sys.argv[1].lower()
    success = download_voice(voice_key)
    sys.exit(0 if success else 1)

if __name__ == '__main__':
    main()
