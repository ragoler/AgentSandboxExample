FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY main.py sandbox_provider.py mock_sandbox.py ./

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
