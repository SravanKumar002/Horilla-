from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from rest_framework.authtoken.models import Token
from django.contrib.auth import authenticate

class LoginAPI(APIView):
    permission_classes = [AllowAny]  # ✅ public (no token required)

    def post(self, request):
        username = request.data.get("username")
        password = request.data.get("password")

        # Authenticate user
        user = authenticate(username=username, password=password)
        if user is not None:
            token, _ = Token.objects.get_or_create(user=user)
            return Response({
                "token": token.key,
                "username": user.username
            })
        else:
            return Response({"error": "Invalid credentials"}, status=400)

class LoginTest(APIView):
    permission_classes = [AllowAny]  # ✅ public (no token required)

    def get(self, request):
        return Response({"message": "Login test endpoint is working!"})