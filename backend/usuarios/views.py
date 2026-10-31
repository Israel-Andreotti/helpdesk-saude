import re
import unicodedata

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth import views as auth_views
from django.contrib.auth.mixins import LoginRequiredMixin
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.utils.crypto import get_random_string
from django.views.generic import CreateView, ListView, UpdateView, View

from core.mixins import AdministradorRequiredMixin, AtendenteRequiredMixin, BuscaObrigatoriaMixin

from .ativacao import gerar_link_ativacao
from .forms import AtivarContaForm, LoginForm, SetorForm, TrocarSenhaForm, UsuarioCadastroForm, UsuarioEditarForm
from .models import Setor, Usuario

SENHA_TEMPORARIA_CHARS = 'ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789'


def gerar_senha_temporaria():
    return get_random_string(10, allowed_chars=SENHA_TEMPORARIA_CHARS)


def sugerir_username(nome, sobrenome):
    """Sugestão de login "nome.sobrenome" (sem acentos, minúsculo, último sobrenome), única no sistema."""
    def limpar(texto):
        texto = unicodedata.normalize('NFKD', texto or '').encode('ascii', 'ignore').decode().lower()
        return re.sub(r'[^a-z0-9]', '', texto)

    primeiro = limpar((nome or '').split()[0]) if (nome or '').split() else ''
    ultimo = limpar((sobrenome or '').split()[-1]) if (sobrenome or '').split() else ''
    base = '.'.join(p for p in (primeiro, ultimo) if p) or 'usuario'
    sugestao, n = base, 2
    while Usuario.objects.filter(username__iexact=sugestao).exists():
        sugestao, n = f'{base}{n}', n + 1
    return sugestao


def perfil_redirect_url(usuario):
    if usuario.perfil in (Usuario.Perfil.ADMINISTRADOR, Usuario.Perfil.ATENDENTE):
        return reverse_lazy('chamados:list')
    return reverse_lazy('chamados:create')


class LoginView(auth_views.LoginView):
    template_name = 'usuarios/login.html'
    authentication_form = LoginForm

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        if settings.LOGIN_RAPIDO:
            context['usuarios_login_rapido'] = Usuario.objects.filter(is_active=True).select_related('setor').order_by(
                'perfil', 'first_name', 'username'
            )
        return context

    def get_success_url(self):
        redirect_url = self.get_redirect_url()
        if redirect_url:
            return redirect_url
        return perfil_redirect_url(self.request.user)


class LoginRapidoView(View):
    """Entra como qualquer usuário ativo com um clique, sem senha. Só existe com LOGIN_RAPIDO
    ligado (testes locais, DEBUG=True); fora disso responde 404."""

    def post(self, request, pk):
        if not settings.LOGIN_RAPIDO:
            raise Http404
        usuario = get_object_or_404(Usuario, pk=pk, is_active=True)
        login(request, usuario, backend='django.contrib.auth.backends.ModelBackend')
        return redirect(perfil_redirect_url(usuario))


class LogoutView(auth_views.LogoutView):
    pass


class TrocarSenhaView(LoginRequiredMixin, auth_views.PasswordChangeView):
    template_name = 'usuarios/trocar_senha.html'
    form_class = TrocarSenhaForm

    def form_valid(self, form):
        response = super().form_valid(form)
        self.request.user.deve_trocar_senha = False
        self.request.user.save(update_fields=['deve_trocar_senha'])
        return response

    def get_success_url(self):
        return perfil_redirect_url(self.request.user)


class UsuarioCadastroView(AtendenteRequiredMixin, CreateView):
    """Cadastro de usuário. Avulso: senha temporária mostrada uma vez (troca obrigatória no 1º login).
    A partir de um chamado de pedido de novo usuário (?chamado=<pk>): já vem preenchido com os dados
    informados pelo gestor e, em vez de senha, gera um link de ativação que o gestor vê no chamado."""

    model = Usuario
    form_class = UsuarioCadastroForm
    template_name = 'usuarios/usuario_form.html'

    def dispatch(self, request, *args, **kwargs):
        self.solicitacao = None
        chamado_pk = request.GET.get('chamado', '')
        if chamado_pk and request.user.is_authenticated and not request.user.is_solicitante():
            from chamados.models import SolicitacaoUsuario

            self.solicitacao = (
                SolicitacaoUsuario.objects.select_related('chamado', 'setor').filter(chamado_id=chamado_pk).first()
                if chamado_pk.isdigit() else None
            )
            motivo = None
            if not self.solicitacao:
                motivo = 'Este chamado não é um pedido de novo usuário.'
            elif self.solicitacao.usuario_id:
                motivo = 'O usuário deste pedido já foi criado.'
            elif self.solicitacao.chamado.encerrado:
                motivo = 'Este chamado já foi fechado.'
            if motivo:
                messages.error(request, motivo)
                if self.solicitacao:
                    return redirect('chamados:detail', pk=self.solicitacao.chamado_id)
                return redirect('usuarios:list')
        return super().dispatch(request, *args, **kwargs)

    def get_initial(self):
        initial = super().get_initial()
        if self.solicitacao:
            s = self.solicitacao
            initial.update({
                'first_name': s.first_name, 'last_name': s.last_name, 'email': s.email, 'telefone': s.telefone,
                'setor': s.setor_id, 'perfil': Usuario.Perfil.SOLICITANTE,
                'username': sugerir_username(s.first_name, s.last_name),
            })
        return initial

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['solicitacao'] = self.solicitacao
        return context

    @transaction.atomic
    def _criar_pelo_chamado(self, form):
        from chamados.models import EventoChamado

        usuario = form.save()
        solicitacao = self.solicitacao
        solicitacao.usuario = usuario
        solicitacao.link_ativacao = gerar_link_ativacao(usuario)
        solicitacao.link_gerado_em = timezone.now()
        solicitacao.save(update_fields=['usuario', 'link_ativacao', 'link_gerado_em'])
        chamado = solicitacao.chamado
        chamado.registrar_primeira_resposta()
        chamado.save(update_fields=['primeira_resposta_em', 'atualizado_em'])
        chamado.registrar_evento(
            EventoChamado.Tipo.USUARIO_CRIADO, self.request.user,
            f'Criou o usuário "{usuario.username}" (matrícula {usuario.matricula}) e gerou o link de ativação.',
        )
        return chamado

    def form_valid(self, form):
        if self.solicitacao:
            chamado = self._criar_pelo_chamado(form)
            messages.success(
                self.request,
                'Usuário criado. O link de ativação está no chamado para o gestor repassar ao funcionário.',
            )
            return redirect('chamados:detail', pk=chamado.pk)
        self.object = form.save(commit=False)
        senha_temporaria = gerar_senha_temporaria()
        self.object.set_password(senha_temporaria)
        self.object.deve_trocar_senha = True
        self.object.save()
        return render(self.request, 'usuarios/usuario_resumo.html', {
            'usuario': self.object,
            'senha_temporaria': senha_temporaria,
        })


class UsuarioEditarView(AtendenteRequiredMixin, UpdateView):
    model = Usuario
    form_class = UsuarioEditarForm
    template_name = 'usuarios/usuario_editar.html'
    success_url = reverse_lazy('usuarios:list')

    def dispatch(self, request, *args, **kwargs):
        usuario = get_object_or_404(Usuario, pk=kwargs['pk'])
        if usuario.super_admin:
            messages.error(request, 'Contas de superadministrador não podem ser editadas por aqui.')
            return redirect('usuarios:list')
        return super().dispatch(request, *args, **kwargs)

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Cadastro de {self.object} atualizado.')
        return response


class UsuarioListView(AtendenteRequiredMixin, BuscaObrigatoriaMixin, ListView):
    template_name = 'usuarios/usuario_list.html'
    context_object_name = 'usuarios'
    paginate_by = 25
    queryset = Usuario.objects.filter(super_admin=False).select_related('setor')
    NOME = ('first_name', 'last_name', 'username')
    ordenacoes = {
        'nome': ('Nome', NOME),
        'matricula': ('Matrícula', ('matricula',)),
        'perfil': ('Perfil', ('perfil',) + NOME),
        'setor': ('Setor', (F('setor__nome').asc(nulls_last=True),) + NOME),
        'recentes': ('Cadastro mais recente', ('-date_joined',)),
    }
    ordem_padrao = 'nome'

    def filtrar(self, qs):
        termo = self.filtro('q')
        if termo:
            qs = qs.filter(
                Q(username__icontains=termo)
                | Q(first_name__icontains=termo)
                | Q(last_name__icontains=termo)
                | Q(matricula__icontains=termo)
                | Q(email__icontains=termo)
            )
        if self.filtro('perfil') in Usuario.Perfil.values:
            qs = qs.filter(perfil=self.filtro('perfil'))
        status = self.filtro('status')
        if status in ('ativo', 'inativo'):
            qs = qs.filter(is_active=status == 'ativo')
        setor = self.filtro_id('setor')
        if setor:
            qs = qs.filter(setor_id=setor)
        vip = self.filtro('vip')
        if vip in ('sim', 'nao'):
            qs = qs.filter(vip=vip == 'sim')
        return qs

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context['perfil_choices'] = Usuario.Perfil.choices
        context['setores'] = Setor.objects.order_by('nome')
        return context


class UsuarioToggleAtivoView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        if usuario.super_admin:
            messages.error(request, 'Contas de superadministrador não podem ser desativadas.')
            return redirect('usuarios:list')
        if usuario == request.user:
            messages.error(request, 'Você não pode desativar a própria conta.')
            return redirect('usuarios:editar', pk=usuario.pk)
        usuario.is_active = not usuario.is_active
        usuario.save(update_fields=['is_active'])
        if usuario.is_active:
            messages.success(request, f'{usuario} reativado.')
        else:
            messages.success(request, f'{usuario} desativado.')
        return redirect('usuarios:editar', pk=usuario.pk)


class UsuarioResetarSenhaView(AtendenteRequiredMixin, View):
    def post(self, request, pk):
        usuario = get_object_or_404(Usuario, pk=pk)
        if usuario.super_admin:
            messages.error(request, 'A senha de uma conta de superadministrador não pode ser resetada por aqui.')
            return redirect('usuarios:list')
        senha_temporaria = gerar_senha_temporaria()
        usuario.set_password(senha_temporaria)
        usuario.deve_trocar_senha = True
        usuario.save()
        return render(request, 'usuarios/usuario_resumo.html', {
            'usuario': usuario,
            'senha_temporaria': senha_temporaria,
            'reset_senha': True,
        })


class SetorListView(AdministradorRequiredMixin, ListView):
    model = Setor
    template_name = 'usuarios/setor_list.html'
    context_object_name = 'setores'

    def get_queryset(self):
        return Setor.objects.order_by('nome')


class SetorCriticoView(AdministradorRequiredMixin, View):
    """Marca/desmarca um setor como crítico (afeta a prioridade dos chamados abertos dali em diante)."""

    def post(self, request, pk):
        setor = get_object_or_404(Setor, pk=pk)
        setor.critico = not setor.critico
        setor.save(update_fields=['critico'])
        if setor.critico:
            messages.success(request, f'"{setor}" marcado como setor crítico: novos chamados dele sobem um nível de prioridade.')
        else:
            messages.success(request, f'"{setor}" deixou de ser setor crítico.')
        return redirect('usuarios:setores')


class SetorCadastroView(AdministradorRequiredMixin, CreateView):
    model = Setor
    form_class = SetorForm
    template_name = 'usuarios/setor_form.html'
    success_url = reverse_lazy('usuarios:setores')

    def form_valid(self, form):
        response = super().form_valid(form)
        messages.success(self.request, f'Setor "{self.object}" cadastrado.')
        return response


class AtivarContaView(auth_views.PasswordResetConfirmView):
    """Link de ativação (pedido de novo usuário): o funcionário cria a própria senha. Uso único e com
    prazo (settings.PASSWORD_RESET_TIMEOUT); depois de usado, o link deixa de valer."""

    template_name = 'usuarios/ativar_conta.html'
    form_class = AtivarContaForm
    success_url = reverse_lazy('usuarios:login')
    post_reset_login = False

    @transaction.atomic
    def form_valid(self, form):
        from chamados.models import EventoChamado, SolicitacaoUsuario

        response = super().form_valid(form)
        usuario = form.user
        solicitacao = SolicitacaoUsuario.objects.select_related('chamado').filter(
            usuario=usuario, ativado_em__isnull=True
        ).first()
        if solicitacao:
            solicitacao.ativado_em = timezone.now()
            solicitacao.link_ativacao = ''
            solicitacao.save(update_fields=['ativado_em', 'link_ativacao'])
            solicitacao.chamado.registrar_evento(
                EventoChamado.Tipo.CONTA_ATIVADA, usuario, 'Ativou a conta e criou a própria senha.'
            )
        messages.success(self.request, f'Conta ativada! Entre com o usuário "{usuario.username}" e a senha que você criou.')
        return response
