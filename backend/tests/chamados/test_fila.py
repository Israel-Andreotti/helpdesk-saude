"""Fila de chamados (integração): o que aparece, filtros, ordenações, ordem lembrada na sessão e a
"versão" usada para a fila se atualizar sozinha."""

from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from chamados.models import Chamado
from chamados.views import COLUNAS_FILA, versao_fila
from tests.fabricas import cliente, criar_chamado, criar_setor, criar_solicitante, criar_subcategoria, criar_tecnico

URL = reverse('chamados:list')


class FilaTests(TestCase):
    def setUp(self):
        Chamado.objects.all().delete()  # o banco de teste vem com chamados de demonstração
        self.tecnico = criar_tecnico()
        agora = timezone.now()
        self.critico = criar_chamado(subcategoria=criar_subcategoria(prioridade='critica', tipo='incidente'))
        self.baixa = criar_chamado(subcategoria=criar_subcategoria(prioridade='baixa', tipo='requisicao'))
        self.media = criar_chamado(subcategoria=criar_subcategoria(prioridade='media', tipo='incidente'))
        # Prazos e aberturas controlados: baixa vence primeiro, depois crítico, depois média.
        Chamado.objects.filter(pk=self.baixa.pk).update(prazo_sla=agora + timedelta(hours=1), criado_em=agora - timedelta(hours=3))
        Chamado.objects.filter(pk=self.critico.pk).update(prazo_sla=agora + timedelta(hours=2), criado_em=agora - timedelta(hours=2))
        Chamado.objects.filter(pk=self.media.pk).update(prazo_sla=agora + timedelta(hours=20), criado_em=agora - timedelta(hours=1))

    def fila(self, usuario=None, **params):
        resposta = cliente(usuario or self.tecnico).get(URL, params)
        return [c.pk for c in resposta.context['chamados']], resposta

    def test_fila_da_equipe_nao_mostra_fechados(self):
        self.media.fechar()
        self.media.save()

        pks, _ = self.fila()
        self.assertNotIn(self.media.pk, pks)

    def test_solicitante_ve_os_proprios_fechados(self):
        self.media.fechar()
        self.media.save()

        # Ficam na aba "Fechados" (a aba "Em aberto" e o filtro de status não incluem fechados).
        pks, _ = self.fila(usuario=self.media.solicitante, aba='fechados')
        self.assertEqual(pks, [self.media.pk])
        pks, resposta = self.fila(usuario=self.media.solicitante)
        self.assertNotIn(self.media.pk, pks)
        self.assertNotIn('fechado', [valor for valor, _ in resposta.context['status_choices']])

    def test_filtro_de_status_da_equipe_nao_oferece_fechado(self):
        _, resposta = self.fila()

        self.assertNotIn('fechado', [valor for valor, _ in resposta.context['status_choices']])

    def test_ordem_padrao_e_urgencia_do_sla(self):
        pks, _ = self.fila()

        self.assertEqual(pks, [self.baixa.pk, self.critico.pk, self.media.pk])

    def test_pausado_vai_para_o_fim_na_urgencia(self):
        self.baixa.pausar_sla()
        self.baixa.save()

        pks, _ = self.fila()
        self.assertEqual(pks[-1], self.baixa.pk)

    def test_ordenacoes(self):
        casos = {
            'prioridade': [self.critico.pk, self.media.pk, self.baixa.pk],
            'recentes': [self.media.pk, self.critico.pk, self.baixa.pk],
            'antigos': [self.baixa.pk, self.critico.pk, self.media.pk],
        }
        for ordem, esperado in casos.items():
            with self.subTest(ordem=ordem):
                pks, _ = self.fila(ordem=ordem)
                self.assertEqual(pks, esperado)

    def test_ordenacao_por_sla_consumido(self):
        # baixa: 3h de 4h (75%); crítico: 2h de 4h (50%); média: 1h de 21h (~5%).
        pks, _ = self.fila(ordem='consumido')

        self.assertEqual(pks, [self.baixa.pk, self.critico.pk, self.media.pk])

    def test_ordem_escolhida_fica_guardada_na_sessao(self):
        c = cliente(self.tecnico)
        c.get(URL, {'ordem': 'prioridade'})

        self.assertEqual(c.get(URL).context['ordem_selecionada'], 'prioridade')
        self.assertEqual(c.get(URL, {'ordem': 'invalida'}).context['ordem_selecionada'], 'prioridade')
        self.assertEqual(cliente(criar_tecnico()).get(URL).context['ordem_selecionada'], 'urgencia')

    def test_filtros(self):
        self.critico.atribuir(self.tecnico)
        self.critico.save()
        casos = [
            ({'tipo': 'requisicao'}, {self.baixa.pk}),
            ({'status': 'em_andamento'}, {self.critico.pk}),
            ({'atendente': self.tecnico.pk}, {self.critico.pk}),
            ({'categoria': self.media.categoria_id}, {self.media.pk}),
            ({'q': self.critico.codigo}, {self.critico.pk}),
        ]
        for params, esperado in casos:
            with self.subTest(params=params):
                pks, _ = self.fila(**params)
                self.assertEqual(set(pks), esperado)

    def test_paginacao_mantem_os_filtros(self):
        _, resposta = self.fila(tipo='incidente', ordem='prioridade')

        self.assertIn('tipo=incidente', resposta.context['filtros_querystring'])
        self.assertIn('ordem=prioridade', resposta.context['filtros_querystring'])


class VersaoDaFilaTests(TestCase):
    """A página da fila recarrega quando esta "versão" muda."""

    def test_muda_com_chamado_novo_e_com_atribuicao(self):
        inicial = versao_fila()
        chamado = criar_chamado()
        com_novo = versao_fila()
        chamado.atribuir(criar_tecnico())
        chamado.save()

        self.assertNotEqual(inicial, com_novo)
        self.assertNotEqual(com_novo, versao_fila())

    def test_estavel_sem_mudancas(self):
        criar_chamado()

        self.assertEqual(versao_fila(), versao_fila())

    def test_endpoint_da_versao(self):
        resposta = cliente(criar_tecnico()).get(reverse('chamados:fila_versao'))

        self.assertEqual(resposta.json()['versao'], versao_fila())

    def test_solicitante_continua_vendo_a_fila_dele_sem_script_de_atualizacao(self):
        solicitante = criar_solicitante()
        criar_chamado(solicitante=solicitante)

        self.assertNotIn('fila/versao', cliente(solicitante).get(URL).content.decode())


class HistoricoTests(TestCase):
    def test_historico_mostra_so_fechados_e_busca(self):
        fechado = criar_chamado(descricao='Impressora do 3º andar sem toner')
        outro_fechado = criar_chamado()
        aberto = criar_chamado(descricao='Impressora travando')
        Chamado.objects.filter(pk__in=[fechado.pk, outro_fechado.pk]).update(status=Chamado.Status.FECHADO)
        url = reverse('chamados:historico')
        c = cliente(criar_tecnico())

        self.assertEqual(list(c.get(url).context['chamados']), [])  # nada antes de buscar
        todos = {ch.pk for ch in c.get(url, {'buscar': '1'}).context['chamados']}
        self.assertTrue({fechado.pk, outro_fechado.pk} <= todos)
        self.assertNotIn(aberto.pk, todos)
        self.assertEqual([ch.pk for ch in c.get(url, {'q': 'toner'}).context['chamados']], [fechado.pk])
        self.assertEqual([ch.pk for ch in c.get(url, {'q': fechado.codigo}).context['chamados']], [fechado.pk])

    def test_historico_filtros(self):
        setor = criar_setor()
        tecnico = criar_tecnico()
        alvo = criar_chamado(setor=setor)
        outro = criar_chamado()
        Chamado.objects.filter(pk__in=[alvo.pk, outro.pk]).update(status=Chamado.Status.FECHADO)
        Chamado.objects.filter(pk=alvo.pk).update(atendente=tecnico, fechado_em=timezone.now() - timedelta(days=10))
        Chamado.objects.filter(pk=outro.pk).update(fechado_em=timezone.now())
        c = cliente(criar_tecnico())

        def buscar(**filtros):
            return {ch.pk for ch in c.get(reverse('chamados:historico'), filtros).context['chamados']}

        self.assertEqual(buscar(setor=setor.pk), {alvo.pk})
        self.assertEqual(buscar(atendente=tecnico.pk), {alvo.pk})
        limite = (timezone.now() - timedelta(days=5)).date().isoformat()
        self.assertIn(outro.pk, buscar(de=limite))
        self.assertNotIn(alvo.pk, buscar(de=limite))
        self.assertIn(alvo.pk, buscar(ate=limite))
        self.assertNotIn(outro.pk, buscar(ate=limite))
        # valores inválidos são ignorados em vez de dar erro
        self.assertEqual(c.get(reverse('chamados:historico'), {'setor': 'x', 'de': '2026-02-30'}).status_code, 200)


class ColunasDaFilaTests(TestCase):
    URL = reverse('chamados:colunas_fila')

    def setUp(self):
        self.tecnico = criar_tecnico()
        self.c = cliente(self.tecnico)

    def colunas_na_tela(self, c=None):
        """Chaves das colunas visíveis no cabeçalho da fila, na ordem em que aparecem."""
        return [(col['chave'], col['visivel']) for col in (c or self.c).get(reverse('chamados:list')).context['colunas']]

    def test_padrao_tem_as_nove_colunas_na_ordem_original(self):
        self.assertEqual([chave for chave, _ in self.colunas_na_tela()], list(COLUNAS_FILA))
        self.assertTrue(all(visivel for _, visivel in self.colunas_na_tela()))

    def test_salva_ordem_e_colunas_ocultas_no_usuario(self):
        resposta = self.c.post(self.URL, {'ordem': ['prazo_sla', 'titulo'], 'ocultas': ['setor']})

        self.assertEqual(resposta.status_code, 200)
        colunas = self.colunas_na_tela()
        self.assertEqual([chave for chave, _ in colunas][:3], ['codigo', 'prazo_sla', 'titulo'])
        self.assertEqual(len(colunas), len(COLUNAS_FILA))  # as que faltaram entram na posição padrão
        self.assertIn(('setor', False), colunas)
        # Vale em outra sessão/computador: está no usuário, não no navegador.
        self.assertIn(('setor', False), self.colunas_na_tela(cliente(self.tecnico)))

    def test_codigo_e_fixo_e_chaves_invalidas_sao_ignoradas(self):
        self.c.post(self.URL, {'ordem': ['titulo', 'codigo', 'inexistente', 'titulo'], 'ocultas': ['codigo', 'xyz']})

        colunas = self.colunas_na_tela()
        self.assertEqual(colunas[0], ('codigo', True))
        self.assertEqual(colunas[1], ('titulo', True))
        self.assertEqual(len(colunas), len(COLUNAS_FILA))

    def test_restaurar_padrao(self):
        self.c.post(self.URL, {'ordem': ['prazo_sla'], 'ocultas': ['setor']})
        self.c.post(self.URL, {'restaurar': '1'})

        self.tecnico.refresh_from_db()
        self.assertEqual(self.tecnico.colunas_fila, {})
        self.assertEqual(self.colunas_na_tela(), [(chave, True) for chave in COLUNAS_FILA])

    def test_solicitante_nao_personaliza_e_ve_o_padrao(self):
        solicitante = criar_solicitante(colunas_fila={'ordem': ['prazo_sla'], 'ocultas': ['setor']})
        c = cliente(solicitante)

        self.assertEqual(c.post(self.URL, {'ocultas': ['titulo']}).status_code, 403)
        self.assertEqual(self.colunas_na_tela(c), [(chave, True) for chave in COLUNAS_FILA])
        self.assertNotIn('menuColunas', c.get(reverse('chamados:list')).content.decode())

    def test_coluna_oculta_renderizada_escondida(self):
        criar_chamado()
        self.c.post(self.URL, {'ocultas': ['setor']})

        html = self.c.get(reverse('chamados:list')).content.decode()
        self.assertIn('data-col="setor" class="d-none"', html)


class AbasMeusChamadosTests(TestCase):
    def setUp(self):
        self.solicitante = criar_solicitante()
        self.aberto = criar_chamado(solicitante=self.solicitante)
        self.fechado = criar_chamado(solicitante=self.solicitante)
        Chamado.objects.filter(pk=self.fechado.pk).update(status=Chamado.Status.FECHADO, fechado_em=timezone.now(), avaliacao=4)
        self.c = cliente(self.solicitante)

    def test_aba_em_aberto_e_o_padrao_e_nao_mostra_fechados(self):
        resposta = self.c.get(reverse('chamados:list'))

        self.assertEqual(resposta.context['aba'], 'abertos')
        self.assertEqual([c.pk for c in resposta.context['chamados']], [self.aberto.pk])
        self.assertEqual((resposta.context['total_abertos'], resposta.context['total_fechados']), (1, 1))

    def test_aba_fechados_mostra_so_fechados_com_avaliacao(self):
        resposta = self.c.get(reverse('chamados:list'), {'aba': 'fechados'})

        self.assertEqual([c.pk for c in resposta.context['chamados']], [self.fechado.pk])
        self.assertContains(resposta, '4 de 5 estrelas')
        self.assertContains(resposta, 'Fechado em')

    def test_equipe_nao_tem_abas(self):
        self.assertIsNone(cliente(criar_tecnico()).get(reverse('chamados:list')).context['aba'])
