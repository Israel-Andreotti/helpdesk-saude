"""Ativos: patrimônio automático, lotação (setor ou funcionário), edição com histórico e exclusão."""

from django.test import TestCase
from django.urls import reverse

from ativos.forms import AtivoEditarForm
from ativos.models import Ativo, Marca, Modelo, MovimentacaoAtivo
from tests.fabricas import cliente, criar_admin, criar_setor, criar_solicitante, criar_tecnico, mensagens
from usuarios.models import Setor


def setor_ti():
    return Setor.objects.get_or_create(nome='TI')[0]


def criar_modelo(marca='Dell', modelo='Latitude'):
    marca_obj = Marca.objects.filter(nome__iexact=marca).first() or Marca.objects.create(nome=marca)
    return Modelo.objects.filter(marca=marca_obj, nome__iexact=modelo).first() or Modelo.objects.create(marca=marca_obj, nome=modelo)


def criar_ativo(**campos):
    campos.setdefault('setor', setor_ti())
    modelo = criar_modelo(campos.pop('marca', 'Dell'), campos.pop('modelo', 'Latitude'))
    return Ativo.objects.create(modelo=modelo, **campos)


class AtivoModelTests(TestCase):
    def test_patrimonio_e_sequencial_com_seis_digitos(self):
        primeiro = criar_ativo()
        segundo = criar_ativo()

        self.assertRegex(primeiro.patrimonio, r'^\d{6}$')
        self.assertEqual(int(segundo.patrimonio), int(primeiro.patrimonio) + 1)

    def test_patrimonio_manual_fora_do_padrao_nao_afeta_a_sequencia(self):
        anterior = criar_ativo()
        criar_ativo(patrimonio='PAT-ANTIGO')

        self.assertEqual(int(criar_ativo().patrimonio), int(anterior.patrimonio) + 1)

    def test_marca_vem_do_modelo(self):
        ativo = criar_ativo(marca='Lenovo', modelo='ThinkPad E14')

        self.assertEqual((ativo.marca.nome, ativo.modelo.nome), ('Lenovo', 'ThinkPad E14'))
        self.assertEqual(str(ativo), f'Lenovo ThinkPad E14 ({ativo.patrimonio})')

    def test_lotacao_por_extenso(self):
        funcionario = criar_solicitante(first_name='Ana', last_name='Souza')

        self.assertEqual(criar_ativo().lotacao_display, 'TI')
        self.assertEqual(criar_ativo(setor=None, funcionario=funcionario).lotacao_display, 'Ana Souza (funcionário)')
        self.assertEqual(criar_ativo(setor=None).lotacao_display, 'Sem lotação')

    def test_setor_e_funcionario_ao_mesmo_tempo_e_invalido(self):
        ativo = criar_ativo()
        form = AtivoEditarForm(instance=ativo, data={
            'marca': ativo.marca.pk, 'modelo': ativo.modelo.pk, 'tipo': 'notebook', 'status': 'em_uso',
            'setor': setor_ti().pk, 'funcionario': criar_solicitante().pk,
        })

        self.assertFalse(form.is_valid())
        self.assertIn('ao mesmo tempo', str(form.non_field_errors()))


class AtivoTelasTests(TestCase):
    def setUp(self):
        self.tecnico = criar_tecnico()
        self.c = cliente(self.tecnico)

    def editar(self, ativo, **dados):
        campos = {'marca': ativo.marca.pk, 'modelo': ativo.modelo.pk, 'tipo': ativo.tipo, 'status': ativo.status,
                  'setor': ativo.setor_id or '', 'funcionario': ativo.funcionario_id or ''}
        campos.update(dados)
        return self.c.post(reverse('ativos:editar', args=[ativo.pk]), campos, follow=True)

    def test_cadastro_entra_na_ti_como_disponivel(self):
        modelo = criar_modelo('HP', 'M24')
        self.c.post(reverse('ativos:cadastrar'), {'marca': modelo.marca.pk, 'modelo': modelo.pk, 'tipo': 'monitor'})

        ativo = Ativo.objects.get(modelo=modelo)
        self.assertEqual(ativo.setor, setor_ti())
        self.assertEqual(ativo.status, Ativo.Status.DISPONIVEL)

    def test_editar_lotacao_gera_movimentacao_efetivada(self):
        ativo = criar_ativo()
        destino = criar_setor()

        resposta = self.editar(ativo, setor=destino.pk)

        movimentacao = ativo.movimentacoes.get()
        self.assertEqual(movimentacao.status, MovimentacaoAtivo.Status.EFETIVADA)
        self.assertEqual((movimentacao.setor_origem, movimentacao.setor_destino), (setor_ti(), destino))
        self.assertEqual(movimentacao.realizado_por, self.tecnico)
        self.assertIsNone(movimentacao.chamado)
        self.assertTrue(any('Movimentação registrada no histórico' in m for m in mensagens(resposta)))

    def test_editar_sem_mudar_lotacao_nao_gera_movimentacao(self):
        ativo = criar_ativo()
        self.editar(ativo, status='danificado')

        self.assertFalse(ativo.movimentacoes.exists())

    def test_lotacao_bloqueada_com_movimentacao_pendente(self):
        ativo = criar_ativo()
        MovimentacaoAtivo.objects.create(ativo=ativo, setor_destino=criar_setor(), realizado_por=self.tecnico)

        resposta = self.editar(ativo, setor=criar_setor().pk)

        ativo.refresh_from_db()
        self.assertEqual(ativo.setor, setor_ti())
        self.assertContains(resposta, 'movimentação pendente')

    def test_ativo_com_historico_nao_pode_ser_excluido(self):
        ativo = criar_ativo()
        self.editar(ativo, setor=criar_setor().pk)

        resposta = cliente(criar_admin()).post(reverse('ativos:excluir', args=[ativo.pk]), follow=True)

        self.assertTrue(Ativo.objects.filter(pk=ativo.pk).exists())
        self.assertTrue(any('histórico de movimentações' in m for m in mensagens(resposta)))

    def test_ativo_sem_historico_pode_ser_excluido_pelo_admin(self):
        ativo = criar_ativo()
        cliente(criar_admin()).post(reverse('ativos:excluir', args=[ativo.pk]))

        self.assertFalse(Ativo.objects.filter(pk=ativo.pk).exists())

    def test_tecnico_nao_exclui_ativo(self):
        ativo = criar_ativo()

        self.assertEqual(self.c.post(reverse('ativos:excluir', args=[ativo.pk])).status_code, 403)
        self.assertTrue(Ativo.objects.filter(pk=ativo.pk).exists())

    def test_historico_do_ativo(self):
        ativo = criar_ativo()
        self.editar(ativo, setor=criar_setor().pk)

        resposta = self.c.get(reverse('ativos:historico', args=[ativo.pk]))

        self.assertEqual(len(resposta.context['movimentacoes']), 1)
        self.assertContains(resposta, 'Edição manual')


class ListaDeAtivosTests(TestCase):
    def setUp(self):
        self.c = cliente(criar_tecnico())

    def listar(self, **filtros):
        return set(self.c.get(reverse('ativos:list'), filtros).context['ativos'])

    def test_so_lista_depois_de_buscar(self):
        ativo = criar_ativo()
        self.assertEqual(self.listar(), set())
        self.assertIn(ativo, self.listar(buscar='1'))

    def test_filtros(self):
        setor = criar_setor()
        no_setor = criar_ativo(marca='zetamarca', setor=setor, tipo=Ativo.Tipo.MONITOR)
        funcionario = criar_solicitante(first_name='Gertrudes')
        com_funcionario = criar_ativo(marca='zetamarca', setor=None, funcionario=funcionario)
        self.assertEqual(self.listar(q='zetamarca'), {no_setor, com_funcionario})
        self.assertEqual(self.listar(setor=setor.pk), {no_setor})
        self.assertEqual(self.listar(q='zetamarca', tipo=Ativo.Tipo.MONITOR), {no_setor})
        self.assertEqual(self.listar(funcionario='gertrudes'), {com_funcionario})
        self.assertEqual(self.listar(funcionario=funcionario.matricula), {com_funcionario})


class MarcaModeloTests(TestCase):
    URL = reverse('ativos:cadastrar')

    def cadastrar(self, usuario, marca, modelo):
        return cliente(usuario).post(self.URL, {'marca': marca, 'modelo': modelo, 'tipo': 'notebook'})

    def test_admin_cria_marca_e_modelo_novos_pelo_formulario(self):
        self.cadastrar(criar_admin(), 'novo:Acer', 'novo:Aspire 5')

        ativo = Ativo.objects.get(modelo__nome='Aspire 5')
        self.assertEqual(ativo.marca.nome, 'Acer')

    def test_nome_novo_que_ja_existe_reaproveita_sem_duplicar(self):
        existente = criar_modelo('Dell', 'Latitude 5440')

        self.cadastrar(criar_admin(), 'novo:DELL', 'novo:latitude 5440')

        self.assertEqual(Marca.objects.filter(nome__iexact='dell').count(), 1)
        self.assertEqual(Modelo.objects.filter(marca=existente.marca, nome__iexact='latitude 5440').count(), 1)
        self.assertTrue(Ativo.objects.filter(modelo=existente).exists())

    def test_tecnico_nao_cria_marca_nem_modelo(self):
        modelo = criar_modelo('Dell', 'Optiplex')
        tecnico = criar_tecnico()

        resposta = self.cadastrar(tecnico, 'novo:Acer', 'novo:Aspire')
        self.assertFalse(Marca.objects.filter(nome='Acer').exists())
        self.assertIn('Só administradores', str(resposta.context['form'].errors))

        resposta = self.cadastrar(tecnico, modelo.marca.pk, 'novo:Vostro')
        self.assertFalse(Modelo.objects.filter(nome='Vostro').exists())

        self.cadastrar(tecnico, modelo.marca.pk, modelo.pk)
        self.assertTrue(Ativo.objects.filter(modelo=modelo).exists())

    def test_modelo_precisa_ser_da_marca_escolhida(self):
        de_outra_marca = criar_modelo('Motorola', 'Moto G54')
        dell = criar_modelo('Dell', 'Optiplex').marca

        resposta = self.cadastrar(criar_admin(), dell.pk, de_outra_marca.pk)

        self.assertFalse(Ativo.objects.filter(modelo=de_outra_marca).exists())
        self.assertIn('Escolha um modelo da marca', str(resposta.context['form'].errors))

    def test_formulario_traz_modelos_por_marca_para_a_cascata(self):
        modelo = criar_modelo('Samsung', 'Galaxy A15')

        resposta = cliente(criar_tecnico()).get(self.URL)

        self.assertIn({'value': str(modelo.pk), 'text': 'Galaxy A15'}, resposta.context['modelos_por_marca'][str(modelo.marca_id)])
        self.assertFalse(resposta.context['pode_criar_marca_modelo'])


class OrdenacaoDeAtivosTests(TestCase):
    def setUp(self):
        self.c = cliente(criar_tecnico())
        Ativo.objects.all().delete()
        self.primeiro = criar_ativo(marca='Zeta', modelo='A', tipo=Ativo.Tipo.CELULAR)
        self.segundo = criar_ativo(marca='Alfa', modelo='B', tipo=Ativo.Tipo.NOTEBOOK)

    def ordem(self, **params):
        return list(self.c.get(reverse('ativos:list'), {'buscar': '1', **params}).context['ativos'])

    def test_padrao_e_por_marca_e_modelo(self):
        self.assertEqual(self.ordem(), [self.segundo, self.primeiro])

    def test_outras_ordenacoes_e_opcao_invalida_cai_no_padrao(self):
        self.assertEqual(self.ordem(ordem='patrimonio'), [self.primeiro, self.segundo])
        self.assertEqual(self.ordem(ordem='recentes'), [self.segundo, self.primeiro])
        self.assertEqual(self.ordem(ordem='tipo'), [self.primeiro, self.segundo])
        self.assertEqual(self.ordem(ordem='xyz'), [self.segundo, self.primeiro])

    def test_so_trocar_a_ordem_nao_conta_como_busca(self):
        self.assertEqual(list(self.c.get(reverse('ativos:list'), {'ordem': 'patrimonio'}).context['ativos']), [])
