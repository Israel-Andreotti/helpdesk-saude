from django.contrib import admin

from .models import Categoria, Chamado, EventoChamado, ProcedimentoEntry, SLAPrioridade, SolicitacaoUsuario, Subcategoria


class SubcategoriaInline(admin.TabularInline):
    model = Subcategoria
    extra = 1
    fields = ('nome', 'tipo', 'prioridade', 'pedido_usuario')


@admin.register(Categoria)
class CategoriaAdmin(admin.ModelAdmin):
    list_display = ('nome', 'ordem')
    ordering = ('ordem', 'nome')
    inlines = [SubcategoriaInline]


class EventoChamadoInline(admin.TabularInline):
    """Log de auditoria do ciclo de vida: somente leitura."""

    model = EventoChamado
    extra = 0
    fields = ('criado_em', 'tipo', 'autor', 'descricao', 'publico')
    readonly_fields = fields
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


class ProcedimentoEntryInline(admin.TabularInline):
    model = ProcedimentoEntry
    extra = 0
    readonly_fields = ('autor', 'criado_em')


@admin.register(SLAPrioridade)
class SLAPrioridadeAdmin(admin.ModelAdmin):
    list_display = ('prioridade', 'horas')


@admin.register(Chamado)
class ChamadoAdmin(admin.ModelAdmin):
    list_display = ('codigo', 'titulo', 'categoria', 'subcategoria', 'status', 'prioridade', 'solicitante', 'atendente', 'criado_em')
    list_filter = ('status', 'prioridade', 'categoria')
    search_fields = ('codigo', 'titulo', 'descricao')
    readonly_fields = ('prioridade',)  # deriva sempre da subcategoria, ver Chamado.save()
    inlines = [EventoChamadoInline, ProcedimentoEntryInline]


@admin.register(SolicitacaoUsuario)
class SolicitacaoUsuarioAdmin(admin.ModelAdmin):
    """Pedidos de novo usuário (via chamado): somente consulta. O link de ativação não é exibido."""

    list_display = ('nome_completo', 'email', 'setor', 'chamado', 'usuario', 'link_gerado_em', 'ativado_em')
    search_fields = ('first_name', 'last_name', 'email', 'chamado__codigo')
    exclude = ('link_ativacao',)
    readonly_fields = ('chamado', 'first_name', 'last_name', 'email', 'telefone', 'setor', 'usuario',
                       'link_gerado_em', 'ativado_em')

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
