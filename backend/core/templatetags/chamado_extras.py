from django import template

register = template.Library()

STATUS_CLASSES = {
    'aberto': 'status-aberto',
    'em_andamento': 'status-andamento',
    'aguardando_solicitante': 'status-aguardando',
    'fechado': 'status-fechado',
}

PRIORIDADE_CLASSES = {
    'baixa': 'prioridade-baixa',
    'media': 'prioridade-media',
    'alta': 'prioridade-alta',
    'critica': 'prioridade-critica',
}


@register.filter
def status_badge(status):
    return STATUS_CLASSES.get(status, 'status-aberto')


@register.filter
def prioridade_badge(prioridade):
    return PRIORIDADE_CLASSES.get(prioridade, 'prioridade-media')


@register.simple_tag
def chamados_aguardando_resposta(usuario):
    """Quantos chamados do solicitante precisam de uma ação dele (badge do menu): responder um
    chamado pausado aguardando a sua informação, ou avaliar/reabrir um chamado recém-fechado."""
    from chamados.models import Chamado

    if not getattr(usuario, 'is_authenticated', False) or not usuario.is_solicitante():
        return 0
    aguardando = Chamado.objects.filter(solicitante=usuario, status=Chamado.Status.AGUARDANDO_SOLICITANTE).count()
    from chamados.models import SolicitacaoUsuario

    return (
        aguardando + Chamado.fechados_para_avaliar(usuario).count()
        + SolicitacaoUsuario.links_prontos(usuario).count()
    )


@register.simple_tag
def respostas_nao_vistas(usuario):
    """Quantas respostas de solicitante o técnico ainda não viu (badge do menu da fila)."""
    from chamados.models import Chamado

    if not getattr(usuario, 'is_authenticated', False) or usuario.is_solicitante():
        return 0
    return Chamado.respostas_nao_vistas(usuario).count()


@register.filter
def iniciais(nome):
    partes = (nome or '').split()
    if not partes:
        return '?'
    if len(partes) == 1:
        return partes[0][:2].upper()
    return (partes[0][0] + partes[-1][0]).upper()


@register.filter
def duracao(valor):
    """timedelta -> texto curto ("45min", "3h 20min", "2d 5h"); vazio vira "—"."""
    if valor is None:
        return '—'
    minutos = int(valor.total_seconds() // 60)
    dias, resto = divmod(minutos, 60 * 24)
    horas, minutos = divmod(resto, 60)
    if dias:
        return f'{dias}d {horas}h'
    if horas:
        return f'{horas}h {minutos}min'
    return f'{minutos}min'


@register.inclusion_tag('chamados/_tipo_badge.html')
def tipo_badge(tipo, rotulo=None):
    """Selo "Incidente"/"Requisição" (ícone + texto, nunca só cor)."""
    return {'tipo': tipo, 'rotulo': rotulo}



@register.filter
def sla_distancia(chamado):
    """Distância até o prazo do SLA em texto curto ("2h 15min", "3d 4h", "12min"), para a fila.
    Só formata: se o prazo já passou, é o tempo desde o estouro."""
    from django.utils import timezone

    if not chamado.prazo_sla:
        return ''
    referencia = chamado.sla_pausado_em or timezone.now()
    minutos = int(abs((chamado.prazo_sla - referencia).total_seconds()) // 60)
    dias, resto = divmod(minutos, 24 * 60)
    horas, minutos = divmod(resto, 60)
    if dias:
        return f'{dias}d {horas}h' if horas else f'{dias}d'
    if horas:
        return f'{horas}h {minutos}min' if minutos else f'{horas}h'
    return f'{minutos}min'
