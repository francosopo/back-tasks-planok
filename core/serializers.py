from rest_framework import serializers
from .models import Task

class TaskSerializer(serializers.ModelSerializer):
    # Campos de solo lectura para mostrar las etiquetas legibles de los Enums
    status_display = serializers.CharField(source='get_status_display', read_only=True)
    priority_display = serializers.CharField(source='get_priority_display', read_only=True)

    class Meta:
        model = Task
        fields = [
            'id', 
            'title', 
            'description', 
            'status', 
            'priority', 
            'status_display', 
            'priority_display', 
            'created_at', 
            'updated_at'
        ]