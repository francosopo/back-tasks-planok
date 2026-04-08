from django.test import TestCase

# Create your tests here.

from django.urls import reverse
from rest_framework import status
from rest_framework.test import APITestCase
from .models import Task

class TaskAPITests(APITestCase):

    def setUp(self):
        # Creamos dos tareas iniciales para los tests de detalle (ID 1 y 2)
        self.task1 = Task.objects.create(
            title="Tarea 1", 
            description="Descripción 1", 
            priority="low"
        )
        self.task2 = Task.objects.create(
            title="Tarea 2", 
            description="Descripción 2", 
            priority="high"
        )
        self.url_list = "/tasks/"
        # Usamos f-strings para las URLs de detalle
        self.url_detail_1 = f"/tasks/{self.task1.id}/"
        self.url_detail_2 = f"/tasks/{self.task2.id}/"

    def test_get_all_tasks(self):
        """Valida que el listado devuelve ambas tareas"""
        response = self.client.get(self.url_list)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.data), 2)

    def test_get_specific_tasks(self):
        """Valida específicamente /tasks/1/ y /tasks/2/"""
        resp1 = self.client.get(self.url_detail_1)
        resp2 = self.client.get(self.url_detail_2)
        
        self.assertEqual(resp1.status_code, status.HTTP_200_OK)
        self.assertEqual(resp1.data['title'], "Tarea 1")
        
        self.assertEqual(resp2.status_code, status.HTTP_200_OK)
        self.assertEqual(resp2.data['title'], "Tarea 2")

    def test_create_task(self):
        """Valida el POST en /tasks/"""
        data = {
            "title": "Nueva Tarea",
            "description": "Prueba de creación",
            "priority": "urgent"
        }
        response = self.client.post(self.url_list, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(Task.objects.count(), 3)

    def test_update_task(self):
        """Valida el PUT en /tasks/<id>/"""
        data = {"title": "Tarea 1 Editada", "priority": "high"}
        # Usamos patch para edición parcial o put para total
        response = self.client.patch(self.url_detail_1, data, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.task1.refresh_from_db()
        self.assertEqual(self.task1.title, "Tarea 1 Editada")