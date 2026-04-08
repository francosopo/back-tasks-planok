# back-tasks-planok
docker build . -t api:tasks
docker-compose up 


curl -X GET http://127.0.0.1:8000/tasks/


curl -X POST http://127.0.0.1:8000/tasks/ \
     -H "Content-Type: application/json" \
     -d '{
        "title": "Aprender Langchain",
        "description": "Configurar el agente para la prueba técnica",
        "priority": "high"
     }'