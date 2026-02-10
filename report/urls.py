from django.urls import path
from django.http import HttpResponse

def under_construction_view(request):
    return render(request, "report/under_construction.html")

urlpatterns = [
    path("under-construction/", under_construction_view, name="under_construction"),
]
