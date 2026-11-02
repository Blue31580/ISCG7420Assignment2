from multiprocessing.reduction import duplicate

from django.contrib.auth.models import User
from rest_framework import serializers
from django.utils import timezone

from tools.models import Appointment, Appointment_Slot, Doctor

def get_role(user):
    if user.is_staff:
        return 'admin'
    if hasattr(user, 'doctor_profile'):
        return 'doctor'
    return 'patient'

class UserSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'role']

        def get_role(self, obj):
            return get_role(obj)

class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ['username', 'email', 'first_name', 'last_name', 'password']

        def create(self, validated_data):
            return User.objects.create_user(**validated_data)

class UserAdminSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8, required=False)
    role = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = ['id', 'username', 'email', 'first_name', 'last_name', 'password', 'is_active', 'is_staff',  'role']

    def get_role(self, obj):
        return get_role(obj)

    def create(self, validated_data):
        password = validated_data.pop('password', None)
        if not password:
            raise serializers.ValidationError({'password': 'Password is required'})
        return User.objects.create_superuser(**validated_data, password=password)

    def update(self, instance, validated_data):
        password = validated_data.pop('password', None)
        user = super().update(instance, validated_data)
        if password:
            user.set_password(password)
            user.save()
        return user

class DoctorSerializer(serializers.ModelSerializer):
    name = serializers.ReadOnlyField()
    username = serializers.ReadOnlyField(source='user.username')

    class Meta:
        model = Doctor
        fields = ['id', 'user', 'username', 'name' ,'specialization', 'room_number', 'bio', 'profile_image', 'consultation_fee']

class AppointmentSlotSerializer(serializers.ModelSerializer):
    doctor_name = serializers.ReadOnlyField(source='doctor.name')

    class Meta:
        model = Appointment_Slot
        fields = ['id', 'doctor', 'doctor_name', 'appointment_date', 'appointment_time', 'appointment_end_time', 'is_booked']
        read_only_fields = ['is_booked']
        extra_kwargs = {'doctor': {'required': False}}
        validators = []

    def validate(self, attrs):
        request = self.context['request']
        user = request.user

        if not user.is_staff and not hasattr(user, 'doctor_profile'):
            attrs['doctor'] = user.doctor_profile
        doctor = attrs.get('doctor') or (self.instance.doctor if self.instance else None)
        if doctor is None:
            raise serializers.ValidationError({'doctor': 'Doctor is required'})
        attrs['doctor'] = doctor

        date = attrs.get('appointment_date', getattr(self.instance, 'appointment_date', None))
        start = attrs.get('appointment_time', getattr(self.instance, 'appointment_time', None))
        end = attrs.get('appointment_end_time', getattr(self.instance, 'appointment_end_time', None))

        if end <= start:
            raise serializers.ValidationError({'appointment_end_time': 'End time must be after start time'})
        if date < timezone.localtime().date():
            raise serializers.ValidationError({'appointment_date': 'Date must be in the future'})

        if self.instance and self.instance.is_booked:
            changed = (date != self.instance.appointment_date or start != self.instance.appointment_time
                       or end != self.instance.appointment_end_time or doctor != self.instance.doctor)
            if changed:
                raise serializers.ValidationError('This slot is booked. Cancel the appointment before changing it.')

        duplicate = Appointment_Slot.objects.filter(
            doctor=doctor,
            appointment_date=date,
            appointment_time__gte=start)

        if self.instance:
            duplicate = duplicate.exclude(pk=self.instance.pk)
        if duplicate.exists():
            raise serializers.ValidationError('This slot is already booked.')
        return attrs

class AppointmentSerializer(serializers.ModelSerializer):
    patient_username = serializers.ReadOnlyField(source='patient.username')
    doctor_username = serializers.ReadOnlyField(source='doctor.user.username')
    slot_date = serializers.ReadOnlyField(source='slot.appointment_date')
    slot_start = serializers.ReadOnlyField(source='slot.appointment_time')
    slot_end = serializers.ReadOnlyField(source='slot.appointment_end_time')

    class Meta:
        model = Appointment
        fields = ['id', 'patient', 'patient_username', 'slot', 'doctor_name',
                  'slot_date', 'slot_start', 'slot_end',
                  'appointment_status', 'appointment_details', 'appointment_date_time']
        read_only_fields = ['patient', 'appointment_status']

    def validate_slot(self, slot):
        is_own_slot = self.instance is not None and slot.pk == self.instance.slot_id
        if not is_own_slot:
            if slot.is_booked:
                raise serializers.ValidationError('This slot is already booked.')
            if slot.appointment_date < timezone.localtime().date():
                raise serializers.ValidationError('This slot is in the past.')
        return slot

    def validate(self, attrs):
        if not self.context['request'].user.is_staff:
            attrs.pop('appointment_status', None)
        return attrs