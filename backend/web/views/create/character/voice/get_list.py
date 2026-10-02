from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from django.db.models import Q

from web.models.character import Voice


def visible_voices(user):
    return Voice.objects.filter(Q(owner=user) | Q(owner__isnull=True)).order_by('id')


def voice_data(voice):
    return {'id': voice.id, 'name': voice.name, 'is_custom': voice.owner_id is not None}


class GetVoiceList(APIView):
    permission_classes = [IsAuthenticated]
    def get(self,request):
        try:
            voices = [voice_data(v) for v in visible_voices(request.user)]
            return Response({
                'result': 'success',
                'voices': voices,
            })
        except:
            return Response({
                'result': '系统异常，请稍后重试'
            })
