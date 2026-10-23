from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q
class EmailBackend(ModelBackend):
    def authenticate(self,request,username=None,password=None,**kwargs):
        users=get_user_model().objects.filter(Q(username__iexact=username)|Q(email__iexact=username))
        if users.count()!=1:
            get_user_model()().set_password(password)
            return None
        user=users.first()
        if user.check_password(password) and self.user_can_authenticate(user): return user
