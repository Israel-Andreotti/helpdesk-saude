from django.contrib import admin

from .models import Ativo, Marca, Modelo, MovimentacaoAtivo


class ModeloInline(admin.TabularInline):
    model = Modelo
    extra = 0


@admin.register(Marca)
class MarcaAdmin(admin.ModelAdmin):
    """Correção de nomes de marcas/modelos (ex.: "Hp" → "HP"); excluir só se nenhum ativo usar."""

    search_fields = ('nome',)
    inlines = [ModeloInline]


@admin.register(Ativo)
class AtivoAdmin(admin.ModelAdmin):
    list_display = ('marca', 'modelo', 'tipo', 'patrimonio', 'status', 'setor', 'funcionario')
    list_filter = ('status', 'tipo', 'setor', 'modelo__marca')
    search_fields = ('modelo__marca__nome', 'modelo__nome', 'patrimonio')
    list_select_related = ('modelo__marca', 'setor', 'funcionario')
    readonly_fields = ('patrimonio',)


@admin.register(MovimentacaoAtivo)
class MovimentacaoAtivoAdmin(admin.ModelAdmin):
    """Registro de auditoria: somente leitura, ninguém cria, altera ou apaga por aqui."""

    list_display = (
        'ativo', 'status', 'setor_origem', 'setor_destino', 'funcionario_origem', 'funcionario_destino',
        'realizado_por', 'chamado', 'criado_em', 'efetivada_em',
    )
    list_filter = ('status', 'criado_em')
    search_fields = ('ativo__patrimonio', 'ativo__modelo__marca__nome', 'ativo__modelo__nome')

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
