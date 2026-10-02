import io
import json
import os
from pathlib import Path
import time
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
import wave

from run import configure_django, temporary_workspace


def wav_bytes(width=2, seconds=6, rate=16000):
    output = io.BytesIO()
    with wave.open(output, 'wb') as audio:
        audio.setnchannels(1)
        audio.setsampwidth(width)
        audio.setframerate(rate)
        audio.writeframes(b'\0' * width * rate * seconds)
    return output.getvalue()


class VoiceCloneTests(unittest.TestCase):
    def test_upload_provider_download_cleanup_and_library_permissions(self):
        with temporary_workspace() as directory:
            configure_django(directory)
            import requests
            from django.contrib.auth.models import User
            from django.core.files.uploadedfile import SimpleUploadedFile
            from django.test import Client, TestCase, override_settings
            from django.test.runner import DiscoverRunner
            from rest_framework.test import APIClient
            from web.models.character import Character, Voice
            from web.models.user import UserProfile
            from web.views.create.character.voice.clone import SAMPLE_TTL

            checks = self
            root = Path(directory) / 'samples'

            class FlowChecks(TestCase):
                def setUp(self):
                    self.user = User.objects.create_user(username='voice-owner')
                    self.other = User.objects.create_user(username='voice-other')
                    self.profile = UserProfile.objects.create(user=self.user)
                    UserProfile.objects.create(user=self.other)
                    self.client = APIClient()
                    self.client.force_authenticate(self.user)
                    self.shared = Voice.objects.create(name='公共音色', voice_id='shared')
                    self.foreign = Voice.objects.create(name='别人的音色', voice_id='foreign', owner=self.other)
                    self.url = '/api/create/character/voice/clone/'

                def upload(self, name='sample.wav', content=None, label='我的声音'):
                    return self.client.post(self.url, {
                        'name': label,
                        'audio': SimpleUploadedFile(name, wav_bytes() if content is None else content),
                    }, format='multipart')

                def test_provider_download_and_private_library(self):
                    raw = wav_bytes()
                    def provider(url, headers, json, timeout):
                        checks.assertEqual(json['model'], 'voice-enrollment')
                        checks.assertEqual(json['input']['action'], 'create_voice')
                        checks.assertRegex(json['input']['prefix'], r'^[A-Za-z0-9]{1,10}$')
                        checks.assertEqual(timeout, (5, 90))
                        parsed = urlsplit(json['input']['url'])
                        checks.assertEqual(parsed.netloc, 'voice.example.com')
                        sample = parsed.path + '?' + parsed.query
                        anonymous = Client()
                        downloaded = anonymous.get(sample)
                        try:
                            checks.assertEqual(downloaded.status_code, 200)
                            checks.assertEqual(downloaded['Content-Type'], 'audio/wav')
                            checks.assertEqual(downloaded['Cache-Control'], 'no-store')
                            checks.assertEqual(b''.join(downloaded.streaming_content), raw)
                        finally:
                            downloaded.close()
                        checks.assertEqual(anonymous.get(parsed.path).status_code, 404)
                        checks.assertEqual(anonymous.get(sample + 'invalid').status_code, 404)
                        with patch('django.core.signing.time.time', return_value=time.time() + SAMPLE_TTL + 2):
                            checks.assertEqual(anonymous.get(sample).status_code, 404)
                        self.download_url = sample
                        response = requests.Response()
                        response.status_code = 200
                        response._content = b'{"output":{"voice_id":"cloned-voice"}}'
                        return response
                    with patch('web.views.create.character.voice.custom.create_voice.requests.post', side_effect=provider) as call:
                        response = self.upload(content=raw)
                    checks.assertEqual(response.status_code, 201)
                    call.assert_called_once()
                    voice = Voice.objects.get(pk=response.data['voice']['id'])
                    checks.assertEqual(voice.owner, self.user)
                    checks.assertEqual(voice.voice_id, 'cloned-voice')
                    checks.assertTrue(response.data['voice']['is_custom'])
                    checks.assertEqual(list(root.iterdir()), [])
                    checks.assertEqual(Client().get(self.download_url).status_code, 404)
                    owned = self.client.get('/api/create/character/voice/get_list/').data['voices']
                    checks.assertEqual({v['id'] for v in owned}, {voice.pk, self.shared.pk})
                    self.client.force_authenticate(self.other)
                    other = self.client.get('/api/create/character/voice/get_list/').data['voices']
                    checks.assertEqual({v['id'] for v in other}, {self.foreign.pk, self.shared.pk})

                def test_validation_rejects_inputs_without_provider_calls(self):
                    with patch('web.views.create.character.voice.clone.create_voice') as call:
                        self.client.force_authenticate(None)
                        checks.assertEqual(self.upload().status_code, 401)
                        self.client.force_authenticate(self.user)
                        for name, audio in [
                            ('fake.wav', b'not audio'), ('wide.wav', wav_bytes(width=3)),
                            ('short.wav', wav_bytes(seconds=2)), ('low.wav', wav_bytes(rate=8000)),
                            ('truncated.wav', wav_bytes()[:-20]), ('bad.mp3', b'not mp3'),
                            ('bad.m4a', b'not m4a'), ('file.exe', wav_bytes()),
                            ('large.mp3', b'ID3' + b'x' * (10 * 1024 * 1024)),
                        ]:
                            checks.assertEqual(self.upload(name=name, content=audio).status_code, 400, name)
                        checks.assertEqual(self.upload(label='').status_code, 400)
                        for origin in ['', 'http://localhost:8000', 'http://127.0.0.1:8000', 'http://192.168.1.3:8000', 'https://user:pass@host.example']:
                            with override_settings(VOICE_PUBLIC_BASE_URL=origin):
                                checks.assertEqual(self.upload().status_code, 400)
                        with patch.dict(os.environ, {'API_KEY': ''}):
                            checks.assertEqual(self.upload().status_code, 503)
                        call.assert_not_called()

                def test_failure_cleanup_and_compressed_upload_forwarding(self):
                    samples = [
                        ('sample.mp3', b'ID3' + b'\0' * 20, 'audio/mpeg'),
                        ('sample.m4a', b'\0\0\0\x18ftypM4A ' + b'\0' * 20, 'audio/mp4'),
                    ]
                    for name, raw, mime in samples:
                        def clone(url, prefix):
                            parsed = urlsplit(url)
                            downloaded = Client().get(parsed.path + '?' + parsed.query)
                            try:
                                checks.assertEqual(downloaded['Content-Type'], mime)
                                checks.assertEqual(b''.join(downloaded.streaming_content), raw)
                            finally:
                                downloaded.close()
                            return {'output': {'voice_id': 'mock-' + name}}
                        with patch('web.views.create.character.voice.clone.create_voice', side_effect=clone):
                            checks.assertEqual(self.upload(name=name, content=raw).status_code, 201)
                    count = Voice.objects.count()
                    for failure, expected_status in [(requests.Timeout(), 504), (requests.ConnectionError(), 502), (ValueError('bad json'), 502)]:
                        with patch('web.views.create.character.voice.clone.create_voice', side_effect=failure):
                            checks.assertEqual(self.upload().status_code, expected_status)
                        checks.assertEqual(list(root.iterdir()), [])
                        checks.assertEqual(Voice.objects.count(), count)
                    response = requests.Response()
                    response.status_code = 403
                    response._content = json.dumps({'code': 'InsufficientBalance', 'request_id': 'trace-123',
                        'message': 'secret-key-in-provider-message'}).encode()
                    with patch('web.views.create.character.voice.custom.create_voice.requests.post', return_value=response):
                        failed = self.upload()
                    checks.assertEqual(failed.status_code, 502)
                    checks.assertEqual(failed.data['provider_code'], 'InsufficientBalance')
                    checks.assertNotIn('secret-key', str(failed.data))
                    checks.assertEqual(list(root.iterdir()), [])
                    for invalid in [{'output': {}}, {'output': {'voice_id': ' '}}]:
                        with patch('web.views.create.character.voice.clone.create_voice', return_value=invalid):
                            checks.assertEqual(self.upload().status_code, 502)
                    checks.assertEqual(Voice.objects.count(), count)

                def test_character_cannot_use_another_users_voice(self):
                    character = Character.objects.create(author=self.profile, name='角色', profile='人设',
                        voice=self.shared, photo='keep.png', background_image='keep-background.png')
                    data = {'name': '角色', 'profile': '人设', 'voice_id': self.foreign.pk}
                    response = self.client.post('/api/create/character/create/', {**data,
                        'photo': SimpleUploadedFile('photo.png', b'fake'),
                        'background_image': SimpleUploadedFile('background.png', b'fake')}, format='multipart')
                    checks.assertEqual(response.status_code, 400)
                    with patch('web.views.create.character.update.remove_old_photo') as remove:
                        response = self.client.post('/api/create/character/update/', {**data, 'character_id': character.pk,
                            'photo': SimpleUploadedFile('photo.png', b'fake')}, format='multipart')
                    checks.assertEqual(response.status_code, 400)
                    remove.assert_not_called()
                    character.refresh_from_db()
                    checks.assertEqual(character.voice, self.shared)
                    single = self.client.get('/api/create/character/get_single/', {'character_id': character.pk}).data
                    checks.assertEqual({v['id'] for v in single['voices']}, {self.shared.pk})

            runner = DiscoverRunner(verbosity=0, interactive=False)
            runner.setup_test_environment()
            database = runner.setup_databases()
            try:
                with override_settings(VOICE_PUBLIC_BASE_URL='https://voice.example.com', VOICE_SAMPLE_ROOT=root), patch.dict(
                    os.environ, {'API_KEY': 'test-key', 'VOICE_URL': 'https://provider.example.com/voice'},
                ):
                    result = runner.run_suite(unittest.defaultTestLoader.loadTestsFromTestCase(FlowChecks))
                    self.assertTrue(result.wasSuccessful(), result.errors + result.failures)
            finally:
                runner.teardown_databases(database)
                runner.teardown_test_environment()
