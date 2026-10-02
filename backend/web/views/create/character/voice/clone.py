import io
import ipaddress
import re
import wave
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4

import os
import requests
from django.conf import settings
from django.core import signing
from django.http import FileResponse, Http404
from django.urls import reverse
from rest_framework.exceptions import ValidationError
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from web.models.character import Voice
from web.views.create.character.voice.custom.create_voice import create_voice
from web.views.create.character.voice.get_list import voice_data

MAX_AUDIO_BYTES = 10 * 1024 * 1024
SAMPLE_TTL = 600
SIGNING_SALT = 'voice-enrollment-sample'
AUDIO_TYPES = {'.wav': 'audio/wav', '.mp3': 'audio/mpeg', '.m4a': 'audio/mp4'}


def validate_audio(upload):
    if upload is None:
        raise ValidationError({'result': '请选择需要复刻音色的音频'})
    suffix = Path(upload.name).suffix.lower()
    if suffix not in AUDIO_TYPES:
        raise ValidationError({'result': '仅支持 WAV（16bit）、MP3、M4A'})
    if not 0 < upload.size <= MAX_AUDIO_BYTES:
        raise ValidationError({'result': '音频文件不能为空，且不能超过 10 MB'})
    content = upload.read(MAX_AUDIO_BYTES + 1)
    if not content or len(content) > MAX_AUDIO_BYTES:
        raise ValidationError({'result': '音频文件不能为空，且不能超过 10 MB'})
    if suffix == '.wav':
        try:
            with wave.open(io.BytesIO(content), 'rb') as audio:
                if audio.getsampwidth() != 2 or audio.getcomptype() != 'NONE':
                    raise ValidationError({'result': 'WAV 必须为 16bit PCM 编码'})
                if audio.getframerate() < 16000 or audio.getnchannels() not in (1, 2):
                    raise ValidationError({'result': 'WAV 采样率需至少 16 kHz，声道为单声道或双声道'})
                frames = audio.getnframes()
                if not 5 <= frames / audio.getframerate() <= 60:
                    raise ValidationError({'result': 'WAV 时长需为 5～60 秒，建议使用 10～20 秒清晰朗读'})
                if len(audio.readframes(frames)) != frames * audio.getnchannels() * 2:
                    raise ValidationError({'result': 'WAV 数据不完整，请重新导出音频'})
        except (wave.Error, EOFError):
            raise ValidationError({'result': '不是有效的 WAV 音频文件'})
    elif suffix == '.mp3':
        if not (content.startswith(b'ID3') or (len(content) >= 4 and content[0] == 0xff and content[1] & 0xe0 == 0xe0)):
            raise ValidationError({'result': '不是有效的 MP3 文件头，请勿直接修改扩展名'})
    elif len(content) < 16 or content[4:8] != b'ftyp':
        raise ValidationError({'result': '不是有效的 M4A 文件头，请勿直接修改扩展名'})
    # ponytail: MP3/M4A container checks only; the provider validates decoding, duration and speech quality.
    return suffix, content


def public_origin():
    origin = settings.VOICE_PUBLIC_BASE_URL
    try:
        parsed = urlsplit(origin)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError
        parsed.port  # Validate the optional port.
        host = parsed.hostname.lower()
        if host == 'localhost' or host.endswith(('.localhost', '.local')):
            raise ValueError
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            address = None
        if address is not None and not address.is_global:
            raise ValueError
    except ValueError:
        raise ValidationError({'result': '请先在后端配置 VOICE_PUBLIC_BASE_URL 为百炼可访问的公网地址，不能使用 localhost、127.0.0.1 或内网 IP'})
    return origin.rstrip('/')


def provider_failure(data):
    data = data if isinstance(data, dict) else {}
    # Never relay raw provider messages, which can contain credentials or the signed audio URL.
    safe = lambda value: value if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,100}', value) else ''
    code = safe(data.get('code', ''))
    request_id = safe(data.get('request_id', ''))
    return {'result': '百炼音色复刻失败，请检查音频样本、模型权限和账户额度',
            'provider_code': code, 'request_id': request_id}


class CloneVoiceView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        name = request.data.get('name', '')
        if not isinstance(name, str) or not 1 <= len(name.strip()) <= 100:
            raise ValidationError({'result': '音色名称需要为 1～100 个字'})
        suffix, content = validate_audio(request.FILES.get('audio'))
        origin = public_origin()
        if not os.getenv('API_KEY') or not os.getenv('VOICE_URL'):
            return Response({'result': '后端尚未配置 API_KEY 或 VOICE_URL'}, status=503)
        root = Path(settings.VOICE_SAMPLE_ROOT)
        root.mkdir(parents=True, exist_ok=True)
        filename = uuid4().hex + suffix
        path = root / filename
        path.write_bytes(content)
        try:
            token = signing.dumps(filename, salt=SIGNING_SALT)
            url = origin + reverse('voice-clone-sample', args=[filename]) + '?token=' + token
            result = create_voice(url, uuid4().hex[:10])
            output = result.get('output') if isinstance(result, dict) else None
            voice_id = output.get('voice_id') if isinstance(output, dict) else None
            if not isinstance(voice_id, str) or not voice_id.strip() or len(voice_id) > 100:
                return Response(provider_failure(result), status=502)
            voice = Voice.objects.create(name=name.strip(), voice_id=voice_id, owner=request.user)
            return Response({'result': 'success', 'voice': voice_data(voice)}, status=201)
        except requests.Timeout:
            return Response({'result': '百炼请求超时，创建结果未确认；请先检查百炼音色列表，再决定是否重新提交'}, status=504)
        except requests.HTTPError as error:
            try:
                result = error.response.json()
            except (ValueError, AttributeError):
                result = {}
            return Response(provider_failure(result), status=502)
        except (requests.RequestException, ValueError):
            return Response({'result': '无法完成百炼复刻请求，请检查接口地址、网络和公网音频地址'}, status=502)
        finally:
            path.unlink(missing_ok=True)


class VoiceSampleView(APIView):
    permission_classes = [AllowAny]
    authentication_classes = []  # The short-lived signature authorizes the provider download.

    def get(self, request, filename):
        if not re.fullmatch(r'[0-9a-f]{32}\.(wav|mp3|m4a)', filename):
            raise Http404
        try:
            signed_name = signing.loads(request.query_params.get('token', ''), salt=SIGNING_SALT, max_age=SAMPLE_TTL)
        except signing.BadSignature:
            raise Http404
        if signed_name != filename:
            raise Http404
        try:
            audio = (Path(settings.VOICE_SAMPLE_ROOT) / filename).open('rb')
        except FileNotFoundError:
            raise Http404
        response = FileResponse(audio, content_type=AUDIO_TYPES[Path(filename).suffix])
        response['Cache-Control'] = 'no-store'
        response['X-Content-Type-Options'] = 'nosniff'
        response['Content-Disposition'] = f'inline; filename="{filename}"'
        return response
