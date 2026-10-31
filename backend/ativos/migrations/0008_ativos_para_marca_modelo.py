from django.db import migrations


def converter(apps, schema_editor):
    """Cria Marca/Modelo a partir do texto atual de cada ativo (sem diferenciar maiúsculas:
    "hp" e "Hp" viram a mesma marca) e liga o ativo ao modelo."""
    Ativo = apps.get_model('ativos', 'Ativo')
    Marca = apps.get_model('ativos', 'Marca')
    Modelo = apps.get_model('ativos', 'Modelo')
    for ativo in Ativo.objects.all():
        nome_marca = (ativo.marca or '').strip() or 'Sem marca'
        nome_modelo = (ativo.modelo or '').strip() or 'Sem modelo'
        marca = Marca.objects.filter(nome__iexact=nome_marca).first() or Marca.objects.create(nome=nome_marca)
        modelo = (
            Modelo.objects.filter(marca=marca, nome__iexact=nome_modelo).first()
            or Modelo.objects.create(marca=marca, nome=nome_modelo)
        )
        ativo.modelo_ref = modelo
        ativo.save(update_fields=['modelo_ref'])


def reverter(apps, schema_editor):
    Ativo = apps.get_model('ativos', 'Ativo')
    for ativo in Ativo.objects.select_related('modelo_ref__marca'):
        ativo.marca = ativo.modelo_ref.marca.nome
        ativo.modelo = ativo.modelo_ref.nome
        ativo.save(update_fields=['marca', 'modelo'])


class Migration(migrations.Migration):
    dependencies = [
        ('ativos', '0007_marca_modelo'),
    ]

    operations = [
        migrations.RunPython(converter, reverter),
    ]
