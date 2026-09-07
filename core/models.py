from django.db import models
from django.conf import settings
from django.contrib.auth.models import Permission

class Lookup(models.Model):
    name = models.CharField(max_length=100)
    value = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'lookups'

    def __str__(self):
        return f"{self.name} - {self.value}"

class Role(models.Model):
    role_name = models.CharField(max_length=100, unique=True)
    permissions = models.ManyToManyField(Permission, blank=True, related_name='custom_roles')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'roles'

    def __str__(self):
        return self.role_name

class AuditLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    method = models.CharField(max_length=20)
    endpoint = models.CharField(max_length=255)
    status_code = models.IntegerField(null=True, blank=True)
    ip = models.CharField(max_length=50, null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'audit_logs'


class CompanyProfile(models.Model):
    """
    The selling entity's own identity: what goes on the letterhead of every
    invoice, bill and report the frontend prints.

    Treated as a singleton — one active row. Nothing in the system knew the
    company's own name before this, so printed documents had nowhere to get it.
    """
    name = models.CharField(max_length=255, help_text="Trading name shown on documents")
    legal_name = models.CharField(max_length=255, null=True, blank=True)
    address = models.TextField()
    city = models.CharField(max_length=100, null=True, blank=True)
    postal_code = models.CharField(max_length=20, null=True, blank=True)
    country = models.CharField(max_length=100, default='Bangladesh')

    phone = models.CharField(max_length=50, null=True, blank=True)
    alternative_phone = models.CharField(max_length=50, null=True, blank=True)
    email = models.EmailField(max_length=255, null=True, blank=True)
    website_url = models.URLField(max_length=255, null=True, blank=True)
    logo_url = models.URLField(max_length=500, null=True, blank=True)

    # Bangladesh NBR and DGDA identifiers printed on a pharmaceutical invoice
    business_identification_number = models.CharField(
        max_length=50, null=True, blank=True,
        verbose_name="BIN (13-digit VAT registration)"
    )
    tax_identification_number = models.CharField(
        max_length=50, null=True, blank=True, verbose_name="TIN / e-TIN"
    )
    drug_license_number = models.CharField(max_length=100, null=True, blank=True)
    drug_license_expiry_date = models.DateField(null=True, blank=True)
    trade_license_number = models.CharField(max_length=100, null=True, blank=True)

    default_currency = models.CharField(max_length=10, default='BDT')
    invoice_footer_note = models.TextField(
        null=True, blank=True,
        help_text="Terms or thank-you note printed at the foot of every invoice"
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'company_profiles'
        ordering = ['-is_active', '-id']
        verbose_name = "Company Profile"
        verbose_name_plural = "Company Profile"

    def __str__(self):
        return f"{self.name}{'' if self.is_active else ' (inactive)'}"

    @classmethod
    def get_active(cls):
        """The profile documents should print. None if nobody has set one up."""
        return cls.objects.filter(is_active=True).order_by('-id').first()

    def save(self, *args, **kwargs):
        # One active profile at a time, so a document can never be ambiguous
        # about who issued it.
        if self.is_active:
            CompanyProfile.objects.exclude(pk=self.pk).update(is_active=False)
        super().save(*args, **kwargs)
