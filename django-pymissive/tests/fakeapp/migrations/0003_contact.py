from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("fakeapp", "0002_pdfdocument_published_at"),
    ]

    operations = [
        migrations.CreateModel(
            name="Contact",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("last_name", models.CharField(max_length=120)),
                ("first_name", models.CharField(max_length=120)),
                ("email", models.EmailField(max_length=254, unique=True)),
            ],
            options={
                "verbose_name": "Contact (test fixture)",
                "ordering": ["last_name", "first_name"],
            },
        ),
    ]
