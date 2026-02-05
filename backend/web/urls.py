
from django.urls import path, re_path

from web.user.account.get_user_info import GetUserInfoView
from web.user.account.login import LoginView
from web.user.account.logout import LogoutView
from web.user.account.refresh_token import RefreshTokenView
from web.user.account.register import RegisterView
from web.views.index import index
urlpatterns = [
    path('api/user/account/login/',LoginView.as_view()),
    path('api/user/account/logout/',LogoutView.as_view()),
    path('api/user/account/register/',RegisterView.as_view()),
    path('api/user/account/refresh_token/',RefreshTokenView.as_view()),
    path('api/user/account/get_user_info/',GetUserInfoView.as_view()),
    path('',index),

    re_path(r'^(?!media/|static/|assets/).*$', index)
]
