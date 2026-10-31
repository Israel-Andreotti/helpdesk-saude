from django import forms
from django.db import transaction

from .models import Ativo, Marca, Modelo

# Valor enviado pelo select (Tom Select) quando o administrador digita uma marca/modelo que não existe.
PREFIXO_NOVO = 'novo:'


class MarcaModeloFormMixin(forms.ModelForm):
    """Marca e Modelo escolhidos de listas padronizadas (select pesquisável com cascata Marca → Modelo
    no template). Cada campo recebe o id de uma opção existente ou "novo:<nome>" para criar uma —
    só aceito de administradores (`pode_criar`). Nomes novos que já existem (sem diferenciar
    maiúsculas) reaproveitam o cadastro existente. A marca/modelo novos só são gravados no save()."""

    marca = forms.CharField(label='Marca', widget=forms.Select(attrs={'class': 'form-select', 'data-select-marca': ''}))
    modelo = forms.CharField(label='Modelo', widget=forms.Select(attrs={'class': 'form-select', 'data-select-modelo': ''}))

    def __init__(self, *args, pode_criar=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.pode_criar = pode_criar
        self.fields['marca'].widget.choices = [('', 'Selecione a marca')] + [(m.pk, m.nome) for m in Marca.objects.all()]
        self.fields['modelo'].widget.choices = [('', 'Selecione o modelo')] + [
            (m.pk, f'{m.marca.nome} {m.nome}') for m in Modelo.objects.select_related('marca')
        ]
        if self.instance.pk and not self.is_bound:
            self.initial['marca'] = self.instance.modelo.marca_id
            self.initial['modelo'] = self.instance.modelo_id
        self._marca = self._modelo = None

    def _nome_novo(self, campo, valor):
        nome = valor[len(PREFIXO_NOVO):].strip()
        if not self.pode_criar:
            self.add_error(campo, f'Só administradores podem cadastrar {"uma marca nova" if campo == "marca" else "um modelo novo"}.')
            return None
        if not nome:
            self.add_error(campo, 'Informe o nome.')
            return None
        if len(nome) > 100:
            self.add_error(campo, 'O nome pode ter no máximo 100 caracteres.')
            return None
        return nome

    def clean(self):
        cleaned_data = super().clean()
        valor_marca = (cleaned_data.get('marca') or '').strip()
        valor_modelo = (cleaned_data.get('modelo') or '').strip()

        # Marca: objeto existente ou nome a criar.
        if valor_marca.startswith(PREFIXO_NOVO):
            nome = self._nome_novo('marca', valor_marca)
            if nome:
                self._marca = Marca.objects.filter(nome__iexact=nome).first() or nome
        elif valor_marca.isdigit() and Marca.objects.filter(pk=valor_marca).exists():
            self._marca = Marca.objects.get(pk=valor_marca)
        elif valor_marca:
            self.add_error('marca', 'Escolha uma marca da lista.')

        # Modelo: precisa ser da marca escolhida.
        if self._marca is None:
            return cleaned_data
        if valor_modelo.startswith(PREFIXO_NOVO):
            nome = self._nome_novo('modelo', valor_modelo)
            if nome:
                existente = None
                if isinstance(self._marca, Marca):
                    existente = Modelo.objects.filter(marca=self._marca, nome__iexact=nome).first()
                self._modelo = existente or nome
        elif valor_modelo.isdigit() and isinstance(self._marca, Marca) and Modelo.objects.filter(
            pk=valor_modelo, marca=self._marca
        ).exists():
            self._modelo = Modelo.objects.get(pk=valor_modelo)
        elif valor_modelo:
            self.add_error('modelo', f'Escolha um modelo da marca {self._marca}.')
        return cleaned_data

    @transaction.atomic
    def save(self, commit=True):
        marca = self._marca
        if isinstance(marca, str):
            marca = Marca.objects.create(nome=marca)
        modelo = self._modelo
        if isinstance(modelo, str):
            modelo = Modelo.objects.create(marca=marca, nome=modelo)
        self.instance.modelo = modelo
        return super().save(commit=commit)


class AtivoCadastroForm(MarcaModeloFormMixin):
    """Cadastro inicial: todo ativo novo entra disponível, lotado na TI. O patrimônio é gerado automaticamente."""

    class Meta:
        model = Ativo
        fields = ['tipo']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
        }

    field_order = ['marca', 'modelo', 'tipo']


class AtivoEditarForm(MarcaModeloFormMixin):
    field_order = ['marca', 'modelo', 'tipo', 'status', 'setor', 'funcionario']

    class Meta:
        model = Ativo
        fields = ['tipo', 'status', 'setor', 'funcionario']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'status': forms.Select(attrs={'class': 'form-select'}),
            'setor': forms.Select(attrs={'class': 'form-select'}),
            'funcionario': forms.HiddenInput(),
        }
        help_texts = {
            'setor': 'Deixe em branco se o ativo estiver atribuído a um funcionário.',
            'funcionario': 'Deixe em branco se o ativo estiver lotado num setor.',
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['setor'].required = False
        self.fields['setor'].empty_label = 'Sem setor'
        self.fields['funcionario'].required = False

    def clean(self):
        cleaned_data = super().clean()
        if cleaned_data.get('setor') and cleaned_data.get('funcionario'):
            raise forms.ValidationError(
                'Um ativo não pode estar lotado num setor e atribuído a um funcionário ao mesmo tempo. Escolha só um.'
            )
        return cleaned_data
