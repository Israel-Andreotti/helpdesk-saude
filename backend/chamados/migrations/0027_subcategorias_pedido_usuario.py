from django.db import migrations

ANTIGA = 'Criação/exclusão/alteração de usuário'
CRIACAO = 'Criação de usuário'
EXCLUSAO = 'Exclusão de usuário'
ALTERACAO = 'Alteração de usuário'


def separar(apps, schema_editor):
    """Divide a subcategoria antiga em três: criação e exclusão (só gestores/VIP, com campos próprios no
    formulário) e alteração (qualquer solicitante). Os chamados antigos continuam na primeira (renomeada
    para "Criação de usuário") e mantêm o título que copiaram na abertura."""
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    antiga = Subcategoria.objects.filter(nome__iexact=ANTIGA).first()
    if not antiga:
        return
    antiga.nome = CRIACAO
    antiga.pedido_usuario = 'criacao'
    antiga.save(update_fields=['nome', 'pedido_usuario'])
    for nome, pedido in ((EXCLUSAO, 'exclusao'), (ALTERACAO, '')):
        Subcategoria.objects.get_or_create(
            categoria_id=antiga.categoria_id, nome=nome,
            defaults={'tipo': antiga.tipo, 'prioridade': antiga.prioridade, 'pedido_usuario': pedido},
        )


def juntar(apps, schema_editor):
    Subcategoria = apps.get_model('chamados', 'Subcategoria')
    Chamado = apps.get_model('chamados', 'Chamado')
    criacao = Subcategoria.objects.filter(nome=CRIACAO).first()
    if not criacao:
        return
    for nome in (EXCLUSAO, ALTERACAO):
        outra = Subcategoria.objects.filter(categoria_id=criacao.categoria_id, nome=nome).first()
        if outra:
            Chamado.objects.filter(subcategoria=outra).update(subcategoria=criacao)
            outra.delete()
    criacao.nome = ANTIGA
    criacao.save(update_fields=['nome'])


class Migration(migrations.Migration):
    dependencies = [
        ('chamados', '0026_pedido_novo_usuario'),
    ]

    operations = [
        migrations.RunPython(separar, juntar),
    ]
