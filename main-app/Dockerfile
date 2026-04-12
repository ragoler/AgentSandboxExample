FROM python:3.11-slim

WORKDIR /app

COPY main-app/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main-app/main.py main-app/sandbox_provider.py main-app/mock_sandbox.py ./
COPY frontend /frontend

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
