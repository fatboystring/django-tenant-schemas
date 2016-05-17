import django
from django.conf import settings
from django.db import models, connection
from django.core.management import call_command

from django.utils.encoding import python_2_unicode_compatible
from tenant_schemas.postgresql_backend.base import _check_schema_name
from tenant_schemas.signals import post_schema_sync
from tenant_schemas.utils import django_is_in_test_mode, schema_exists
from tenant_schemas.utils import get_public_schema_name


@python_2_unicode_compatible
class Domain(models.Model):
    tenant = models.ForeignKey("tenant_schemas.Tenant",
                               related_name='domains')
    domain = models.CharField(max_length=128, unique=True)

    def __str__(self):
        return self.domain

    def save(self, *args, **kwargs):
        self.domain = self.domain.lower()
        super(Domain, self).save(*args, **kwargs)


@python_2_unicode_compatible
class Tenant(models.Model):
    """
    All tenant models must inherit this class.
    """

    auto_drop_schema = False
    """
    USE THIS WITH CAUTION!
    Set this flag to true on a parent class if you want the schema to be
    automatically deleted if the tenant row gets deleted.
    """

    auto_create_schema = True
    """
    Set this flag to false on a parent class if you don't want the schema
    to be automatically created upon save.
    """

    schema_name = models.CharField(max_length=63,
                                   unique=True,
                                   validators=[_check_schema_name])

    name = models.CharField(max_length=100)
    created_on = models.DateField(auto_now_add=True)

    def __str__(self):
        return self.name

    def get_domains(self):
        """ Return list of domains for tenant """
        return [d.domain for d in self.domains.all()]

    @classmethod
    def get_public(cls):
        """ Return public tenant """
        return cls.objects.get(schema_name=settings.PUBLIC_SCHEMA_NAME)

    @classmethod
    def get_for_domain(cls, domain):
        """ Get tenant for domain """
        result = Domain.objects.filter(domain=domain.lower())
        if result:
            return result[0].tenant

        return cls.get_public()

    def add_domain(self, domain):
        """ Add specific domain for tenant """
        domain = domain.lower()
        obj, created = Domain.objects.get_or_create(tenant=self, domain=domain)
        return obj

    def remove_domain(self, domain):
        domain = domain.lower()
        return Domain.objects.filter(tenant=self, domain=domain).delete()

    def save(self, verbosity=1, *args, **kwargs):
        is_new = self.pk is None

        if is_new and connection.schema_name != get_public_schema_name():
            raise Exception("Can't create tenant outside the public schema. "
                            "Current schema is %s." % connection.schema_name)
        elif not is_new and connection.schema_name not in (self.schema_name, get_public_schema_name()):
            raise Exception("Can't update tenant outside it's own schema or "
                            "the public schema. Current schema is %s."
                            % connection.schema_name)

        super(Tenant, self).save(*args, **kwargs)

        if is_new and self.auto_create_schema:
            try:
                self.create_schema(check_if_exists=True, verbosity=verbosity)
                post_schema_sync.send(sender=Tenant, tenant=self)
            except:
                # We failed creating the tenant, delete what we created and
                # re-raise the exception
                self.delete(force_drop=True)
                raise

    def delete(self, force_drop=False, *args, **kwargs):
        """
        Deletes this row. Drops the tenant's schema if the attribute
        auto_drop_schema set to True.
        """
        if connection.schema_name not in (self.schema_name, get_public_schema_name()):
            raise Exception("Can't delete tenant outside it's own schema or "
                            "the public schema. Current schema is %s."
                            % connection.schema_name)

        if schema_exists(self.schema_name) and (self.auto_drop_schema or force_drop):
            cursor = connection.cursor()
            cursor.execute('DROP SCHEMA %s CASCADE' % self.schema_name)

        super(Tenant, self).delete(*args, **kwargs)

    def create_schema(self, check_if_exists=False, sync_schema=True,
                      verbosity=1):
        """
        Creates the schema 'schema_name' for this tenant. Optionally checks if
        the schema already exists before creating it. Returns true if the
        schema was created, false otherwise.
        """

        # safety check
        _check_schema_name(self.schema_name)
        cursor = connection.cursor()

        if check_if_exists and schema_exists(self.schema_name):
            return False

        # create the schema
        cursor.execute('CREATE SCHEMA %s' % self.schema_name)

        if sync_schema:
            call_command('migrate_schemas',
                         schema_name=self.schema_name,
                         interactive=False,
                         verbosity=verbosity)

        connection.set_schema_to_public()
