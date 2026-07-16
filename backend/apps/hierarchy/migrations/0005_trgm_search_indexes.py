"""Trigram GIN indexes so icontains search stays fast at 150k+ rows.

Serves /entities/search/ (name/code icontains) and geography ?q= filtering.
pg_trgm ships with PostgreSQL; TrigramExtension needs a role allowed to
CREATE EXTENSION on first run (pre-create the extension in prod if the app
role is unprivileged).
"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('hierarchy', '0004_geographynode_hier_geo_code_idx_and_more'),
    ]

    operations = [
        TrigramExtension(),
        migrations.AddIndex(
            model_name='node',
            index=GinIndex(fields=['name'], name='hier_node_name_trgm',
                           opclasses=['gin_trgm_ops']),
        ),
        migrations.AddIndex(
            model_name='geographynode',
            index=GinIndex(fields=['name'], name='hier_geo_name_trgm',
                           opclasses=['gin_trgm_ops']),
        ),
        migrations.AddIndex(
            model_name='geographynode',
            index=GinIndex(fields=['code'], name='hier_geo_code_trgm',
                           opclasses=['gin_trgm_ops']),
        ),
    ]
