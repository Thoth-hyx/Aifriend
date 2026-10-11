import os

import requests


def create_voice(voice_url,prefix):
    headers = {
        "Authorization": f"Bearer {os.getenv("API_KEY")}",
        "Content-Type": "application/json",
    }
    data = {
        "model": "voice-enrollment",
        "input": {
            "action": "create_voice",
            "target_model": "qwen-audio-3.1-tts-flash",
            "prefix": prefix,
            "url": voice_url,
        }
    }
    response = requests.post(os.getenv("VOICE_URL"), headers=headers, json=data, timeout=(5, 90))
    response.raise_for_status()
    return response.json()
