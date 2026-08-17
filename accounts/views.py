"""
Vistas de cuentas.

Se agrega un límite de intentos de login por IP, que el original no tenía:
el formulario de `LoginView` estaba expuesto sin ninguna traba a fuerza bruta.
"""
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import UserCreationForm
from django.core.cache import cache
from django.shortcuts import redirect, render

MAX_INTENTOS = 10
VENTANA_SEGUNDOS = 900


class LoginRateLimitedView(auth_views.LoginView):
    template_name = 'accounts/login.html'
    redirect_authenticated_user = True

    def _clave(self):
        ip = self.request.META.get('HTTP_X_FORWARDED_FOR', '').split(',')[0].strip()
        ip = ip or self.request.META.get('REMOTE_ADDR', 'desconocida')
        return f'login_intentos_{ip}'

    def form_invalid(self, form):
        clave = self._clave()
        intentos = cache.get(clave, 0) + 1
        cache.set(clave, intentos, VENTANA_SEGUNDOS)
        if intentos >= MAX_INTENTOS:
            messages.error(
                self.request,
                'Demasiados intentos fallidos. Espera unos minutos antes de reintentar.',
            )
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._clave())
        return super().form_valid(form)

    def post(self, request, *args, **kwargs):
        if cache.get(self._clave(), 0) >= MAX_INTENTOS:
            messages.error(
                request, 'Demasiados intentos fallidos. Espera unos minutos antes de reintentar.'
            )
            return self.form_invalid(self.get_form())
        return super().post(request, *args, **kwargs)


def register(request):
    if request.user.is_authenticated:
        return redirect('dashboard')
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, 'Cuenta creada. Ya puedes iniciar sesión.')
            return redirect('accounts:login')
    else:
        form = UserCreationForm()
    return render(request, 'accounts/register.html', {'form': form})


@login_required
def profile(request):
    from valorizador.models import Cartera, ContratoForward, ValorizacionGuardada

    return render(request, 'accounts/profile.html', {
        'n_contratos': ContratoForward.objects.filter(created_by=request.user).count(),
        'n_carteras': Cartera.objects.filter(created_by=request.user).count(),
        'n_valorizaciones': ValorizacionGuardada.objects.filter(created_by=request.user).count(),
    })
