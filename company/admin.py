from django.contrib import admin

from base.models import CompanyAccessControl


@admin.register(CompanyAccessControl)
class CompanyAccessControlAdmin(admin.ModelAdmin):
    list_display = ("user", "company_list")
    search_fields = ("user__username", "user__email")
    filter_horizontal = ("companies",)

    def company_list(self, obj):
        return ", ".join(obj.companies.values_list("company", flat=True))

    company_list.short_description = "Companies"
