import re

from django.db import migrations

PARTICULAS_NOME = {'da', 'de', 'do', 'das', 'dos', 'e'}


def padronizar_nome(texto, continuacao=False):
    # Cópia de usuarios.models.padronizar_nome (migração não deve depender do código atual do app).
    resultado = []
    for i, palavra in enumerate((texto or '').split()):
        minuscula = palavra.lower()
        if (i > 0 or continuacao) and minuscula in PARTICULAS_NOME:
            resultado.append(minuscula)
        else:
            resultado.append(re.sub(r"(^|[-'’])(\w)", lambda m: m.group(1) + m.group(2).upper(), minuscula))
    return ' '.join(resultado)


def padronizar(apps, schema_editor):
    """Nomes já cadastrados passam a ter iniciais maiúsculas (os novos são padronizados no save())."""
    Usuario = apps.get_model('usuarios', 'Usuario')
    for usuario in Usuario.objects.only('pk', 'first_name', 'last_name'):
        nome, sobrenome = padronizar_nome(usuario.first_name), padronizar_nome(usuario.last_name, continuacao=True)
        if (nome, sobrenome) != (usuario.first_name, usuario.last_name):
            Usuario.objects.filter(pk=usuario.pk).update(first_name=nome, last_name=sobrenome)


class Migration(migrations.Migration):
    dependencies = [
        ('usuarios', '0010_usuario_colunas_fila'),
    ]

    operations = [
        migrations.RunPython(padronizar, migrations.RunPython.noop),
    ]
