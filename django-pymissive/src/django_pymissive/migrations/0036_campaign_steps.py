# Campaign steps, in one step from the 1.8.5 schema.
#
# Schema is added first, historical campaign rows are copied onto steps,
# then the legacy channel columns are removed. The RunPython calls must stay
# between those schema operations: they read columns this migration drops.

import django.db.models.deletion
import django_geoaddress.fields
import django_providerkit.fields
import django_pymissive.fields
import django_pymissive.models.campaign_step
import namedid.fields
import phonenumber_field.modelfields
from django.db import migrations, models


TYPE_ORDER = (
    'email',
    'email_marketing',
    'ere',
    'sms',
    'rcs',
    'voice_call',
    'notification',
    'push_notification',
    'branded',
    'letter',
    'registered_letter',
    'hand_delivery',
)

EMAIL_TYPES = {'email', 'email_marketing', 'ere'}
PHONE_TYPES = {'sms', 'rcs', 'voice_call'}
APPLICATION_TYPES = {'notification', 'push_notification', 'branded'}
ADDRESS_TYPES = {'letter', 'registered_letter', 'hand_delivery'}


def _step_values(campaign, missive_type):
    values = {
        'subject': campaign.subject,
    }
    if missive_type in EMAIL_TYPES:
        values.update(
            acknowledgement=campaign.acknowledgement_email,
            sender_name=campaign.sender_email_name,
            sender_email=campaign.sender_email,
            reply_to_name=campaign.reply_to_email_name,
            reply_to_email=campaign.reply_to_email,
            body_rich=campaign.email_body_rich,
            body_rich_snapshot_html=campaign.email_body_rich_snapshot_html,
            body_text=campaign.email_body_text,
        )
    elif missive_type in PHONE_TYPES | APPLICATION_TYPES:
        values.update(
            sender_name=campaign.sender_phone_name,
            sender_phone=campaign.sender_phone,
            body_rich=campaign.phone_body_rich,
            body_rich_snapshot_html=campaign.phone_body_rich_snapshot_html,
            body_text=campaign.phone_body_text,
        )
    elif missive_type in ADDRESS_TYPES:
        registered = missive_type == 'registered_letter'
        values.update(
            acknowledgement=campaign.acknowledgement_letter,
            delivery_mode=campaign.delivery_mode_letter,
            priority=campaign.priority_letter,
            duplex_printing=(
                campaign.duplex_printing_registered_letter
                if registered
                else campaign.duplex_printing_letter
            ),
            color_printing=(
                campaign.color_printing_registered_letter
                if registered
                else campaign.color_printing_letter
            ),
            sender_name=campaign.sender_address_name,
            sender_address=campaign.sender_address,
            reply_to_name=campaign.reply_to_address_name,
            reply_to_address=campaign.reply_to_address,
            body_rich=campaign.first_document,
            body_rich_snapshot_html=campaign.first_document_snapshot_html,
        )
    return values


def _configured_fallback_types(campaign):
    types = set()
    if campaign.email_body_rich or campaign.email_body_text:
        types.add('email')
    if campaign.phone_body_rich or campaign.phone_body_text:
        types.add('sms')
    if campaign.first_document:
        types.add('letter')
    return types


def forwards(apps, schema_editor):
    Campaign = apps.get_model('django_pymissive', 'MissiveCampaign')
    CampaignStep = apps.get_model('django_pymissive', 'CampaignStep')
    CampaignTarget = apps.get_model('django_pymissive', 'CampaignTarget')
    Missive = apps.get_model('django_pymissive', 'Missive')
    Scheduled = apps.get_model('django_pymissive', 'MissiveScheduledCampaign')

    types_by_campaign = {}
    for campaign_id, missive_type in Missive.objects.exclude(campaign_id=None).values_list(
        'campaign_id',
        'missive_type',
    ):
        types_by_campaign.setdefault(campaign_id, set()).add(missive_type)
    for campaign_id, missive_type in CampaignTarget.objects.values_list('campaign_id', 'missive_type'):
        types_by_campaign.setdefault(campaign_id, set()).add(missive_type)
    for campaign_id, missive_type in Scheduled.objects.exclude(missive_type='*').values_list(
        'campaign_id',
        'missive_type',
    ):
        types_by_campaign.setdefault(campaign_id, set()).add(missive_type)

    order = {missive_type: position for position, missive_type in enumerate(TYPE_ORDER, start=1)}
    steps = []
    for campaign in Campaign.objects.all().iterator():
        missive_types = types_by_campaign.get(campaign.pk, set()) | _configured_fallback_types(campaign)
        sorted_types = sorted(missive_types, key=lambda value: (order.get(value, len(order) + 1), value))
        for position, missive_type in enumerate(sorted_types, start=1):
            steps.append(
                CampaignStep(
                    campaign_id=campaign.pk,
                    position=position,
                    label=missive_type.replace('_', ' ').title(),
                    missive_type=missive_type,
                    **_step_values(campaign, missive_type),
                )
            )
    CampaignStep.objects.bulk_create(steps)

    step_ids = {
        (campaign_id, missive_type): step_id
        for step_id, campaign_id, missive_type in CampaignStep.objects.values_list(
            'pk',
            'campaign_id',
            'missive_type',
        )
    }
    for missive in Missive.objects.exclude(campaign_id=None).only('pk', 'campaign_id', 'missive_type').iterator():
        missive.campaign_step_id = step_ids[(missive.campaign_id, missive.missive_type)]
        missive.save(update_fields=['campaign_step'])
    for target in CampaignTarget.objects.only('pk', 'campaign_id', 'missive_type').iterator():
        target.campaign_step_id = step_ids[(target.campaign_id, target.missive_type)]
        target.save(update_fields=['campaign_step'])


def backwards(apps, schema_editor):
    CampaignStep = apps.get_model('django_pymissive', 'CampaignStep')
    CampaignTarget = apps.get_model('django_pymissive', 'CampaignTarget')
    Missive = apps.get_model('django_pymissive', 'Missive')

    campaign_ids = dict(CampaignStep.objects.values_list('pk', 'campaign_id'))
    for missive in Missive.objects.exclude(campaign_step_id=None).only('pk', 'campaign_step_id').iterator():
        missive.campaign_id = campaign_ids[missive.campaign_step_id]
        missive.save(update_fields=['campaign'])
    CampaignTarget.objects.update(campaign_step=None)
    CampaignStep.objects.all().delete()

def scheduled_scope_types(missive_type, additional_config):
    """Types this run must keep. ``None`` means every step.

    ``*`` is the historical "all types" value. A selection run stored its
    real list in ``additional_config['missive_types']`` and left the column
    at ``*``, so that list is the scope. An empty list stays "every step".
    """
    concrete = str(missive_type or "")
    if concrete and concrete != "*":
        return [concrete]
    if isinstance(additional_config, dict):
        listed = [str(value) for value in additional_config.get("missive_types") or [] if value]
        if listed:
            return listed
    return None


def prepare_step_relations(apps, schema_editor):
    CampaignStep = apps.get_model("django_pymissive", "CampaignStep")
    CampaignTarget = apps.get_model("django_pymissive", "CampaignTarget")
    Scheduled = apps.get_model("django_pymissive", "MissiveScheduledCampaign")

    for scheduled in Scheduled.objects.iterator():
        types = scheduled_scope_types(scheduled.missive_type, scheduled.additional_config)
        if types is None:
            continue
        steps = list(
            CampaignStep.objects.filter(
                campaign_id=scheduled.campaign_id,
                missive_type__in=types,
            )
        )
        if steps:
            scheduled.campaign_steps.add(*steps)
            continue
        # No matching step must not fall through to "every step".
        config = dict(scheduled.additional_config or {})
        config["step_scope"] = "none"
        scheduled.additional_config = config
        scheduled.save(update_fields=["additional_config"])

    next_positions = {
        row["campaign_id"]: (row["position"] or 0) + 1
        for row in CampaignStep.objects.values("campaign_id")
        .order_by()
        .annotate(position=models.Max("position"))
    }
    for target in CampaignTarget.objects.select_related("campaign_step").iterator():
        step = target.campaign_step
        if (
            step is not None
            and step.campaign_id == target.campaign_id
            and step.missive_type == target.missive_type
        ):
            continue
        step = (
            CampaignStep.objects.filter(
                campaign_id=target.campaign_id,
                missive_type=target.missive_type,
            )
            .order_by("position", "pk")
            .first()
        )
        if step is None:
            position = next_positions.get(target.campaign_id, 1)
            step = CampaignStep.objects.create(
                campaign_id=target.campaign_id,
                position=position,
                label=target.missive_type.replace("_", " ").title(),
                missive_type=target.missive_type,
            )
            next_positions[target.campaign_id] = position + 1
        target.campaign_step_id = step.pk
        target.save(update_fields=["campaign_step"])


def restore_legacy_scope_fields(apps, schema_editor):
    CampaignTarget = apps.get_model("django_pymissive", "CampaignTarget")
    Scheduled = apps.get_model("django_pymissive", "MissiveScheduledCampaign")

    for target in CampaignTarget.objects.select_related("campaign_step").iterator():
        target.missive_type = target.campaign_step.missive_type
        target.save(update_fields=["missive_type"])

    for scheduled in Scheduled.objects.prefetch_related("campaign_steps").iterator():
        types = set(scheduled.campaign_steps.values_list("missive_type", flat=True))
        scheduled.missive_type = next(iter(types)) if len(types) == 1 else "*"
        config = dict(scheduled.additional_config or {})
        config.pop("step_scope", None)
        scheduled.additional_config = config
        scheduled.save(update_fields=["missive_type", "additional_config"])


class Migration(migrations.Migration):

    dependencies = [
        ("contenttypes", "0002_remove_content_type_name"),
        ("django_pymissive", "0035_missive_send_via_task"),
    ]

    operations = [
        migrations.AddField(
            model_name="missive",
            name="is_internal",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text="Internal missive, kept apart from campaign sending.",
                verbose_name="Internal",
            ),
        ),
        migrations.CreateModel(
            name='CampaignStep',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('comment', models.TextField(blank=True, help_text='Internal comment or note', null=True, verbose_name='Comment')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Created At')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Updated At')),
                ('additional_context', django_pymissive.fields.JSONField(blank=True, default=dict, help_text='Additional context as JSON', verbose_name='Additional context')),
                ('additional_config', django_pymissive.fields.JSONField(blank=True, default=dict, help_text='Additional configuration as JSON', verbose_name='Additional configuration')),
                ('metadata', django_pymissive.fields.JSONField(blank=True, default=dict, help_text='Additional metadata as JSON', verbose_name='Metadata')),
                ('body_processors', django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Body processors')),
                ('first_document_processors', django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='First document PDF processors')),
                ('attachment_processors', django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Attachment processors')),
                ('position', models.PositiveIntegerField(help_text='Launch order inside the campaign. Lower numbers run first.', verbose_name='Position')),
                ('label', models.CharField(blank=True, default='', help_text='Name of this step in the campaign.', max_length=255, verbose_name='Label')),
                ('missive_type', models.CharField(choices=[('letter', 'Simple letter'), ('registered_letter', 'Registered letter'), ('hand_delivery', 'Hand delivery'), ('ere', 'Electronic registered email (ERE)'), ('email', 'Email'), ('email_marketing', 'Marketing email'), ('sms', 'SMS'), ('rcs', 'RCS (Rich SMS)'), ('voice_call', 'Automated voice call'), ('notification', 'In-app notification'), ('push_notification', 'Mobile push notification'), ('branded', 'Branded App messaging (WhatsApp, Slack, etc.)')], help_text='Channel this step sends on.', max_length=50, verbose_name='Missive type')),
                ('subject', models.TextField(blank=True, default='', help_text='Subject of this step. The campaign label is separate.', verbose_name='Subject')),
                ('acknowledgement', models.CharField(blank=True, choices=[('basic_delivery', 'Basic delivery'), ('acknowledgement_of_receipt', 'Acknowledgement of receipt')], max_length=50, null=True, verbose_name='Acknowledgement level')),
                ('delivery_mode', models.CharField(blank=True, choices=[('economic', 'Economic'), ('normal', 'Normal'), ('premium', 'Premium'), ('express', 'Express')], max_length=50, null=True, verbose_name='Delivery mode')),
                ('priority', models.CharField(blank=True, choices=[('low', 'Low'), ('normal', 'Normal'), ('high', 'High'), ('urgent', 'Urgent')], max_length=20, null=True, verbose_name='Priority')),
                ('duplex_printing', models.BooleanField(blank=True, default=None, help_text='Empty inherits the campaign value.', null=True, verbose_name='Duplex printing')),
                ('color_printing', models.BooleanField(blank=True, default=None, help_text='Empty inherits the campaign value.', null=True, verbose_name='Color printing')),
                ('sender_name', models.CharField(blank=True, max_length=255, null=True, verbose_name='Sender name')),
                ('sender_email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='Sender email')),
                ('sender_phone', phonenumber_field.modelfields.PhoneNumberField(blank=True, max_length=128, null=True, region=None, verbose_name='Sender phone')),
                ('sender_address', django_geoaddress.fields.GeoaddressField(blank=True, null=True, verbose_name='Sender address')),
                ('reply_to_name', models.CharField(blank=True, max_length=255, null=True, verbose_name='Reply-To name')),
                ('reply_to_email', models.EmailField(blank=True, max_length=254, null=True, verbose_name='Reply-To email')),
                ('reply_to_address', django_geoaddress.fields.GeoaddressField(blank=True, max_length=512, null=True, verbose_name='Reply-To address')),
                ('brand_name', models.CharField(blank=True, max_length=50, null=True, verbose_name='Brand name')),
                ('body_text', models.TextField(blank=True, default='', verbose_name='Plain text body')),
                ('body_rich', django_pymissive.fields.RichTextField(blank=True, default='', verbose_name='Rich body')),
                ('body_rich_snapshot_html', django_pymissive.fields.RichTextField(blank=True, default='', verbose_name='Rich body HTML snapshot')),
                ('build_target_processors', django_pymissive.fields.JSONField(blank=True, default=list, help_text="Chain that builds a target's missive for this step. When non-empty, it replaces the campaign chain. A target or a run with its own chain still wins.", verbose_name='Build target processors')),
            ],
            options={
                'verbose_name': 'Campaign step',
                'verbose_name_plural': 'Campaign steps',
                'ordering': ['campaign', 'position', 'pk'],
            },
        ),
        migrations.RemoveConstraint(
            model_name='campaigntarget',
            name='uniq_campaigntarget_pending',
        ),
        migrations.AlterField(
            model_name='missivecampaign',
            name='named_id',
            field=namedid.fields.NamedIDField(blank=False, generator='django_pymissive.generators.campaign_named_id', help_text='Unique identifier generated from the campaign label', max_length=255, null=False, source_fields=['subject'], unique=True, verbose_name='Named ID'),
        ),
        migrations.AlterField(
            model_name='missivecampaign',
            name='subject',
            field=models.TextField(help_text='Campaign label. The subject of each message lives on its step.', verbose_name='Label'),
        ),
        migrations.AddField(
            model_name='campaignstep',
            name='campaign',
            field=models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='to_campaignstep', to='django_pymissive.missivecampaign', verbose_name='Campaign'),
        ),
        migrations.CreateModel(
            name='BrandedCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Branded campaign step',
                'verbose_name_plural': 'Branded campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('django_pymissive.campaignstep',),
        ),
        migrations.CreateModel(
            name='EmailCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Email campaign step',
                'verbose_name_plural': 'Email campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('django_pymissive.campaignstep',),
        ),
        migrations.CreateModel(
            name='PhoneCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Phone campaign step',
                'verbose_name_plural': 'Phone campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('django_pymissive.campaignstep',),
        ),
        migrations.CreateModel(
            name='PostalCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Postal campaign step',
                'verbose_name_plural': 'Postal campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=('django_pymissive.campaignstep',),
        ),
        migrations.AddField(
            model_name='campaigntarget',
            name='campaign_step',
            field=models.ForeignKey(blank=True, help_text='Step this target is selected on. Empty on a campaign that still selects by missive type.', null=True, on_delete=django.db.models.deletion.CASCADE, related_name='to_campaigntarget', to='django_pymissive.campaignstep', verbose_name='Campaign step'),
        ),
        migrations.AddField(
            model_name='missive',
            name='campaign_step',
            field=models.ForeignKey(blank=True, help_text='Step this missive was built from. Empty for standalone missives.', null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='to_missive', to='django_pymissive.campaignstep', verbose_name='Campaign step'),
        ),
        migrations.AddField(
            model_name='missivebaseattachment',
            name='campaign_step',
            field=models.ManyToManyField(blank=True, help_text='Campaign steps that use this file. Empty makes it available to every step.', related_name='attachments', to='django_pymissive.campaignstep', verbose_name='Campaign steps'),
        ),
        migrations.AddIndex(
            model_name='missive',
            index=models.Index(fields=['campaign_step', 'thread_type', 'status'], name='django_pymi_campaig_079459_idx'),
        ),
        migrations.AddConstraint(
            model_name='campaigntarget',
            constraint=models.UniqueConstraint(condition=models.Q(('abandoned_at__isnull', True), ('campaign_step__isnull', True), ('missive__isnull', True)), fields=('campaign', 'content_type', 'object_id', 'missive_type'), name='uniq_campaigntarget_pending'),
        ),
        migrations.AddConstraint(
            model_name='campaigntarget',
            constraint=models.UniqueConstraint(condition=models.Q(('abandoned_at__isnull', True), ('campaign_step__isnull', False), ('missive__isnull', True)), fields=('campaign', 'content_type', 'object_id', 'campaign_step'), name='uniq_campaigntarget_pending_step'),
        ),
        migrations.AddConstraint(
            model_name='campaignstep',
            constraint=models.UniqueConstraint(fields=('campaign', 'position'), name='uniq_campaign_step_position'),
        ),
        migrations.AlterField(
            model_name='missive',
            name='attachment_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Attachment processors'),
        ),
        migrations.AlterField(
            model_name='missive',
            name='body_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Body processors'),
        ),
        migrations.AlterField(
            model_name='missive',
            name='first_document_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='First document PDF processors'),
        ),
        migrations.AlterField(
            model_name='missivecampaign',
            name='attachment_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Attachment processors'),
        ),
        migrations.AlterField(
            model_name='missivecampaign',
            name='body_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='Body processors'),
        ),
        migrations.AlterField(
            model_name='missivecampaign',
            name='first_document_processors',
            field=django_pymissive.fields.JSONField(blank=True, default=list, help_text='Ordered list of processors. When non-empty, REPLACES inherited defaults. Runtime resolution (first non-empty wins): this object\'s value, then its campaign step and campaign values (when linked), then the global setting. Each entry may be a dotted-path string, a ``[path, kwargs]`` pair, or a ``{"processor": path, "kwargs": {...}}`` dict. When overriding the body chain, include ``django_pymissive.processors.body.django_template.django_template_processor`` if you still want ``{{ var }}`` / ``{% tag %}`` rendering; when overriding the first_document chain, include ``django_pymissive.processors.pdf.weasyprint_renderer.weasyprint_renderer`` (or your own renderer) as the first entry.', verbose_name='First document PDF processors'),
        ),
        migrations.RunPython(forwards, backwards),

        migrations.RemoveIndex(
            model_name='missive',
            name='django_pymi_campaig_88fa43_idx',
        ),
        migrations.RemoveField(
            model_name='missive',
            name='campaign',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='acknowledgement_email',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='acknowledgement_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='color_printing_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='color_printing_registered_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='delivery_mode_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='duplex_printing_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='duplex_printing_registered_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='email_body_rich',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='email_body_rich_snapshot_html',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='email_body_text',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='first_document',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='first_document_snapshot_html',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='phone_body_rich',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='phone_body_rich_snapshot_html',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='phone_body_text',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='priority_letter',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='reply_to_address',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='reply_to_address_name',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='reply_to_email',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='reply_to_email_name',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_address',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_address_name',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_email',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_email_name',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_phone',
        ),
        migrations.RemoveField(
            model_name='missivecampaign',
            name='sender_phone_name',
        ),
        migrations.DeleteModel(
            name='PhoneCampaignStep',
        ),
        migrations.DeleteModel(
            name='PostalCampaignStep',
        ),
        migrations.CreateModel(
            name='EmailMarketingCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Marketing email campaign step',
                'verbose_name_plural': 'Marketing email campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='EreCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Electronic registered email campaign step',
                'verbose_name_plural': 'Electronic registered email campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='HandDeliveryCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Hand delivery campaign step',
                'verbose_name_plural': 'Hand delivery campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.PostalCampaignStepMixin, django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='LetterCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Letter campaign step',
                'verbose_name_plural': 'Letter campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.PostalCampaignStepMixin, django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='NotificationCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Notification campaign step',
                'verbose_name_plural': 'Notification campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='PushNotificationCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Push notification campaign step',
                'verbose_name_plural': 'Push notification campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='RcsCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'RCS campaign step',
                'verbose_name_plural': 'RCS campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='RegisteredLetterCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Registered letter campaign step',
                'verbose_name_plural': 'Registered letter campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.PostalCampaignStepMixin, django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='SmsCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'SMS campaign step',
                'verbose_name_plural': 'SMS campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.CreateModel(
            name='VoiceCallCampaignStep',
            fields=[
            ],
            options={
                'verbose_name': 'Voice call campaign step',
                'verbose_name_plural': 'Voice call campaign steps',
                'proxy': True,
                'indexes': [],
                'constraints': [],
            },
            bases=(django_pymissive.models.campaign_step.TypedCampaignStepMixin, 'django_pymissive.campaignstep'),
        ),
        migrations.AddField(
            model_name="missive",
            name="send_speed",
            field=models.FloatField(
                blank=True,
                editable=False,
                help_text="Seconds spent sending this missive.",
                null=True,
                verbose_name="Send speed",
            ),
        ),
        migrations.AlterField(
            model_name="missivescheduledcampaign",
            name="average_send_speed",
            field=models.FloatField(
                blank=True,
                editable=False,
                help_text=(
                    "Wall-clock seconds per missive sent, from this run's send date to its end. "
                    "Stored when the run ends. Parallel sends make it differ from the mean "
                    "of each missive's own send speed."
                ),
                null=True,
                verbose_name="Average speed per send",
            ),
        ),
        migrations.AlterField(
            model_name="missiveconfig",
            name="default_provider",
            field=django_providerkit.fields.ProviderField(
                blank=True,
                help_text="Provider name. Leave empty for no default.",
                max_length=100,
                verbose_name="Default provider",
            ),
        ),
        migrations.AddField(
            model_name="missivescheduledcampaign",
            name="campaign_steps",
            field=models.ManyToManyField(
                blank=True,
                help_text="Steps sent by this run. Leave empty to send every step in the campaign.",
                related_name="to_scheduled_campaign",
                to="django_pymissive.campaignstep",
                verbose_name="Campaign steps",
            ),
        ),
        migrations.RunPython(
            prepare_step_relations,
            restore_legacy_scope_fields,
        ),
        migrations.RemoveConstraint(
            model_name="campaigntarget",
            name="uniq_campaigntarget_pending",
        ),
        migrations.RemoveConstraint(
            model_name="campaigntarget",
            name="uniq_campaigntarget_pending_step",
        ),
        migrations.RemoveIndex(
            model_name="campaigntarget",
            name="campaigntarget_camp_type",
        ),
        migrations.AlterField(
            model_name="campaigntarget",
            name="campaign_step",
            field=models.ForeignKey(
                help_text="Step this target is selected on.",
                on_delete=django.db.models.deletion.CASCADE,
                related_name="to_campaigntarget",
                to="django_pymissive.campaignstep",
                verbose_name="Campaign step",
            ),
        ),
        migrations.AlterField(
            model_name="campaigntarget",
            name="missive_type",
            field=models.CharField(
                choices=[
                    ("letter", "Simple letter"),
                    ("registered_letter", "Registered letter"),
                    ("hand_delivery", "Hand delivery"),
                    ("ere", "Electronic registered email (ERE)"),
                    ("email", "Email"),
                    ("email_marketing", "Marketing email"),
                    ("sms", "SMS"),
                    ("rcs", "RCS (Rich SMS)"),
                    ("voice_call", "Automated voice call"),
                    ("notification", "In-app notification"),
                    ("push_notification", "Mobile push notification"),
                    ("branded", "Branded App messaging (WhatsApp, Slack, etc.)"),
                ],
                default="",
                help_text="Channel this target is selected on (email, sms, letter, …).",
                max_length=50,
                verbose_name="Missive type",
            ),
        ),
        migrations.RemoveField(
            model_name="campaigntarget",
            name="missive_type",
        ),
        migrations.AddIndex(
            model_name="campaigntarget",
            index=models.Index(
                fields=["campaign", "campaign_step"],
                name="campaigntarget_camp_step",
            ),
        ),
        migrations.AddConstraint(
            model_name="campaigntarget",
            constraint=models.UniqueConstraint(
                condition=models.Q(
                    ("abandoned_at__isnull", True),
                    ("missive__isnull", True),
                ),
                fields=("campaign", "content_type", "object_id", "campaign_step"),
                name="uniq_campaigntarget_pending_step",
            ),
        ),
        migrations.RemoveField(
            model_name="missivescheduledcampaign",
            name="missive_type",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="acknowledgement",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="delivery_mode",
        ),
        migrations.RemoveField(
            model_name="campaignstep",
            name="priority",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="acknowledgement",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="delivery_mode",
        ),
        migrations.RemoveField(
            model_name="missive",
            name="priority",
        ),
    ]
