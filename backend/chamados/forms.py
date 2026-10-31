import re

from django import forms

from .models import Categoria, Chamado, ProcedimentoEntry, SLAPrioridade, Subcategoria


class PlaceholderSelect(forms.Select):
    """Select em que a opção vazia ("Selecione...") funciona como placeholder: fica desabilitada e
    oculta na lista, e o campo aparece em cinza enquanto nada foi escolhido (CSS .hd-select-placeholder)."""

    def __init__(self, attrs=None, choices=()):
        attrs = {**(attrs or {})}
        attrs['class'] = f"{attrs.get('class', 'form-select')} hd-select-placeholder".strip()
        super().__init__(attrs, choices)

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value in (None, ''):
            option['attrs']['disabled'] = True
            option['attrs']['hidden'] = True
        return option


class SetorSelect(PlaceholderSelect):
    """Select de setor que marca os setores críticos com data-critico, para o template avisar
    (abaixo do campo) quando o setor escolhido eleva a prioridade do chamado."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, '') and value.instance.critico:
            option['attrs']['data-critico'] = '1'
        return option


class SubcategoriaSelect(PlaceholderSelect):
    """Select que anota cada <option> com data-categoria, para o JS de cascata filtrar no template."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value not in (None, ''):
            subcategoria = value.instance  # já carregada pelo queryset (sem consulta por opção)
            option['attrs']['data-categoria'] = subcategoria.categoria_id
            option['attrs']['data-tipo'] = subcategoria.get_tipo_display()
            if subcategoria.pedido_usuario:
                option['attrs']['data-pedido-usuario'] = subcategoria.pedido_usuario
        return option


class ChamadoCreateForm(forms.ModelForm):
    # Dados do funcionário: só para a subcategoria de criação de usuário, que apenas gestores
    # (solicitantes VIP) podem abrir. O template mostra estes campos ao escolhê-la.
    novo_first_name = forms.CharField(label='Nome do funcionário', max_length=150, required=False,
                                      widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    novo_last_name = forms.CharField(label='Sobrenome', max_length=150, required=False,
                                     widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    novo_email = forms.EmailField(label='E-mail', required=False,
                                  widget=forms.EmailInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    novo_telefone = forms.CharField(label='Telefone (opcional)', max_length=20, required=False,
                                    widget=forms.TextInput(attrs={
                                        'class': 'form-control', 'placeholder': '(00)00000-0000', 'inputmode': 'numeric',
                                        'maxlength': '14', 'data-telefone-mask': '', 'autocomplete': 'off',
                                    }))
    # O setor do funcionário é o do gestor que pede (definido na view), não um campo do formulário.

    # Exclusão de usuário (também só gestores): quem sai, identificado por nome completo e matrícula.
    excluir_nome = forms.CharField(label='Nome completo', max_length=300, required=False,
                                   widget=forms.TextInput(attrs={'class': 'form-control', 'autocomplete': 'off'}))
    excluir_matricula = forms.CharField(label='Matrícula', max_length=20, required=False,
                                        widget=forms.TextInput(attrs={
                                            'class': 'form-control', 'inputmode': 'numeric', 'autocomplete': 'off',
                                        }))

    class Meta:
        model = Chamado
        fields = ['categoria', 'subcategoria', 'setor', 'descricao']
        widgets = {
            'categoria': PlaceholderSelect(attrs={'class': 'form-select', 'id': 'id_categoria'}),
            'subcategoria': SubcategoriaSelect(attrs={'class': 'form-select', 'id': 'id_subcategoria'}),
            'setor': SetorSelect(attrs={'class': 'form-select', 'id': 'id_setor'}),
            'descricao': forms.Textarea(attrs={'class': 'form-control', 'rows': 4}),
        }

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.fields['categoria'].required = True
        self.fields['categoria'].empty_label = 'Selecione uma categoria'
        self.fields['subcategoria'].required = True
        self.fields['subcategoria'].empty_label = 'Selecione uma subcategoria'
        subcategorias = Subcategoria.objects.select_related('categoria')
        if not self.pode_pedir_usuario:
            subcategorias = subcategorias.filter(pedido_usuario='')
        self.fields['subcategoria'].queryset = subcategorias
        # Nos pedidos de usuário a descrição é opcional (os dados vêm dos campos do funcionário).
        self.fields['descricao'].required = False
        self.fields['descricao'].label = 'Descrição'
        self.fields['setor'].required = True
        self.fields['setor'].empty_label = 'Selecione um setor'
        if usuario is not None and usuario.setor_id and not self.is_bound:
            self.fields['setor'].initial = usuario.setor_id

    def clean(self):
        cleaned_data = super().clean()
        categoria = cleaned_data.get('categoria')
        subcategoria = cleaned_data.get('subcategoria')
        if categoria and subcategoria and subcategoria.categoria_id != categoria.id:
            self.add_error('subcategoria', 'Selecione uma subcategoria pertencente à categoria escolhida.')
        if subcategoria and subcategoria.so_gestor and not self.pode_pedir_usuario:
            self.add_error('subcategoria', 'Somente gestores (solicitantes VIP) podem pedir a criação ou exclusão de usuários.')
        if subcategoria and subcategoria.exclui_usuario:
            self._limpar_exclusao(cleaned_data)
        elif subcategoria and subcategoria.cria_usuario:
            for campo in ('novo_first_name', 'novo_last_name', 'novo_email'):
                if not cleaned_data.get(campo):
                    self.add_error(campo, 'Informe este dado do funcionário.')
            telefone = re.sub(r'\D', '', cleaned_data.get('novo_telefone') or '')
            if telefone and not 10 <= len(telefone) <= 11:
                self.add_error('novo_telefone', 'Telefone inválido. Informe o DDD e o número (10 ou 11 dígitos).')
            cleaned_data['novo_telefone'] = telefone
            if not (cleaned_data.get('descricao') or '').strip() and cleaned_data.get('novo_first_name'):
                cleaned_data['descricao'] = (
                    f"Criação de usuário para {cleaned_data['novo_first_name']} {cleaned_data.get('novo_last_name', '')}".strip() + '.'
                )
                self.instance.descricao = cleaned_data['descricao']
        elif not (cleaned_data.get('descricao') or '').strip():
            self.add_error('descricao', 'Este campo é obrigatório.')
        return cleaned_data

    def _limpar_exclusao(self, cleaned_data):
        """Exclusão de usuário: nome completo e matrícula são obrigatórios e a matrícula tem de ser de um
        usuário ativo. Os dados vão para o início da descrição (a observação do gestor, se houver, vem depois)."""
        from usuarios.models import Usuario, padronizar_nome

        nome = padronizar_nome(cleaned_data.get('excluir_nome'))
        matricula = (cleaned_data.get('excluir_matricula') or '').strip()
        if not nome:
            self.add_error('excluir_nome', 'Informe o nome completo de quem será excluído.')
        if not matricula:
            self.add_error('excluir_matricula', 'Informe a matrícula de quem será excluído.')
        elif not Usuario.objects.filter(matricula=matricula, is_active=True).exists():
            self.add_error('excluir_matricula', 'Nenhum usuário ativo com esta matrícula.')
        if nome and matricula:
            observacao = (cleaned_data.get('descricao') or '').strip()
            cleaned_data['descricao'] = f'Exclusão de usuário: {nome} (matrícula {matricula}).' + (
                f'\n\n{observacao}' if observacao else ''
            )
            self.instance.descricao = cleaned_data['descricao']

    @property
    def pode_pedir_usuario(self):
        return bool(self.usuario and self.usuario.vip)

    @property
    def pede_usuario(self):
        """Pedido de criação de usuário (a view grava os dados do funcionário em SolicitacaoUsuario)."""
        subcategoria = self.cleaned_data.get('subcategoria')
        return bool(subcategoria and subcategoria.cria_usuario)


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = Categoria
        fields = ['nome']
        labels = {'nome': 'Nome da categoria'}
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'autofocus': True}),
        }


class SubcategoriaForm(forms.ModelForm):
    """Adiciona uma subcategoria a uma categoria já definida (tela de edição da categoria)."""

    class Meta:
        model = Subcategoria
        fields = ['nome', 'tipo', 'prioridade']
        labels = {'nome': 'Nome da subcategoria', 'tipo': 'Tipo', 'prioridade': 'Prioridade padrão'}
        widgets = {
            'nome': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Ex.: Impressora'}),
            'tipo': forms.Select(attrs={'class': 'form-select'}),
            'prioridade': forms.Select(attrs={'class': 'form-select'}),
        }

    def __init__(self, *args, categoria, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.categoria = categoria

    def clean_nome(self):
        # unique_together (categoria, nome) não é validado pelo form porque `categoria` não é campo dele.
        nome = self.cleaned_data['nome'].strip()
        if Subcategoria.objects.filter(categoria=self.instance.categoria, nome__iexact=nome).exists():
            raise forms.ValidationError(f'Já existe a subcategoria "{nome}" nesta categoria.')
        return nome


class SLAPrioridadeForm(forms.ModelForm):
    class Meta:
        model = SLAPrioridade
        fields = ['horas']
        labels = {'horas': 'Prazo (em horas)'}
        widgets = {
            'horas': forms.NumberInput(attrs={'class': 'form-control', 'min': 1}),
        }


class ProcedimentoEntryForm(forms.ModelForm):
    class Meta:
        model = ProcedimentoEntry
        fields = ['tipo', 'texto']
        widgets = {
            'tipo': forms.HiddenInput(),
            'texto': forms.Textarea(attrs={
                'class': 'form-control',
                'rows': 3,
                'placeholder': 'Descreva o procedimento realizado...',
            }),
        }

    def clean_tipo(self):
        # "Resposta do solicitante" só é criada pela view do solicitante, nunca pela equipe.
        tipo = self.cleaned_data.get('tipo')
        if tipo not in (ProcedimentoEntry.Tipo.PUBLICO, ProcedimentoEntry.Tipo.INTERNO):
            raise forms.ValidationError('Tipo de registro inválido.')
        return tipo
