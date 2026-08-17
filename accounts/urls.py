from django.contrib.auth import views as auth_views
from django.urls import path

from . import views

app_name = 'accounts'

urlpatterns = [
    path('login/', views.LoginRateLimitedView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(), name='logout'),
    path('registro/', views.register, name='register'),
    path('perfil/', views.profile, name='profile'),
    path('cambiar-clave/', auth_views.PasswordChangeView.as_view(
        template_name='accounts/password_change.html',
        success_url='/accounts/cambiar-clave/listo/',
    ), name='password_change'),
    path('cambiar-clave/listo/', auth_views.PasswordChangeDoneView.as_view(
        template_name='accounts/password_change_done.html',
    ), name='password_change_done'),
]
