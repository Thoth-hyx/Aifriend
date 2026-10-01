from django.conf import settings
from django.http import FileResponse
from django.shortcuts import render

def index(request):
    built_index = settings.BASE_DIR / 'static/frontend/index.html'
    if built_index.is_file():
        return FileResponse(built_index.open('rb'), content_type='text/html')
    return render(request, 'index.html')
