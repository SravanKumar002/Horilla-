# middleware.py

import datetime
from django.conf import settings
from django.shortcuts import redirect

class ForceLogoutMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated:
            now = datetime.datetime.now()
            last_activity = request.session.get('last_activity')
            print("last_activity",last_activity)
            if last_activity:
                elapsed = (now - datetime.datetime.fromtimestamp(last_activity)).total_seconds()
                if elapsed > settings.SESSION_TIME_OUT:
                    from django.contrib.auth import logout
                    logout(request)
                    return redirect('/login/')

            # Update activity timestamp on each request
            request.session['last_activity'] = now.timestamp()

        response = self.get_response(request)
        return response
