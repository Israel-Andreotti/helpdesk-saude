from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.shortcuts import redirect, render
from django.template.loader import get_template

from usuarios.views import perfil_redirect_url


@login_required
def inicio(request):
    """A raiz do site leva à tela inicial do perfil (a mesma do login)."""
    return redirect(perfil_redirect_url(request.user))


def falha_csrf(request, reason=''):
    """Página de CSRF recusado (settings.CSRF_FAILURE_VIEW). A view padrão do Django renderiza sem request,
    o que quebraria o base.html; aqui a página tem menu e usuário como as outras de erro."""
    return render(request, '403_csrf.html', status=403)


# Páginas que a pré-visualização sabe mostrar. 400 e 500 são renderizadas sem contexto, como o Django faz.
PAGINAS_DE_ERRO = {
    400: ('400.html', False), 403: ('403.html', True), 404: ('404.html', True),
    405: ('405.html', True), 419: ('403_csrf.html', True), 500: ('500.html', False),
}


def ver_erro(request, codigo):
    """Só com DEBUG=True: mostra a página de erro como ela aparece em produção (em DEBUG o Django mostra a
    página técnica no lugar). 419 = falha de CSRF (que de verdade responde 403)."""
    if not settings.DEBUG or codigo not in PAGINAS_DE_ERRO:
        raise Http404
    template, com_contexto = PAGINAS_DE_ERRO[codigo]
    status = 403 if codigo == 419 else codigo
    if com_contexto:
        return render(request, template, status=status)
    from django.http import HttpResponse

    return HttpResponse(get_template(template).render(), status=status)
