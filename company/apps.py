from django.apps import AppConfig


class CompanyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'company'
    def ready(self):
        from django.urls import include, path

        from horilla.horilla_settings import APP_URLS, APPS
        from horilla.urls import urlpatterns

        # APPS.append("company")
        print("the flow is coming here")
        urlpatterns.append(
            path("company/", include("company.urls")),
        )
        # APP_URLS.append("company.urls")
        super().ready()