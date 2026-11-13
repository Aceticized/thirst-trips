from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("locations", "0002_fountain_delete_facility")]

    operations = [migrations.RenameModel(old_name="Fountain", new_name="Facility")]
