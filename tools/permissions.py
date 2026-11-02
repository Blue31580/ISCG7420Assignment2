from rest_framework import permissions


class IsAdminStaff(permissions.BasePermission):
    def has_permission(self, request, view):
        return bool(request.user and request.user.is_authenticated and request.user.is_staff)


class IsStaffOrDoctor(permissions.BasePermission):
    def has_permission(self, request, view):
        user = request.user
        return bool(user and user.is_authenticated and (user.is_staff or hasattr(user, 'doctor_profile')))


class IsSlotOwnerOrStaff(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        if request.user.is_staff:
            return True
        return hasattr(request.user, 'doctor_profile') and obj.doctor_id == request.user.doctor_profile.id


class IsAppointmentOwnerOrStaff(permissions.BasePermission):
    def has_object_permission(self, request, view, obj):
        user = request.user
        if user.is_staff:
            return True
        if request.method in permissions.SAFE_METHODS:
            is_slot_doctor = hasattr(user, 'doctor_profile') and obj.slot.doctor_id == user.doctor_profile.id
            return obj.patient_id == user.id or is_slot_doctor
        return obj.patient_id == user.id