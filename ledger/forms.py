from django import forms
from django.core.exceptions import ValidationError
from django.db.models import Q
from .models import Customer, Product, ExpenseCategory, Expense, PaymentMethod
class CustomerForm(forms.ModelForm):
    class Meta:
        model=Customer
        fields=['name','identification','phone','address','email','notes','active']
class ProductForm(forms.ModelForm):
    class Meta:
        model=Product
        fields=['name','code','price','unit','by_weight','variable_weight','weight','active']
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['weight'].required=False
    def clean(self):
        d=super().clean()
        if not d.get('by_weight'):
            d['variable_weight']=False
            d['weight']=0
        elif d.get('variable_weight'):
            d['weight']=0
        if d.get('by_weight') and not d.get('variable_weight') and (d.get('weight') or 0)<=0: self.add_error('weight','Ingrese un peso fijo mayor que cero o seleccione peso variable.')
        return d
class CategoryForm(forms.ModelForm):
    class Meta:
        model=ExpenseCategory
        fields=['name','description','active']
class MethodForm(forms.ModelForm):
    class Meta:
        model=PaymentMethod
        fields=['name','active','is_credit']
class ExpenseForm(forms.ModelForm):
    revision=forms.IntegerField(widget=forms.HiddenInput,initial=0)
    class Meta:
        model=Expense
        fields=['date','category','description','amount','method']
        widgets={'date':forms.DateInput(attrs={'type':'date'},format='%Y-%m-%d')}
    def __init__(self,*args,**kwargs):
        super().__init__(*args,**kwargs)
        self.fields['category'].queryset=ExpenseCategory.objects.filter(Q(active=True)|Q(pk=self.instance.category_id))
        self.fields['method'].queryset=PaymentMethod.objects.filter(Q(active=True,is_credit=False)|Q(pk=self.instance.method_id))
        if self.instance.pk: self.fields['revision'].initial=self.instance.revision
