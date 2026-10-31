"""Encerramento: o técnico fecha; o solicitante pode reabrir em até Chamado.DIAS_REABERTURA dias
(volta para em andamento) e avaliar o atendimento depois de cada fechamento."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chamados.models import Chamado, EventoChamado, ProcedimentoEntry
from tests.fabricas import cliente, criar_chamado, criar_solicitante, criar_tecnico, mensagens


class FechamentoEReaberturaTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.chamado = criar_chamado()
        self.solicitante = self.chamado.solicitante
        cliente(self.tecnico).post(reverse('chamados:pegar', args=[self.chamado.pk]))

    def fechar(self):
        return cliente(self.tecnico).post(reverse('chamados:fechar', args=[self.chamado.pk]), {'notas': 'Problema resolvido.'}, follow=True)

    def reabrir(self, texto='Continua sem acesso.', usuario=None):
        return cliente(usuario or self.solicitante).post(
            reverse('chamados:reabrir', args=[self.chamado.pk]), {'texto': texto}, follow=True
        )

    def avaliar(self, nota, comentario=''):
        return cliente(self.solicitante).post(
            reverse('chamados:avaliar', args=[self.chamado.pk]), {'avaliacao': nota, 'comentario': comentario},
            follow=True,
        )

    def test_tecnico_fecha_chamado(self):
        self.fechar()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertIsNotNone(self.chamado.fechado_em)
        self.assertTrue(self.chamado.fechado_no_prazo)
        self.assertTrue(self.chamado.sla_pausado)
        self.assertIsNotNone(self.chamado.primeira_resposta_em)  # fechar também é responder
        self.assertTrue(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.FECHADO).exists())

    def test_encerrar_exige_anotacoes_publicas(self):
        resposta = cliente(self.tecnico).post(
            reverse('chamados:fechar', args=[self.chamado.pk]), {'notas': '   '}, follow=True
        )
        self.chamado.refresh_from_db()
        self.assertNotEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertTrue(any('anotações de encerramento' in m for m in mensagens(resposta)))

        cliente(self.tecnico).post(
            reverse('chamados:fechar', args=[self.chamado.pk]), {'notas': 'Driver reinstalado.'}
        )
        notas = self.chamado.procedimentos.get(tipo=ProcedimentoEntry.Tipo.ENCERRAMENTO)
        self.assertEqual((notas.texto, notas.autor), ('Driver reinstalado.', self.tecnico))
        # Públicas: o solicitante vê na linha do tempo.
        detalhe = cliente(self.solicitante).get(reverse('chamados:detail', args=[self.chamado.pk]))
        self.assertContains(detalhe, 'Driver reinstalado.')
        self.assertContains(detalhe, 'Anotações de encerramento')

    def test_fechar_fora_do_prazo_registra_sla_estourado(self):
        Chamado.objects.filter(pk=self.chamado.pk).update(prazo_sla=timezone.now() - timedelta(hours=1))
        self.fechar()

        self.chamado.refresh_from_db()
        self.assertFalse(self.chamado.fechado_no_prazo)

    def test_solicitante_reabre_e_tecnico_fecha_de_novo(self):
        self.fechar()
        self.reabrir()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.EM_ANDAMENTO)
        self.assertIsNone(self.chamado.fechado_em)
        self.assertFalse(self.chamado.sla_pausado)
        self.assertEqual(self.chamado.reaberturas, 1)
        self.assertIsNotNone(self.chamado.resposta_solicitante_em)  # avisa o técnico
        self.assertTrue(self.chamado.procedimentos.filter(
            tipo=ProcedimentoEntry.Tipo.RESPOSTA, texto__contains='Continua sem acesso.'
        ).exists())

        self.fechar()
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)

    def test_nao_reabre_depois_do_prazo(self):
        self.fechar()
        vencido = timezone.now() - timedelta(days=Chamado.DIAS_REABERTURA, minutes=1)
        Chamado.objects.filter(pk=self.chamado.pk).update(fechado_em=vencido)

        self.reabrir()

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertEqual(self.chamado.reaberturas, 0)

    def test_reabrir_exige_motivo(self):
        self.fechar()
        self.reabrir(texto='')

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)

    def test_outro_solicitante_nao_reabre(self):
        self.fechar()
        resposta = cliente(criar_solicitante()).post(
            reverse('chamados:reabrir', args=[self.chamado.pk]), {'texto': 'x'}
        )

        self.assertEqual(resposta.status_code, 404)

    def test_avaliacao_apos_fechar_e_descartada_ao_reabrir(self):
        self.fechar()
        self.avaliar('2')
        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.avaliacao, 2)

        self.reabrir()
        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.avaliacao)

    def test_avaliacao_uma_vez_por_fechamento_e_comentario_vai_para_linha_do_tempo(self):
        self.fechar()
        self.avaliar('5', comentario='Muito atencioso')
        resposta = self.avaliar('1')

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.avaliacao, 5)
        self.assertIn('Este chamado não pode ser avaliado.', mensagens(resposta))
        self.assertTrue(self.chamado.procedimentos.filter(texto__contains='Muito atencioso').exists())
        self.assertTrue(self.chamado.eventos.filter(tipo=EventoChamado.Tipo.AVALIADO).exists())

    def test_avaliacao_invalida_e_recusada(self):
        self.fechar()
        resposta = self.avaliar('9')

        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.avaliacao)
        self.assertIn('Escolha de 1 a 5 estrelas para avaliar.', mensagens(resposta))

    def test_chamado_aberto_nao_pode_ser_avaliado(self):
        self.avaliar('5')

        self.chamado.refresh_from_db()
        self.assertIsNone(self.chamado.avaliacao)

    def test_chamado_fechado_e_somente_leitura_para_a_equipe(self):
        self.fechar()
        resposta = cliente(self.tecnico).post(
            reverse('chamados:aguardar_solicitante', args=[self.chamado.pk]), {'texto': 'Qual o ramal?'},
            follow=True,
        )

        self.chamado.refresh_from_db()
        self.assertEqual(self.chamado.status, Chamado.Status.FECHADO)
        self.assertIn('Este chamado já foi fechado e não pode mais ser alterado.', mensagens(resposta))


class AvisoDeChamadoFechadoTests(TestCase):
    """Ao fechar, o solicitante é avisado (menu, aviso e pop-up de "Meus chamados") para avaliar o
    atendimento ou reabrir; o aviso some ao avaliar, ao reabrir ou quando acaba o prazo de reabertura."""

    def setUp(self):
        self.tecnico = criar_tecnico()
        self.chamado = criar_chamado()
        self.solicitante = self.chamado.solicitante
        cliente(self.tecnico).post(reverse('chamados:pegar', args=[self.chamado.pk]))
        cliente(self.tecnico).post(reverse('chamados:fechar', args=[self.chamado.pk]), {'notas': 'Problema resolvido.'})

    def meus_chamados(self):
        return cliente(self.solicitante).get(reverse('chamados:list'))

    def test_solicitante_e_avisado_depois_do_fechamento(self):
        from core.templatetags.chamado_extras import chamados_aguardando_resposta

        resposta = self.meus_chamados()

        self.assertEqual([c.pk for c in resposta.context['fechados_para_avaliar']], [self.chamado.pk])
        self.assertContains(resposta, f'Avaliar {self.chamado.codigo}')
        self.assertEqual(chamados_aguardando_resposta(self.solicitante), 1)

    def test_aviso_some_ao_avaliar(self):
        cliente(self.solicitante).post(reverse('chamados:avaliar', args=[self.chamado.pk]), {'avaliacao': '5'})

        self.assertEqual(self.meus_chamados().context['fechados_para_avaliar'], [])

    def test_aviso_some_ao_reabrir(self):
        cliente(self.solicitante).post(reverse('chamados:reabrir', args=[self.chamado.pk]), {'texto': 'Voltou o erro.'})

        self.assertEqual(self.meus_chamados().context['fechados_para_avaliar'], [])

    def test_aviso_some_depois_do_prazo_de_reabertura(self):
        Chamado.objects.filter(pk=self.chamado.pk).update(
            fechado_em=timezone.now() - timedelta(days=Chamado.DIAS_REABERTURA, minutes=1)
        )

        self.assertEqual(self.meus_chamados().context['fechados_para_avaliar'], [])
