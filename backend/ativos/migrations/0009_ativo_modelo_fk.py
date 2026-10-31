import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    """Troca os campos de texto marca/modelo pela ligação com Modelo (a marca vem do modelo)."""

    dependencies = [
        ('ativos', '0008_ativos_para_marca_modelo'),
    ]

    operations = [
        migrations.AlterModelOptions(
            name='ativo',
            options={'ordering': ['modelo__marca__nome', 'modelo__nome']},
        ),
        migrations.RemoveField(model_name='ativo', name='marca'),
        migrations.RemoveField(model_name='ativo', name='modelo'),
        migrations.RenameField(model_name='ativo', old_name='modelo_ref', new_name='modelo'),
        migrations.AlterField(
            model_name='ativo',
            name='modelo',
            field=models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='ativos', to='ativos.modelo'),
        ),
    ]
