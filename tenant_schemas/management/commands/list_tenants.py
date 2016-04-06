import csv
import sys

from django.core.management import BaseCommand
from tenant_schemas.utils import get_tenant_model


class Command(BaseCommand):
    def handle(self, *args, **options):

        model = get_tenant_model()
        all_tenants = [(t.schema_name, ', '.join(t.get_domains()))
                       for t
                       in model.objects.all()]

        out = csv.writer(sys.stdout, dialect=csv.excel_tab)
        for tenant in all_tenants:
            out.writerow(tenant)
