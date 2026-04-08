from rest_framework import status, viewsets
from rest_framework.response import Response

from core.agent import classify_task, split_task
from .models import Task
from .serializers import TaskSerializer


class TaskViewSet(viewsets.ModelViewSet):
    queryset = Task.objects.all().order_by('-created_at')
    serializer_class = TaskSerializer

    def create(self, request, *args, **kwargs):
        """
        POST /tasks/

        Creates the main task, then:
        - uses split_task (tool: split_task_tool) to propose subtasks
        - creates each subtask as a Task row
        - uses classify_task (tool: classify_task_tool) on each subtask to set priority
        """
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        main_task: Task = serializer.save()

        try:
            split = split_task(main_task.id)
            subtasks_payload = split.get("subtasks", []) if isinstance(split, dict) else []
        except Exception as e:
            return Response(
                {"detail": "Failed to split task.", "error": str(e)},
                status=status.HTTP_502_BAD_GATEWAY,
            )

        created_subtasks: list[Task] = []
        classifications: dict[int, dict] = {}

        for st in subtasks_payload:
            if not isinstance(st, dict):
                continue

            title = str(st.get("title") or "").strip()
            description = str(st.get("description") or "").strip()
            if not title:
                continue

            subtask = Task.objects.create(
                title=title[:255],
                description=description,
                status=Task.Status.PENDING,
            )
            created_subtasks.append(subtask)

            try:
                classification = classify_task(subtask.id)
                if isinstance(classification, dict) and classification.get("priority"):
                    subtask.priority = classification["priority"]
                    subtask.save(update_fields=["priority", "updated_at"])
                    classifications[subtask.id] = classification
            except Exception as e:
                classifications[subtask.id] = {
                    "priority": subtask.priority,
                    "reason": f"Classification failed: {e}",
                }

        return Response(
            {
                "task": TaskSerializer(main_task, context=self.get_serializer_context()).data,
                "subtasks": [
                    {
                        "task": TaskSerializer(
                            st, context=self.get_serializer_context()
                        ).data,
                        "classification": classifications.get(st.id),
                    }
                    for st in created_subtasks
                ],
            },
            status=status.HTTP_201_CREATED,
        )

    # Alias so the intent matches the request wording ("post method").
    def post(self, request, *args, **kwargs):
        return self.create(request, *args, **kwargs)
