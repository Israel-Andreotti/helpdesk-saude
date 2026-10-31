from django.urls import path

from . import views

app_name = 'core'

urlpatterns = [
    path('', views.inicio, name='inicio'),
    # Pré-visualização das páginas de erro (só responde com DEBUG=True).
    path('erros/<int:codigo>/', views.ver_erro, name='ver_erro'),
]
