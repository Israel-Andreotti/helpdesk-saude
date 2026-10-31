"""Link de ativação de conta: o funcionário novo cria a própria senha por um link de uso único,
sem ninguém (TI ou gestor) conhecer a senha. Usa o gerador de tokens de redefinição de senha do
Django: o token vale settings.PASSWORD_RESET_TIMEOUT e deixa de valer quando a senha muda — ao
ser usado, ou ao gerar um link novo (que troca a senha "inutilizável" e invalida os anteriores)."""

from django.contrib.auth.tokens import default_token_generator
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


def gerar_link_ativacao(usuario):
    """Deixa o usuário sem senha utilizável (não entra até ativar) e devolve o caminho do link."""
    usuario.set_unusable_password()
    usuario.deve_trocar_senha = False
    usuario.save(update_fields=['password', 'deve_trocar_senha'])
    uid = urlsafe_base64_encode(force_bytes(usuario.pk))
    token = default_token_generator.make_token(usuario)
    return reverse('usuarios:ativar_conta', kwargs={'uidb64': uid, 'token': token})
