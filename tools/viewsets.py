from django.contrib.auth.models import User
from django.db import IntegrityError, transaction
from django.db.models import Q
from django_filters.rest_framework import DjangoFilterBackend
from rest_framework import permissions, serializers, viewsets

from tools.models import Appointment, Appointment_Slot, Doctor
from tools.permissions import (IsAdminStaff, IsAppointmentOwnerOrStaff,
                               IsSlotOwnerOrStaff, IsStaffOrDoctor)
from tools.serializers import (AppointmentSerializer, AppointmentSlotSerializer,
                               DoctorSerializer, UserAdminSerializer)


class DoctorViewSet(viewsets.ModelViewSet):
    queryset = Doctor.objects.select_related('user')
    serializer_class = DoctorSerializer

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.AllowAny()]
        return [IsAdminStaff()]


class AppointmentSlotViewSet(viewsets.ModelViewSet):
    queryset = Appointment_Slot.objects.select_related('doctor__user')
    serializer_class = AppointmentSlotSerializer
    filter_backends = [DjangoFilterBackend]
    filterset_fields = ['doctor', 'appointment_date', 'is_booked']

    def get_permissions(self):
        if self.action in ('list', 'retrieve'):
            return [permissions.AllowAny()]
        return [IsStaffOrDoctor(), IsSlotOwnerOrStaff()]

    def perform_destroy(self, instance):
        if instance.is_booked:
            raise serializers.ValidationError('This slot is booked. Cancel the appointment first.')
        instance.delete()


class AppointmentViewSet(viewsets.ModelViewSet):
    serializer_class = AppointmentSerializer
    permission_classes = [permissions.IsAuthenticated, IsAppointmentOwnerOrStaff]

    def get_queryset(self):
        user = self.request.user
        qs = Appointment.objects.select_related('patient', 'slot__doctor__user')
        if user.is_staff:
            return qs
        if hasattr(user, 'doctor_profile'):
            return qs.filter(Q(slot__doctor=user.doctor_profile) | Q(patient=user))
        return qs.filter(patient=user)

    def perform_create(self, serializer):
        slot_id = serializer.validated_data['slot'].pk
        try:
            with transaction.atomic():
                # Lock the slot row so two patients can't book it at the same time.
                slot = Appointment_Slot.objects.select_for_update().get(pk=slot_id)
                if slot.is_booked:
                    raise serializers.ValidationError({'slot': 'This slot has already been booked.'})
                serializer.save(patient=self.request.user)
                slot.is_booked = True
                slot.save(update_fields=['is_booked'])
        except IntegrityError:
            raise serializers.ValidationError({'slot': 'This slot has already been booked.'})

    def perform_update(self, serializer):
        old_slot = serializer.instance.slot
        new_slot = serializer.validated_data.get('slot', old_slot)
        with transaction.atomic():
            if new_slot.pk != old_slot.pk:  # rescheduling to another slot
                new_slot = Appointment_Slot.objects.select_for_update().get(pk=new_slot.pk)
                if new_slot.is_booked:
                    raise serializers.ValidationError({'slot': 'This slot has already been booked.'})
                serializer.save()
                old_slot.is_booked = False
                old_slot.save(update_fields=['is_booked'])
                new_slot.is_booked = True
                new_slot.save(update_fields=['is_booked'])
            else:
                serializer.save()

    def perform_destroy(self, instance):
        # Cancelling frees the slot so someone else can book it.
        with transaction.atomic():
            slot = instance.slot
            instance.delete()
            slot.is_booked = False
            slot.save(update_fields=['is_booked'])


class UserViewSet(viewsets.ModelViewSet):
    """Admin dashboard: manage user accounts."""
    queryset = User.objects.all().order_by('id')
    serializer_class = UserAdminSerializer
    permission_classes = [IsAdminStaff]

    def perform_destroy(self, instance):
        if instance == self.request.user:
            raise serializers.ValidationError('You cannot delete your own account.')
        instance.delete()