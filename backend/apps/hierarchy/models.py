from django.contrib.postgres.indexes import GinIndex
from django.db import models

from apps.core.models import BaseModel, VersionedMixin


class Channel(BaseModel):
    """Business channel (GT, MT, E-commerce, Rural)."""
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    description = models.TextField(blank=True)

    class Meta:
        db_table = 'hierarchy_channel'

    def __str__(self):
        return self.name


class GeographyType(BaseModel):
    """Represents the levels in the geography hierarchy (for example,
        country → region → state → territory).

        This hierarchy defines where work is performed. It is independent of the
        organisation hierarchy (NodeType/Node`) and is connected to it only through
        assignments.Assignment.
    """
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    levels = models.JSONField(default=list)
    # Per-territory custom fields (outlet_count, population, market_index, …). Same format
    # as NodeType.attribute_schema; drives geography-based target disaggregation.
    attribute_schema = models.JSONField(default=list)

    class Meta:
        db_table = 'hierarchy_geographytype'

    def __str__(self):
        return self.name


class GeographyNode(BaseModel):
    """Represents a location in the geography hierarchy.
    Uses a materialized path to make subtree lookups fast and efficient.
    """
    geography_type = models.ForeignKey(
        GeographyType,
        on_delete=models.CASCADE,
        related_name='nodes',
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    level = models.CharField(max_length=50)
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='children',
    )
    path = models.CharField(max_length=1000, db_index=True, blank=True, default='')
    depth = models.PositiveIntegerField(default=0)
    # Validated against geography_type.attribute_schema via GeographyService.validate_attributes.
    attributes = models.JSONField(default=dict)

    class Meta:
        db_table = 'hierarchy_geographynode'
        indexes = [
            models.Index(fields=['code'], name='hier_geo_code_idx'),
            models.Index(fields=['geography_type', 'level'], name='hier_geo_type_lvl_idx'),
            models.Index(fields=['parent', 'is_active'], name='hier_geo_par_act_idx'),
            models.Index(fields=['geography_type', 'parent', 'is_active'],
                         name='hier_geo_type_par_idx'),
            GinIndex(fields=['name'], name='hier_geo_name_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['code'], name='hier_geo_code_trgm', opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return f'{self.name} ({self.level})'

    def save(self, *args, **kwargs):
        if self.parent_id:
            row = type(self).objects.values('path', 'depth').get(pk=self.parent_id)
            self.path = row['path'] + self.code + '/'
            self.depth = row['depth'] + 1
        else:
            self.path = f'/{self.code}/'
            self.depth = 0
        super().save(*args, **kwargs)

    def get_subtree(self):
        """Returns all active descendant nodes, excluding the current node,using a path prefix match."""
        return type(self).objects.filter(
            path__startswith=self.path,
            is_active=True,
        ).exclude(pk=self.pk)

    def get_ancestors(self):
        """Walk parent chain to root. Returns list [parent, grandparent, …, root]."""
        ancestors = []
        pk = self.parent_id
        while pk:
            node = type(self).objects.get(pk=pk)
            ancestors.append(node)
            pk = node.parent_id
        return ancestors

    def get_direct_children(self):
        """Active direct children."""
        return self.children.filter(is_active=True)


class NodeType(BaseModel, VersionedMixin):
    """Defines a node type in the configurable organisation hierarchy.
    This hierarchy represents who does the work. The model was previously named
    `EntityType`, so the foreign key on `Node` is still called `entity_type` for
    backward compatibility.
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    level_order = models.PositiveIntegerField()
    allowed_parent_types = models.JSONField(default=list)
    allowed_child_types = models.JSONField(default=list)
    attribute_schema = models.JSONField(default=list)
    is_loginable = models.BooleanField(default=False)
    incentive_eligible = models.BooleanField(default=False)
    is_leaf = models.BooleanField(default=False)
    # Root types (e.g. NSM) must sit at the top — nodes of this type cannot have a parent.
    is_root_type = models.BooleanField(default=False)
    default_role = models.ForeignKey(
        'accounts.Role',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='node_types',
    )
    channel = models.ForeignKey(
        Channel,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='node_types',
    )
    display_config = models.JSONField(default=dict)

    class Meta:
        db_table = 'hierarchy_nodetype'
        ordering = ['level_order']
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'version'],
                name='hierarchy_nodetype_code_ver_uniq',
            ),
        ]

    def __str__(self):
        return f'{self.name} (v{self.version})'


class Node(BaseModel, VersionedMixin):
    """Represents a node in the configurable organisation hierarchy.

    Formerly `Entity`. Its relationship to geography territories is resolved
    exclusively through `assignments.Assignment` — never a static FK.
    """
    entity_type = models.ForeignKey(
        NodeType,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name='nodes',
    )
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, blank=True, default='')
    parent = models.ForeignKey(
        'self',
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='children',
    )
    attributes = models.JSONField(default=dict)
    channel = models.ForeignKey(
        Channel,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name='nodes',
    )
    path = models.CharField(max_length=1000, db_index=True, blank=True, default='')
    depth = models.PositiveIntegerField(default=0)
    status = models.CharField(max_length=20, default='active')

    class Meta:
        db_table = 'hierarchy_node'
        constraints = [
            models.UniqueConstraint(
                fields=['code', 'version'],
                name='hierarchy_node_code_ver_uniq',
            ),
        ]
        indexes = [
            models.Index(fields=['entity_type', 'is_current'], name='hier_node_type_cur_idx'),
            models.Index(fields=['parent', 'is_current'],      name='hier_node_par_cur_idx'),
            models.Index(fields=['status'],                    name='hier_node_status_idx'),
            models.Index(fields=['channel', 'entity_type'],    name='hier_node_chan_type_idx'),
            models.Index(fields=['path', 'is_current', 'is_active'], name='hier_node_path_cur_act_idx'),
            GinIndex(fields=['name'], name='hier_node_name_trgm', opclasses=['gin_trgm_ops']),
        ]

    def __str__(self):
        return f'{self.name} ({self.code})' if self.code else self.name

    def save(self, *args, **kwargs):
        if self.code:
            if self.parent_id:
                row = type(self).objects.values('path', 'depth').get(pk=self.parent_id)
                self.path = row['path'] + self.code + '/'
                self.depth = row['depth'] + 1
            else:
                self.path = f'/{self.code}/'
                self.depth = 0
        super().save(*args, **kwargs)

    def get_subtree(self):
        """All active descendants (path prefix match). Excludes self."""
        return type(self).objects.filter(
            path__startswith=self.path,
            is_current=True,
            is_active=True,
        ).exclude(pk=self.pk)

    def get_ancestors(self):
        """Walk parent chain to root. Returns list [parent, grandparent, …, root]."""
        ancestors = []
        pk = self.parent_id
        while pk:
            node = type(self).objects.get(pk=pk)
            ancestors.append(node)
            pk = node.parent_id
        return ancestors

    def get_direct_children(self):
        """Active current direct children."""
        return self.children.filter(is_current=True, is_active=True)

    def get_siblings(self):
        """Active current nodes sharing the same parent."""
        if not self.parent_id:
            return type(self).objects.none()
        return type(self).objects.filter(
            parent_id=self.parent_id,
            is_current=True,
            is_active=True,
        ).exclude(pk=self.pk)

    def get_team(self, entity_type_codes=None):
        """All active descendants, optionally filtered by node type codes."""
        qs = type(self).objects.filter(
            path__startswith=self.path,
            is_current=True,
            is_active=True,
        ).exclude(pk=self.pk)
        if entity_type_codes:
            qs = qs.filter(entity_type__code__in=entity_type_codes)
        return qs


class RelationshipType(BaseModel):
    """
    Named lateral relationship between two node types.
    E.g. "SO manages Distributor".
    """
    name = models.CharField(max_length=200)
    code = models.CharField(max_length=50, unique=True)
    from_entity_type = models.ForeignKey(
        NodeType,
        on_delete=models.CASCADE,
        related_name='from_relationship_types',
    )
    to_entity_type = models.ForeignKey(
        NodeType,
        on_delete=models.CASCADE,
        related_name='to_relationship_types',
    )
    allows_multiple = models.BooleanField(default=True)

    class Meta:
        db_table = 'hierarchy_relationshiptype'

    def __str__(self):
        return self.name


class NodeRelationship(BaseModel):
    """A single instance of a lateral relationship with effective dates (formerly EntityRelationship)."""
    relationship_type = models.ForeignKey(
        RelationshipType,
        on_delete=models.CASCADE,
        related_name='relationships',
    )
    from_entity = models.ForeignKey(
        Node,
        on_delete=models.CASCADE,
        related_name='outgoing_relationships',
    )
    to_entity = models.ForeignKey(
        Node,
        on_delete=models.CASCADE,
        related_name='incoming_relationships',
    )
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    class Meta:
        db_table = 'hierarchy_noderelationship'
        indexes = [
            models.Index(fields=['from_entity', 'relationship_type'], name='hierarchy_nr_from_type_idx'),
            models.Index(fields=['to_entity',   'relationship_type'], name='hierarchy_nr_to_type_idx'),
        ]

    def __str__(self):
        return f'{self.from_entity} → {self.to_entity} ({self.relationship_type})'
