from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from django.forms import formset_factory
from django.utils import timezone
from .models import Worker, PayrollSettings, SprayProduct, SprayApplication

DATE = {'type': 'date'}


class RevisionForm(forms.ModelForm):
    revision = forms.IntegerField(widget=forms.HiddenInput, initial=0)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields['revision'].initial = self.instance.revision


class WorkerForm(RevisionForm):
    class Meta:
        model = Worker
        fields = ['name', 'identification', 'occupation', 'joined_on', 'daily_rate', 'active', 'notes']
        widgets = {'joined_on': forms.DateInput(attrs=DATE, format='%Y-%m-%d')}


class SettingsForm(RevisionForm):
    class Meta:
        model = PayrollSettings
        fields = ['mode', 'hourly_rate', 'ordinary_hours', 'multiplier']

    def clean(self):
        d = super().clean()
        if d.get('mode') == 'hourly' and d.get('hourly_rate') is None:
            self.add_error('hourly_rate', 'Defina la tarifa, incluso si es cero.')
        if d.get('mode') == 'derived' and (not d.get('ordinary_hours') or d.get('multiplier') is None):
            raise ValidationError('Defina las horas ordinarias y el factor; no se suponen recargos.')
        return d


class PeriodForm(forms.Form):
    start = forms.DateField(label='Fecha inicial', widget=forms.DateInput(attrs=DATE))
    end = forms.DateField(label='Fecha final', widget=forms.DateInput(attrs=DATE))
    token = forms.UUIDField(widget=forms.HiddenInput)

    def clean(self):
        d = super().clean()
        if d.get('start') and d.get('end') and d['start'] > d['end']:
            raise ValidationError('La fecha final debe ser igual o posterior a la inicial.')
        if d.get('end') and d['end'] > timezone.localdate():
            raise ValidationError('No se puede liquidar asistencia futura.')
        return d


class AttendanceRow(forms.Form):
    worker = forms.IntegerField(widget=forms.HiddenInput)
    revision = forms.IntegerField(widget=forms.HiddenInput, initial=0)
    worked = forms.BooleanField(label='Trabajó', required=False)
    hours = forms.IntegerField(label='Horas extras', min_value=0, max_value=24, initial=0)
    minutes = forms.IntegerField(label='Minutos extras', min_value=0, max_value=1440, initial=0)
    notes = forms.CharField(label='Observaciones', required=False, max_length=2000)

    def clean(self):
        d = super().clean()
        n = (d.get('hours') or 0) * 60 + (d.get('minutes') or 0)
        if n > 1440:
            raise ValidationError('El tiempo extra no puede superar 24 horas por día.')
        if n and not d.get('worked'):
            raise ValidationError('No registre extras en un día no trabajado.')
        return d


AttendanceRows = formset_factory(AttendanceRow, extra=0, max_num=1000, validate_max=True)


class SprayProductForm(RevisionForm):
    class Meta:
        model = SprayProduct
        fields = ['name', 'ingredient', 'category', 'unit', 'interval_days', 'interval_source', 'notes', 'active']

    def clean(self):
        d = super().clean()
        if d.get('interval_days') and not d.get('interval_source'):
            self.add_error('interval_source', 'Indique la fuente técnica o el responsable agrícola.')
        return d


class SprayForm(RevisionForm):
    next_at = forms.DateTimeField(label='Próxima aplicación (opcional, revisar antes de guardar)', required=False, widget=forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'))
    token = forms.UUIDField(widget=forms.HiddenInput)

    class Meta:
        model = SprayApplication
        fields = ['scheduled_at', 'area', 'responsible', 'status', 'notes']
        widgets = {'scheduled_at': forms.DateTimeInput(attrs={'type': 'datetime-local'}, format='%Y-%m-%dT%H:%M'), 'notes': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['status'].choices = [('scheduled', 'Programada'), ('completed', 'Realizada')]

    def clean(self):
        d = super().clean()
        when = d.get('scheduled_at')
        if when and d.get('status') == 'completed' and when > timezone.now():
            self.add_error('scheduled_at', 'Una aplicación futura debe guardarse como programada.')
        if d.get('next_at') and when and d['next_at'] <= when:
            self.add_error('next_at', 'La próxima fecha debe ser posterior a esta aplicación.')
        return d


class SprayRow(forms.Form):
    product = forms.ModelChoiceField(label='Producto', queryset=SprayProduct.objects.filter(active=True))
    quantity = forms.DecimalField(label='Cantidad', max_digits=14, decimal_places=3, min_value=Decimal('.001'))
    unit = forms.CharField(label='Unidad', max_length=60)


SprayRows = formset_factory(SprayRow, extra=3, max_num=100, validate_max=True, min_num=1, validate_min=True, can_delete=True)
