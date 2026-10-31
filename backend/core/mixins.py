from django.contrib.auth.mixins import UserPassesTestMixin
from django.utils.dateparse import parse_date


class PerfilRequiredMixin(UserPassesTestMixin):
    """Libera a view apenas para usuários com um dos perfis em `perfis_permitidos`."""

    perfis_permitidos = ()

    def test_func(self):
        usuario = self.request.user
        return usuario.is_authenticated and usuario.perfil in self.perfis_permitidos


class AdministradorRequiredMixin(PerfilRequiredMixin):
    perfis_permitidos = ('administrador',)


class AtendenteRequiredMixin(PerfilRequiredMixin):
    perfis_permitidos = ('administrador', 'atendente')


class BuscaObrigatoriaMixin:
    """Listas que não mostram nada ao abrir: os resultados só aparecem depois de uma busca
    (botão "Buscar", que envia `buscar=1`, ou qualquer filtro preenchido). Buscar sem filtros lista tudo.
    A view filtra em `filtrar(qs)`; o template recebe `buscou`, `f` (valores dos filtros) e
    `filtros_querystring` (para a paginação não perder a busca).

    Ordenação opcional: `ordenacoes` = {chave: (rótulo, campos do order_by)} e `ordem_padrao`; o
    parâmetro `ordem` escolhe (não conta como busca). O template recebe `ordenacoes` e `ordem_selecionada`."""

    ordenacoes = {}
    ordem_padrao = ''

    def buscou(self):
        return any(chave not in ('page', 'ordem') and valor.strip() for chave, valor in self.request.GET.items())

    def get_ordem(self):
        ordem = self.filtro('ordem')
        return ordem if ordem in self.ordenacoes else self.ordem_padrao

    def filtro(self, nome):
        return self.request.GET.get(nome, '').strip()

    def filtro_id(self, nome):
        """Valor de um filtro que é uma chave primária (ignora o que não for número)."""
        valor = self.filtro(nome)
        return int(valor) if valor.isdigit() else None

    def filtro_data(self, nome):
        """Data de um filtro (AAAA-MM-DD, como envia o <input type="date">); None se vazia ou inválida."""
        try:
            return parse_date(self.filtro(nome))
        except ValueError:
            return None

    def filtrar(self, qs):
        return qs

    def get_queryset(self):
        qs = super().get_queryset()
        if not self.buscou():
            return qs.none()
        qs = self.filtrar(qs)
        if self.ordenacoes:
            qs = qs.order_by(*self.ordenacoes[self.get_ordem()][1])
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['buscou'] = self.buscou()
        context['ordenacoes'] = [(chave, rotulo) for chave, (rotulo, _) in self.ordenacoes.items()]
        context['ordem_selecionada'] = self.get_ordem()
        context['f'] = {chave: valor.strip() for chave, valor in self.request.GET.items()}
        parametros = self.request.GET.copy()
        parametros.pop('page', None)
        context['filtros_querystring'] = parametros.urlencode()
        return context
