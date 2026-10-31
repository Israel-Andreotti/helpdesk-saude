from django.contrib import admin
from django.templatetags.static import static
from django.urls import include, path
from django.views.generic import RedirectView

urlpatterns = [
    # Navegadores pedem /favicon.ico por conta própria (ex.: no admin, que não usa base.html).
    path('favicon.ico', RedirectView.as_view(url=static('img/favicon.svg'), permanent=False)),
    path('admin/', admin.site.urls),
    path('', include('core.urls')),
    path('usuarios/', include('usuarios.urls')),
    path('chamados/', include('chamados.urls')),
    path('ativos/', include('ativos.urls')),
    path('indicadores/', include('indicadores.urls')),
]
