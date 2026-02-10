from django.urls import path
from company import views


urlpatterns = [
    path('', views.company_index, name='company_index'),
]
