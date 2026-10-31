"""Pedido de novo usuário via chamado: só gestores (VIP) abrem, informando os dados do funcionário;
a TI cria o usuário a partir do chamado e o gestor recebe um link de ativação de uso único, com o
qual o funcionário cria a própria senha (ninguém vê senha)."""

from datetime import timedelta

from django.conf import settings
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chamados.models import Chamado, EventoChamado, SolicitacaoUsuario
from core.templatetags.chamado_extras import chamados_aguardando_resposta
from tests.fabricas import (
    cliente, criar_setor, criar_solicitante, criar_subcategoria, criar_tecnico, mensagens,
)
from usuarios.models import Usuario
from usuarios.views import sugerir_username

SENHA_NOVA = 'Hosp1tal-Seguro'


class PedidoDeNovoUsuarioTests(TestCase):
    def setUp(self):
        self.setor = criar_setor()
        self.gestor = criar_solicitante(setor=self.setor, vip=True)
        self.tecnico = criar_tecnico()
        self.subcategoria = criar_subcategoria(tipo='requisicao')
        self.subcategoria.pedido_usuario = 'criacao'
        self.subcategoria.save()

    def abrir(self, usuario=None, **dados):
        campos = {
            'categoria': self.subcategoria.categoria_id, 'subcategoria': self.subcategoria.pk, 'setor': self.setor.pk,
            'descricao': '', 'novo_first_name': 'João', 'novo_last_name': 'da Silva Ávila',
            'novo_email': 'joao@hospital.test', 'novo_telefone': '(11)98888-7777',
        }
        campos.update(dados)
        return cliente(usuario or self.gestor).post(reverse('chamados:create'), campos)

    def abrir_e_criar_usuario(self):
        self.abrir()
        chamado = Chamado.objects.get(solicitacao_usuario__email='joao@hospital.test')
        tecnico = cliente(self.tecnico)
        url = reverse('usuarios:cadastrar') + f'?chamado={chamado.pk}'
        inicial = tecnico.get(url).context['form'].initial
        dados = {campo: inicial.get(campo, '') for campo in
                 ('username', 'first_name', 'last_name', 'email', 'telefone', 'perfil', 'setor')}
        resposta = tecnico.post(url, dados)
        return chamado, resposta

    # ---- abertura

    def test_gestor_abre_com_os_dados_e_o_funcionario_fica_no_setor_do_gestor(self):
        self.abrir(setor=criar_setor().pk)  # mesmo abrindo o chamado em outro setor

        solicitacao = SolicitacaoUsuario.objects.get()
        self.assertEqual((solicitacao.nome_completo, solicitacao.telefone), ('João da Silva Ávila', '11988887777'))
        self.assertEqual(solicitacao.setor, self.setor)
        self.assertIn('Criação de usuário para João', solicitacao.chamado.descricao)

    def test_quem_nao_e_gestor_nao_ve_nem_abre_o_pedido(self):
        comum = criar_solicitante(setor=self.setor)

        form = cliente(comum).get(reverse('chamados:create')).context['form']
        self.assertNotIn(self.subcategoria, form.fields['subcategoria'].queryset)
        self.abrir(usuario=comum)
        self.assertFalse(SolicitacaoUsuario.objects.exists())

    def test_dados_do_funcionario_sao_obrigatorios(self):
        resposta = self.abrir(novo_email='')

        self.assertFalse(SolicitacaoUsuario.objects.exists())
        self.assertIn('novo_email', resposta.context['form'].errors)

    # ---- criação pela TI

    def test_tecnico_cria_usuario_pelo_chamado_sem_senha_e_com_link(self):
        chamado, resposta = self.abrir_e_criar_usuario()

        self.assertRedirects(resposta, reverse('chamados:detail', args=[chamado.pk]))
        solicitacao = SolicitacaoUsuario.objects.get(chamado=chamado)
        usuario = solicitacao.usuario
        self.assertEqual(usuario.username, 'joao.avila')
        self.assertEqual(usuario.setor, self.setor)
        self.assertFalse(usuario.has_usable_password())  # não entra até ativar
        self.assertTrue(solicitacao.link_ativacao.startswith('/usuarios/ativar/'))
        self.assertTrue(chamado.eventos.filter(tipo=EventoChamado.Tipo.USUARIO_CRIADO).exists())
        chamado.refresh_from_db()
        self.assertIsNotNone(chamado.primeira_resposta_em)

    def test_gestor_ve_o_link_no_chamado_e_e_avisado(self):
        chamado, _ = self.abrir_e_criar_usuario()

        resposta = cliente(self.gestor).get(reverse('chamados:detail', args=[chamado.pk]))
        self.assertContains(resposta, 'id="linkAtivacao"')
        self.assertEqual(len(cliente(self.gestor).get(reverse('chamados:list')).context['acessos_prontos']), 1)
        self.assertEqual(chamados_aguardando_resposta(self.gestor), 1)

    def test_nao_cria_duas_vezes_pelo_mesmo_chamado(self):
        chamado, _ = self.abrir_e_criar_usuario()

        resposta = cliente(self.tecnico).get(reverse('usuarios:cadastrar') + f'?chamado={chamado.pk}', follow=True)
        self.assertTrue(any('já foi criado' in m for m in mensagens(resposta)))

    # ---- ativação

    def test_funcionario_ativa_pelo_link_e_o_link_nao_vale_de_novo(self):
        chamado, _ = self.abrir_e_criar_usuario()
        link = SolicitacaoUsuario.objects.get(chamado=chamado).link_ativacao
        anonimo = cliente()

        formulario = anonimo.get(link, follow=True)
        self.assertTrue(formulario.context['validlink'])
        anonimo.post(formulario.redirect_chain[-1][0], {'new_password1': SENHA_NOVA, 'new_password2': SENHA_NOVA})

        usuario = Usuario.objects.get(username='joao.avila')
        self.assertTrue(usuario.check_password(SENHA_NOVA))
        solicitacao = SolicitacaoUsuario.objects.get(chamado=chamado)
        self.assertIsNotNone(solicitacao.ativado_em)
        self.assertEqual(solicitacao.link_ativacao, '')
        self.assertTrue(chamado.eventos.filter(tipo=EventoChamado.Tipo.CONTA_ATIVADA, autor=usuario).exists())
        self.assertFalse(cliente().get(link, follow=True).context['validlink'])
        self.assertEqual(chamados_aguardando_resposta(self.gestor), 0)

    def test_novo_link_invalida_o_anterior(self):
        chamado, _ = self.abrir_e_criar_usuario()
        antigo = SolicitacaoUsuario.objects.get(chamado=chamado).link_ativacao

        cliente(self.tecnico).post(reverse('chamados:novo_link_ativacao', args=[chamado.pk]))

        novo = SolicitacaoUsuario.objects.get(chamado=chamado).link_ativacao
        self.assertNotEqual(novo, antigo)
        self.assertFalse(cliente().get(antigo, follow=True).context['validlink'])
        self.assertTrue(cliente().get(novo, follow=True).context['validlink'])

    def test_link_expirado_some_do_chamado(self):
        chamado, _ = self.abrir_e_criar_usuario()
        SolicitacaoUsuario.objects.filter(chamado=chamado).update(
            link_gerado_em=timezone.now() - timedelta(seconds=settings.PASSWORD_RESET_TIMEOUT + 60)
        )

        resposta = cliente(self.gestor).get(reverse('chamados:detail', args=[chamado.pk]))
        self.assertNotContains(resposta, 'id="linkAtivacao"')
        self.assertContains(resposta, 'expirou')
        self.assertEqual(chamados_aguardando_resposta(self.gestor), 0)


class PedidoDeExclusaoEAlteracaoTests(TestCase):
    """Exclusão: só gestores, com nome completo e matrícula de um usuário ativo. Alteração: qualquer um."""

    def setUp(self):
        self.setor = criar_setor()
        self.gestor = criar_solicitante(setor=self.setor, vip=True)
        self.comum = criar_solicitante(setor=self.setor)
        self.saindo = criar_solicitante(setor=self.setor)
        self.exclusao = criar_subcategoria(tipo='requisicao')
        self.exclusao.pedido_usuario = 'exclusao'
        self.exclusao.save()
        self.alteracao = criar_subcategoria(tipo='requisicao')

    def abrir(self, usuario, subcategoria, **dados):
        campos = {'categoria': subcategoria.categoria_id, 'subcategoria': subcategoria.pk,
                  'setor': self.setor.pk, 'descricao': ''}
        campos.update(dados)
        return cliente(usuario).post(reverse('chamados:create'), campos)

    def test_gestor_pede_exclusao_com_nome_e_matricula(self):
        self.abrir(self.gestor, self.exclusao, excluir_nome='  Maria   Souza ',
                   excluir_matricula=self.saindo.matricula, descricao='Saída em 05/11.')

        chamado = Chamado.objects.get(subcategoria=self.exclusao)
        self.assertTrue(chamado.descricao.startswith(
            f'Exclusão de usuário: Maria Souza (matrícula {self.saindo.matricula}).'))
        self.assertIn('Saída em 05/11.', chamado.descricao)
        self.assertFalse(SolicitacaoUsuario.objects.exists())

    def test_exclusao_exige_nome_e_matricula_de_usuario_ativo(self):
        resposta = self.abrir(self.gestor, self.exclusao, excluir_nome='', excluir_matricula='999999')

        erros = resposta.context['form'].errors
        self.assertIn('excluir_nome', erros)
        self.assertIn('Nenhum usuário ativo', str(erros['excluir_matricula']))
        self.assertFalse(Chamado.objects.filter(subcategoria=self.exclusao).exists())

    def test_quem_nao_e_gestor_nao_pede_exclusao_mas_pede_alteracao(self):
        form = cliente(self.comum).get(reverse('chamados:create')).context['form']
        self.assertNotIn(self.exclusao, form.fields['subcategoria'].queryset)
        self.assertIn(self.alteracao, form.fields['subcategoria'].queryset)

        self.abrir(self.comum, self.exclusao, excluir_nome='Maria Souza', excluir_matricula=self.saindo.matricula)
        self.abrir(self.comum, self.alteracao, descricao='Trocar meu sobrenome no cadastro.')
        self.assertFalse(Chamado.objects.filter(subcategoria=self.exclusao).exists())
        self.assertTrue(Chamado.objects.filter(subcategoria=self.alteracao, solicitante=self.comum).exists())

    def test_alteracao_continua_exigindo_descricao(self):
        resposta = self.abrir(self.comum, self.alteracao)
        self.assertIn('descricao', resposta.context['form'].errors)


class SugestaoDeLoginTests(TestCase):
    def test_sem_acentos_primeiro_e_ultimo_nome_e_unico(self):
        self.assertEqual(sugerir_username('José Carlos', 'de Araújo'), 'jose.araujo')
        criar_solicitante(username='jose.araujo')
        self.assertEqual(sugerir_username('José', 'Araújo'), 'jose.araujo2')
