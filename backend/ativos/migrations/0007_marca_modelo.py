import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    """Cria as tabelas de Marca e Modelo e um campo provisório no ativo para ligar ao Modelo
    (preenchido na 0008, a partir do texto de marca/modelo)."""

    dependencies = [
        ('ativos', '0006_remove_status_triagem'),
    ]

    operations = [
        migrations.CreateModel(
            name='Marca',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
            ],
            options={'ordering': ['nome']},
        ),
        migrations.AddConstraint(
            model_name='marca',
            constraint=models.UniqueConstraint(django.db.models.functions.text.Lower('nome'), name='marca_nome_unico'),
        ),
        migrations.CreateModel(
            name='Modelo',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nome', models.CharField(max_length=100)),
                ('marca', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='modelos', to='ativos.marca')),
            ],
            options={'ordering': ['marca__nome', 'nome']},
        ),
        migrations.AddConstraint(
            model_name='modelo',
            constraint=models.UniqueConstraint('marca', django.db.models.functions.text.Lower('nome'), name='modelo_nome_unico_por_marca'),
        ),
        migrations.AddField(
            model_name='ativo',
            name='modelo_ref',
            field=models.ForeignKey(null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to='ativos.modelo'),
        ),
    ]
